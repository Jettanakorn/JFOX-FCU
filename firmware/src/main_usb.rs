//! JFOX FCU - USB CDC + MAVLink bring-up firmware.
//!
//! Standalone (no RTIC) bring-up binary, not the real flight application
//! (see `main.rs`/`jfox-fcu-flight` for that): reads the IMU, runs
//! `MadgwickFilter`, and reports real state over USB CDC as MAVLink v1 -
//! HEARTBEAT (1Hz, `flight::arming::ArmingFsm`'s real armed state - this
//! binary has no RC/command-link input so it can never actually arm, and
//! HEARTBEAT reports that honestly rather than a hardcoded "active"),
//! SYS_STATUS (1Hz, `flight::bit::BitReport`'s real IMU-init health), and
//! ATTITUDE (~4Hz, `MadgwickFilter`'s real estimate). See
//! `telemetry::mavlink` for the encoder, and `BUILD_AND_FLASH.md` for why
//! this exists as an interim MAVLink bridge rather than the project's
//! long-term GCS link (JFOXLink, not yet implemented).

#![no_std]
#![no_main]

use panic_probe as _;
use defmt_rtt as _;

use stm32f4::stm32f427 as pac;
use defmt::{info, warn};
use cortex_m_rt::entry;

use bsp::clocks::Clocks;
use hal::{spi::Spi, gpio::*};
use drivers::ms5611::{self, Ms5611, Osr};
use drivers::probe::{self, BusScan, Device};
use drivers::Mpu6000;
use flight::MadgwickFilter;
use flight::arming::{ArmingFsm, ArmRequest, PreArmChecks};
use flight::bit::{BitReport, BitTestId};
use telemetry::mavlink::{self, sensor_bits};

// USB imports
use usb_device::prelude::*;
use usbd_serial::SerialPort;
use synopsys_usb_otg::{UsbBus, UsbPeripheral};

/// USB device buffer
static mut EP_MEMORY: [u32; 1024] = [0; 1024];

/// USB OTG FS peripheral descriptor for `synopsys-usb-otg`'s `UsbBus`.
/// Zero-sized marker type - the register base address is fixed for this MCU
/// and `enable()` needs no runtime state, so there's nothing to store.
struct UsbPeripheralImpl;

unsafe impl UsbPeripheral for UsbPeripheralImpl {
    // Same base address already used elsewhere in this workspace - see
    // bsp::memory_map::USB_OTG_FS_BASE.
    const REGISTERS: *const () = bsp::memory_map::USB_OTG_FS_BASE as *const ();
    const HIGH_SPEED: bool = false; // OTG_FS = Full Speed only, no HS PHY
    // FIFO depth (32-bit words) and endpoint count for STM32F4's OTG_FS
    // peripheral - fixed by the silicon, not configurable. These are the
    // standard values for this IP block, used identically by every STM32F4
    // OTG_FS driver in the Rust embedded ecosystem (e.g. stm32f4xx-hal's
    // usb_fs feature).
    const FIFO_DEPTH_WORDS: usize = 320;
    const ENDPOINT_COUNT: usize = 4;

    /// Called internally by `synopsys_usb_otg::UsbBus` (see its own
    /// `UsbBus::enable`) - not something this file calls directly.
    fn enable() {
        unsafe {
            // Enable GPIOA clock, configure PA11/PA12 as AF10 (USB OTG FS),
            // enable the OTG_FS peripheral clock.
            let rcc = 0x4002_3800 as *mut u32;
            let ahb1enr = (rcc as usize + 0x30) as *mut u32;
            ahb1enr.write_volatile(ahb1enr.read_volatile() | (1 << 0)); // GPIOAEN

            let gpioa = 0x4002_0000 as *mut u32;
            let moder = (gpioa as usize + 0x00) as *mut u32;
            let afrh = (gpioa as usize + 0x24) as *mut u32;

            // PA11, PA12: Alternate function mode (10)
            let mut mode_val = moder.read_volatile();
            mode_val &= !(0x3 << 22); // Clear PA11
            mode_val |= 0x2 << 22; // Set PA11 to AF
            mode_val &= !(0x3 << 24); // Clear PA12
            mode_val |= 0x2 << 24; // Set PA12 to AF
            moder.write_volatile(mode_val);

            // PA11, PA12: AF10 (USB OTG FS)
            let mut afr_val = afrh.read_volatile();
            afr_val &= !(0xF << 12); // Clear PA11 AF
            afr_val |= 0xA << 12; // Set PA11 to AF10
            afr_val &= !(0xF << 16); // Clear PA12 AF
            afr_val |= 0xA << 16; // Set PA12 to AF10
            afrh.write_volatile(afr_val);

            // Enable USB OTG FS clock
            let ahb2enr = (rcc as usize + 0x34) as *mut u32;
            ahb2enr.write_volatile(ahb2enr.read_volatile() | (1 << 7)); // OTGFSEN
        }
    }

    fn ahb_frequency_hz(&self) -> u32 {
        bsp::clocks::HCLK_FREQ_HZ
    }
}

#[entry]
fn main() -> ! {
    info!("JFOX FCU v3.0 - USB CDC + MAVLink Firmware");
    info!("Hardware: PX4 FMUv2 family - 2.4.5 / Pixhawk 2.4.8 (STM32F427VIT6)");

    // Get peripherals (UsbPeripheralImpl talks to OTG_FS directly by fixed
    // register address rather than through `dp`, matching this workspace's
    // raw-register convention - see hal::spi/hal::can - so this binding is
    // only for the ownership/take-once safety property, not its fields).
    let _dp = pac::Peripherals::take().unwrap();

    // Configure system clocks to 168MHz (PLLQ gives USB its exact 48MHz)
    let clocks = unsafe { Clocks::configure() };
    info!("System clock: {}MHz", clocks.sysclk() / 1_000_000);

    // Initialize status LED on PE14
    info!("Initializing status LED (PE14)...");
    let mut led = unsafe { Pin::<'E', 14, Output>::new().into_output() };
    led.set_high(); // Turn on during initialization

    // Initialize USB peripheral - pin config and clock enable happen inside
    // UsbPeripheralImpl::enable(), called internally by UsbBus.
    info!("Initializing USB OTG FS...");

    let usb_bus = UsbBus::new(UsbPeripheralImpl, unsafe { &mut *core::ptr::addr_of_mut!(EP_MEMORY) });

    let mut serial = SerialPort::new(&usb_bus);

    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x26AC, 0x0011))
        .max_packet_size_0(64)
        .expect("64 is a valid max_packet_size_0 value (8/16/32/64)")
        .build();

    info!("USB CDC initialized!");

    // Initialize SPI1 - the shared internal sensor bus ("SPI_INT")
    info!("Initializing SPI1 (internal sensor bus)...");
    let mut spi1 = unsafe { Spi::<1>::new() };
    spi1.init_mode3(3); // APB2=84MHz, div=16 -> 5.25MHz

    // Probe the bus before anything claims it. Sensor population on the FMUv2
    // family is a per-unit build option, so what is fitted has to be asked
    // rather than assumed - see drivers::probe.
    let (scan, baro_prom) = {
        let mut scan = BusScan::empty();
        let mut mpu_cs = unsafe { Pin::<'C', 2, Output>::new().into_output() };
        let mut gyro_cs = unsafe { Pin::<'C', 13, Output>::new().into_output() };
        let mut mag_cs = unsafe { Pin::<'C', 15, Output>::new().into_output() };
        let mut baro_cs = unsafe { Pin::<'D', 7, Output>::new().into_output() };

        // Every CS idles high; a device left selected corrupts the next probe.
        let _ = mpu_cs.set_high();
        let _ = gyro_cs.set_high();
        let _ = mag_cs.set_high();
        let _ = baro_cs.set_high();

        scan.imu = probe::probe_imu(&mut spi1, &mut mpu_cs);
        scan.gyro = probe::probe_st(&mut spi1, &mut gyro_cs);
        scan.accel_mag = probe::probe_st(&mut spi1, &mut mag_cs);
        let (baro_dev, prom) = probe::probe_baro(&mut spi1, &mut baro_cs);
        scan.baro = baro_dev;
        (scan, prom)
    };
    scan.log();

    // Initialize MPU-6000 IMU
    info!("Initializing MPU-6000 IMU...");
    let mpu_cs = unsafe { Pin::<'C', 2, Output>::new().into_output() };
    let mut mpu6000 = Mpu6000::new(spi1, mpu_cs);
    let mut bit_report = BitReport::new();
    match mpu6000.init() {
        Ok(()) => {
            info!("MPU-6000 initialized successfully");
            bit_report.record(BitTestId::ImuCommunication, true);
        }
        Err(()) => {
            warn!("MPU-6000 initialization failed!");
            bit_report.record(BitTestId::ImuCommunication, false);
        }
    }

    // Barometer, if one answered the probe.
    //
    // This takes a second `Spi::<1>` handle aliasing the one `Mpu6000` now
    // owns. That is sound here and only here: `Spi` holds nothing but a base
    // address, `new()` does not reconfigure the bus (so this handle inherits
    // the mode-3 setup above, which both parts accept), and this is a single
    // threaded main loop with no interrupt touching SPI1 - the two are used
    // strictly in sequence, each asserting only its own chip select. It would
    // stop being sound the moment either moved into an interrupt.
    let mut spi_baro = unsafe { Spi::<1>::new() };
    let mut baro_cs = unsafe { Pin::<'D', 7, Output>::new().into_output() };
    let _ = baro_cs.set_high();
    let mut baro = if scan.baro == Device::Ms5611 {
        info!("MS5611 barometer present, PROM CRC verified");
        Some(Ms5611::from_prom(baro_prom, Osr::Osr1024))
    } else {
        info!("No barometer on this board - SCALED_PRESSURE will not be sent");
        None
    };
    let mut last_baro: Option<ms5611::Reading> = None;

    // Sensor bitmaps for SYS_STATUS, built from what actually answered. A bit
    // set here that nothing populates would be a claim the GCS cannot check.
    let mut sensors_present: u32 = 0;
    if scan.imu.is_present() {
        sensors_present |= sensor_bits::GYRO_3D | sensor_bits::ACCEL_3D;
    }
    if scan.gyro.is_present() {
        sensors_present |= sensor_bits::GYRO_3D_2;
    }
    if scan.accel_mag.is_present() {
        sensors_present |= sensor_bits::ACCEL_3D_2 | sensor_bits::MAG_3D;
    }
    if scan.baro == Device::Ms5611 {
        sensors_present |= sensor_bits::ABSOLUTE_PRESSURE;
    }

    // Initialize Madgwick filter
    let mut madgwick = MadgwickFilter::new(0.01);
    info!("Madgwick filter initialized");

    // Arming FSM: this binary has no RC/command-link input (see
    // flight::arming's module docs), so it's driven with ArmRequest::None
    // every tick and can never actually arm - that's an honest reflection
    // of what this bring-up binary can do, not a placeholder. HEARTBEAT's
    // armed flag genuinely always reads false here, rather than the
    // previous hardcoded "active" claim regardless of real state.
    let mut arming = ArmingFsm::new();

    led.set_low(); // Turn off LED to indicate init complete
    info!("Entering main loop...");

    let mut count = 0u32;
    let mut led_state = false;
    let mut attitude_send_count = 0u32;
    let mut mav_seq = 0u8;
    let mut startup_sent = false;
    const IMU_DT_S: f32 = 0.001; // 1kHz main loop

    let startup_msg = b"\r\n========================================\r\n\
JFOX FCU v3.0 - USB CDC + real MAVLink\r\n\
Hardware: STM32F427VIT6 @ 168MHz\r\n\
========================================\r\n\r\n\
[OK] USB CDC ready\r\n\
[OK] MAVLink HEARTBEAT/SYS_STATUS/ATTITUDE enabled\r\n\r\n";

    /// How long without a GCS HEARTBEAT before the command link is considered
    /// lost. 3 seconds is three missed 1Hz beats - long enough not to trip on
    /// one dropped frame, short enough to matter.
    const GCS_LINK_TIMEOUT_MS: u32 = 3000;

    let mut time_boot_ms: u32 = 0;
    let mut last_gyro = math::Vec3::zero();
    let mut last_imu: Option<drivers::mpu6000::ImuData> = None;

    // Command link state.
    let mut parser = mavlink::Parser::new();
    let mut pending_arm: Option<bool> = None;
    let mut gcs_heartbeat_age_ms: u32 = 0;
    let mut link_up = false;

    loop {
        // Poll USB - CRITICAL for USB operation!
        //
        // Draining the OUT endpoint is mandatory regardless of whether the
        // bytes are wanted: an endpoint that is never read fills after one
        // packet, NAKs everything after it, backs up the host's driver buffer
        // and blocks every host-side write. That is what froze QGroundControl
        // before 63eaee0. Now the bytes are also *used*.
        if usb_dev.poll(&mut [&mut serial]) {
            let mut buf = [0u8; 64];
            if let Ok(n) = serial.read(&mut buf) {
                for &b in &buf[..n] {
                    if let Some(msg) = parser.push(b) {
                        match msg {
                            mavlink::Message::Heartbeat => {
                                // Link liveness. Nothing acts on it yet, but a
                                // failsafe times out on the absence of this.
                                gcs_heartbeat_age_ms = 0;
                                link_up = true;
                            }
                            mavlink::Message::CommandLong { command, param1, .. } => {
                                let result = handle_command(command, param1, &mut pending_arm);
                                let ack = mavlink::encode_command_ack(mav_seq, command, result);
                                mav_seq = mav_seq.wrapping_add(1);
                                let _ = serial.write(&ack);
                            }
                        }
                    }
                }
            }

            if !startup_sent {
                let _ = serial.write(startup_msg);
                startup_sent = true;
            }
        }

        // Read IMU data
        let imu_ok = if let Ok(imu_data) = mpu6000.read_data() {
            madgwick.update(imu_data.gyro, imu_data.accel, IMU_DT_S);
            last_gyro = imu_data.gyro;
            last_imu = Some(imu_data);
            true
        } else {
            if count == 0 {
                warn!("Failed to read IMU data");
            }
            false
        };

        // Arming FSM: no command-link input yet (see the local comment
        // above where `arming` is constructed), so this genuinely never
        // arms - still real state, driven every tick like the real
        // control_task will be.
        // Arming FSM, now driven by a real command link. `pending_arm` is set
        // by an inbound COMMAND_LONG and held until cleared, so a single
        // command produces a sustained request - the FSM requires a debounced
        // hold to arm, which a one-tick pulse would never satisfy.
        let request = match pending_arm {
            Some(true) => ArmRequest::Arm,
            Some(false) => ArmRequest::Disarm,
            None => ArmRequest::None,
        };
        let checks = PreArmChecks { bit_passed: bit_report.all_passed(), attitude_valid: imu_ok };
        arming.update(request, checks, IMU_DT_S);

        // A disarm request is instantaneous by design, so it is consumed as
        // soon as the FSM has seen it. An arm request is held until the FSM
        // reaches Armed, or until the GCS countermands it.
        if pending_arm == Some(false) || (pending_arm == Some(true) && arming.output_allowed()) {
            pending_arm = None;
        }

        // Command-link liveness. Nothing acts on the timeout yet - this binary
        // drives no outputs - but the age is tracked so a failsafe has
        // something real to read when there is something to fail safe.
        if link_up {
            gcs_heartbeat_age_ms = gcs_heartbeat_age_ms.saturating_add(1);
            if gcs_heartbeat_age_ms > GCS_LINK_TIMEOUT_MS {
                warn!("GCS heartbeat lost after {}ms", gcs_heartbeat_age_ms);
                link_up = false;
            }
        }

        // Barometer conversions advance one tick at a time and never block -
        // see drivers::ms5611. A completed reading is held for the next
        // SCALED_PRESSURE send rather than triggering one, so telemetry rate
        // stays decoupled from conversion rate.
        if let Some(b) = baro.as_mut() {
            if let Some(reading) = b.tick(&mut spi_baro, &mut baro_cs) {
                last_baro = Some(reading);
            }
        }

        // ATTITUDE + SCALED_IMU @ ~4Hz (every 250 ticks of this 1kHz loop).
        attitude_send_count += 1;
        if attitude_send_count >= 250 {
            attitude_send_count = 0;
            let (roll, pitch, yaw) = madgwick.get_euler();
            let frame = mavlink::encode_attitude(mav_seq, time_boot_ms, roll, pitch, yaw, last_gyro.x, last_gyro.y, last_gyro.z);
            mav_seq = mav_seq.wrapping_add(1);
            let _ = serial.write(&frame);

            // SCALED_IMU is the sensor itself rather than the estimate - what
            // you plot to tell a bad IMU from a bad filter. Units are fixed by
            // the dialect: accel in milli-g, gyro in milli-rad/s. This
            // firmware works in g and rad/s, hence the x1000.
            if let Some(imu) = last_imu {
                let frame = mavlink::encode_scaled_imu(
                    mav_seq,
                    time_boot_ms,
                    (imu.accel.x * 1000.0) as i16,
                    (imu.accel.y * 1000.0) as i16,
                    (imu.accel.z * 1000.0) as i16,
                    (imu.gyro.x * 1000.0) as i16,
                    (imu.gyro.y * 1000.0) as i16,
                    (imu.gyro.z * 1000.0) as i16,
                    0, 0, 0, // no magnetometer driven on this board
                );
                mav_seq = mav_seq.wrapping_add(1);
                let _ = serial.write(&frame);
            }

            if let Some(r) = last_baro {
                let frame = mavlink::encode_scaled_pressure(
                    mav_seq,
                    time_boot_ms,
                    r.pressure_hpa(),
                    r.temperature_cdeg as i16,
                );
                mav_seq = mav_seq.wrapping_add(1);
                let _ = serial.write(&frame);
            }
        }

        // HEARTBEAT + SYS_STATUS @ 1Hz (every 1000 ticks).
        count += 1;
        if count >= 1000 {
            count = 0;
            led_state = !led_state;
            if led_state {
                led.set_high();
            } else {
                led.set_low();
            }

            let (roll, pitch, yaw) = madgwick.get_euler();
            info!(
                "Attitude: roll={} pitch={} yaw={} armed={}",
                (roll * 180.0 / core::f32::consts::PI) as i32,
                (pitch * 180.0 / core::f32::consts::PI) as i32,
                (yaw * 180.0 / core::f32::consts::PI) as i32,
                arming.output_allowed()
            );

            let hb = mavlink::encode_heartbeat(mav_seq, arming.output_allowed());
            mav_seq = mav_seq.wrapping_add(1);
            let _ = serial.write(&hb);

            // Health drops only for sensors this firmware actually drives and
            // that have actually failed. A detected-but-unsupported part
            // (L3GD20, LSM303D) stays present-and-healthy: nothing here has
            // grounds to call it broken.
            let health = if bit_report.all_passed() {
                sensors_present
            } else {
                sensors_present & !(sensor_bits::GYRO_3D | sensor_bits::ACCEL_3D)
            };
            let sys_status =
                mavlink::encode_sys_status_detailed(mav_seq, sensors_present, sensors_present, health);
            mav_seq = mav_seq.wrapping_add(1);
            let _ = serial.write(&sys_status);
        }

        time_boot_ms = time_boot_ms.wrapping_add(1);

        // Simple delay (~1ms at 168MHz)
        delay_cycles(168_000);
    }
}

/// Simple delay function (approximate)
#[inline(always)]
fn delay_cycles(cycles: u32) {
    for _ in 0..cycles {
        cortex_m::asm::nop();
    }
}

/// Dispatch one inbound COMMAND_LONG, returning the `MAV_RESULT` to ACK with.
///
/// Every command gets an honest answer, including the ones this firmware
/// cannot do. `UNSUPPORTED` is a useful reply; silence is not - a GCS that
/// receives no ACK simply retries forever, and the operator learns nothing
/// about why the vehicle ignored them.
///
/// Note what is deliberately *not* here: nothing in this binary drives a motor
/// output. Arming sets a state flag that HEARTBEAT then reports. That is what
/// makes accepting an arm command over USB reasonable at this stage - the
/// property under test is the FSM's debounce and pre-arm gating, not thrust.
fn handle_command(command: u16, param1: f32, pending_arm: &mut Option<bool>) -> u8 {
    use telemetry::mavlink::{cmd, result};

    match command {
        cmd::COMPONENT_ARM_DISARM => {
            // param1: 1 = arm, 0 = disarm. Anything else is a malformed
            // request rather than a a default-to-disarm, and is refused so the
            // sender finds out.
            if param1 == 1.0 {
                info!("COMMAND_LONG: arm requested");
                *pending_arm = Some(true);
                result::ACCEPTED
            } else if param1 == 0.0 {
                info!("COMMAND_LONG: disarm requested");
                *pending_arm = Some(false);
                result::ACCEPTED
            } else {
                warn!("COMMAND_LONG: ARM_DISARM with invalid param1, refusing");
                result::DENIED
            }
        }

        cmd::NAV_RETURN_TO_LAUNCH => {
            // Refused honestly rather than accepted and ignored. RTL needs a
            // position estimate and a navigation controller, and this binary
            // has neither a GPS nor any navigation at all.
            warn!("COMMAND_LONG: RTL requested but unsupported - no GPS, no navigation");
            result::UNSUPPORTED
        }

        other => {
            warn!("COMMAND_LONG: unsupported command {}", other);
            result::UNSUPPORTED
        }
    }
}
