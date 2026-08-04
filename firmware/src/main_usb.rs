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
use telemetry::mavlink::{self, sensor_bits, severity};
use common::params::{ParamTable, MAV_PARAM_TYPE_REAL32};

/// Reported in AUTOPILOT_VERSION. Encoded as MAVLink expects: one byte each of
/// major, minor, patch, and release type, packed little-endian.
const FLIGHT_SW_VERSION: u32 = 0x0001_0000; // 0.1.0

/// SPI1 divisor for **register** access: APB2 84MHz / 128 = 656kHz.
///
/// The MPU-6000 specifies a 1MHz maximum for register read/write. This is the
/// slowest-but-one prescaler that fits under it, and it applies to every part
/// on the internal bus during identification and configuration.
const SPI_DIV_REGISTER: u8 = 6;

/// SPI1 divisor for sensor **data** bursts: 84MHz / 16 = 5.25MHz.
///
/// The MPU-6000 allows 20MHz for the sensor/interrupt register block, the
/// MS5611 allows 20MHz, and the ST parts allow 10MHz - so this is comfortably
/// inside every part's limit while being fast enough for a 1kHz burst read.
const SPI_DIV_DATA: u8 = 3;

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
    //
    // Two speeds, and the slow one is mandatory rather than cautious. The
    // MPU-6000 datasheet limits SPI **register** access to 1MHz; only the
    // sensor and interrupt data registers (59-96, 100-104) tolerate 20MHz.
    // Everything init() touches - WHO_AM_I, PWR_MGMT_1, the CONFIG and
    // range registers, SMPLRT_DIV - is a register access, so configuring
    // the part at 5.25MHz runs it at over five times its specified maximum
    // and the reads come back unreliable. PX4's own MPU6000 driver carries
    // the same low/high split for this reason.
    //
    // The probe runs at the slow speed too: it is all WHO_AM_I reads.
    info!("Initializing SPI1 (internal sensor bus)...");
    let mut spi1 = unsafe { Spi::<1>::new() };
    spi1.init_mode3(SPI_DIV_REGISTER); // 84MHz/128 = 656kHz, inside the 1MHz register limit

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
    let imu_variant = match mpu6000.init() {
        Ok(v) => {
            info!("IMU initialized: {}", v.name());
            bit_report.record(BitTestId::ImuCommunication, true);
            Some(v)
        }
        Err(()) => {
            warn!("IMU initialization failed!");
            bit_report.record(BitTestId::ImuCommunication, false);
            None
        }
    };

    // Configuration is done, so the bus can come up to data speed. Reads from
    // here on are the ACCEL_XOUT_H burst and the MS5611's ADC, both of which
    // their datasheets allow at 20MHz.
    //
    // Reconfiguring through a second handle for the same reason the barometer
    // uses one: `Spi` holds only a base address, and `init_mode3` rewrites CR1
    // for the peripheral regardless of which handle calls it. Single-threaded
    // loop, no interrupt touches SPI1.
    {
        let mut spi_speed = unsafe { Spi::<1>::new() };
        spi_speed.init_mode3(SPI_DIV_DATA);
        info!("SPI1 raised to data speed (84MHz/16 = 5.25MHz)");
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

    // Parameter protocol state. `param_stream` is the index of the next
    // PARAM_VALUE to send during a full-list download; one goes out per
    // millisecond tick rather than all at once, because 26 x 33 bytes pushed
    // into the IN endpoint in a single pass would overrun it and the frames
    // would be dropped silently by `let _ = serial.write(..)`.
    let mut params = ParamTable::new();
    let mut param_stream: Option<u16> = None;
    let mut send_version = false;
    let mut status_report: Option<u8> = None;

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
                                let result = handle_command(
                                    command,
                                    param1,
                                    &mut pending_arm,
                                    &mut send_version,
                                );
                                let ack = mavlink::encode_command_ack(mav_seq, command, result);
                                mav_seq = mav_seq.wrapping_add(1);
                                let _ = serial.write(&ack);
                            }

                            mavlink::Message::ParamRequestList => {
                                info!("PARAM_REQUEST_LIST: streaming {} parameters", params.count());
                                param_stream = Some(0);
                            }

                            mavlink::Message::ParamRequestRead { param_index, param_id } => {
                                // index -1 means "by name" - how a GCS
                                // re-requests a parameter whose reply it lost.
                                let idx = if param_index >= 0 {
                                    Some(param_index as usize)
                                } else {
                                    ParamTable::index_of(&param_id)
                                };
                                if let Some(i) = idx {
                                    send_param(&mut serial, &params, i, &mut mav_seq);
                                } else {
                                    warn!("PARAM_REQUEST_READ for an unknown parameter");
                                }
                            }

                            mavlink::Message::ParamSet { param_id, param_value } => {
                                match params.set(&param_id, param_value) {
                                    Ok(i) => {
                                        info!("PARAM_SET accepted, index {}", i);
                                        // Echoing the stored value back is how
                                        // a GCS confirms the write. Echoing
                                        // what we stored - not what was sent -
                                        // is what makes a clamped or refused
                                        // write visible to the operator.
                                        send_param(&mut serial, &params, i, &mut mav_seq);
                                    }
                                    Err(e) => {
                                        warn!("PARAM_SET refused: {}", defmt::Debug2Format(&e));
                                        // Refusals still echo the *current*
                                        // value, so the GCS updates its view
                                        // to the truth rather than keeping the
                                        // value it optimistically displayed.
                                        if let Some(i) = ParamTable::index_of(&param_id) {
                                            send_param(&mut serial, &params, i, &mut mav_seq);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if !startup_sent {
                let _ = serial.write(startup_msg);
                startup_sent = true;
                // Queue the boot report. Without a debug probe, STATUSTEXT is
                // the only way an operator sees which sensors answered - and
                // "attitude is frozen at zero" is indistinguishable from a
                // dozen other faults until you know whether the IMU is even
                // there. Queued rather than sent here so the frames go out one
                // per tick and do not overrun the IN endpoint.
                status_report = Some(0);
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

        // Boot report over STATUSTEXT, one line per tick.
        if let Some(line) = status_report {
            let (sev, text): (u8, &[u8]) = match line {
                0 => (
                    severity::INFO,
                    match imu_variant {
                        Some(drivers::mpu6000::ImuVariant::Mpu6000) => b"IMU: MPU-6000 OK" as &[u8],
                        Some(drivers::mpu6000::ImuVariant::Icm20602) => b"IMU: ICM-20602 OK (compat)",
                        Some(drivers::mpu6000::ImuVariant::Icm20608) => b"IMU: ICM-20608 OK (compat)",
                        None => b"IMU: INIT FAILED - attitude will not work",
                    },
                ),
                1 => (
                    if imu_variant.is_some() { severity::INFO } else { severity::ERROR },
                    match scan.imu {
                        Device::Absent => b"IMU bus: nothing answered at CS PC2" as &[u8],
                        Device::Unknown(_) => b"IMU bus: unknown device ID at CS PC2",
                        _ => b"IMU bus: device detected at CS PC2",
                    },
                ),
                2 => (
                    severity::INFO,
                    if scan.baro == Device::Ms5611 {
                        b"Baro: MS5611 OK" as &[u8]
                    } else {
                        b"Baro: none fitted"
                    },
                ),
                3 => (
                    severity::INFO,
                    match scan.gyro {
                        Device::Absent => b"Gyro2: none" as &[u8],
                        _ => b"Gyro2: detected, no driver",
                    },
                ),
                _ => (
                    severity::INFO,
                    match scan.accel_mag {
                        Device::Absent => b"AccelMag: none" as &[u8],
                        _ => b"AccelMag: detected, no driver",
                    },
                ),
            };
            let frame = mavlink::encode_statustext(mav_seq, sev, text);
            mav_seq = mav_seq.wrapping_add(1);
            let _ = serial.write(&frame);
            status_report = if line < 4 { Some(line + 1) } else { None };
        }

        // Stream the parameter list, one per tick. A GCS tracks which indices
        // it has received and re-requests gaps, so what matters is that every
        // index is sent exactly once with the true count - not the rate.
        if let Some(i) = param_stream {
            send_param(&mut serial, &params, i as usize, &mut mav_seq);
            param_stream = if i + 1 < params.count() { Some(i + 1) } else { None };
        }

        if send_version {
            send_version = false;
            let frame = mavlink::encode_autopilot_version(mav_seq, FLIGHT_SW_VERSION);
            mav_seq = mav_seq.wrapping_add(1);
            let _ = serial.write(&frame);
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
/// Send one PARAM_VALUE.
///
/// `param_index` is the parameter's real position and `param_count` the true
/// total, on every message. A GCS tracks which indices it has seen and
/// re-requests the gaps, so sending a running counter instead of the true index
/// is the classic way to make a parameter download stall just short of
/// complete.
fn send_param<B: usb_device::bus::UsbBus>(
    serial: &mut SerialPort<'_, B>,
    params: &ParamTable,
    index: usize,
    mav_seq: &mut u8,
) {
    let (Some(id), Some(value)) = (ParamTable::name_bytes(index), params.get(index)) else {
        return;
    };
    let frame = mavlink::encode_param_value(
        *mav_seq,
        &id,
        value,
        MAV_PARAM_TYPE_REAL32,
        params.count(),
        index as u16,
    );
    *mav_seq = mav_seq.wrapping_add(1);
    let _ = serial.write(&frame);
}

fn handle_command(
    command: u16,
    param1: f32,
    pending_arm: &mut Option<bool>,
    send_version: &mut bool,
) -> u8 {
    use telemetry::mavlink::{cmd, result};

    match command {
        cmd::REQUEST_AUTOPILOT_CAPABILITIES => {
            *send_version = true;
            result::ACCEPTED
        }

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
