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
use drivers::Mpu6000;
use flight::MadgwickFilter;
use flight::arming::{ArmingFsm, ArmRequest, PreArmChecks};
use flight::bit::{BitReport, BitTestId};
use telemetry::mavlink;

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

    // Initialize SPI1 for MPU-6000
    info!("Initializing SPI1 for MPU-6000...");
    let mut spi1 = unsafe { Spi::<1>::new() };
    spi1.init_mode3(3); // APB2=84MHz, div=16 -> 5.25MHz

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

    let mut time_boot_ms: u32 = 0;
    let mut last_gyro = math::Vec3::zero();

    loop {
        // Poll USB - CRITICAL for USB operation!
        if usb_dev.poll(&mut [&mut serial]) {
            // Drain the CDC OUT endpoint and discard what arrives. This
            // binary has no command link, so the bytes are genuinely not
            // wanted - but an OUT endpoint that is never read fills after
            // one packet and then NAKs every transaction that follows. The
            // host's driver buffer backs up behind it and every host-side
            // write blocks: the port opens, reads fine, and times out on
            // write. That is what hung QGroundControl, and it is why this
            // read is not optional just because the data is unused.
            let mut discard = [0u8; 64];
            let _ = serial.read(&mut discard);

            if !startup_sent {
                let _ = serial.write(startup_msg);
                startup_sent = true;
            }
        }

        // Read IMU data
        let imu_ok = if let Ok(imu_data) = mpu6000.read_data() {
            madgwick.update(imu_data.gyro, imu_data.accel, IMU_DT_S);
            last_gyro = imu_data.gyro;
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
        let checks = PreArmChecks { bit_passed: bit_report.all_passed(), attitude_valid: imu_ok };
        arming.update(ArmRequest::None, checks, IMU_DT_S);

        // ATTITUDE @ ~4Hz (every 250 ticks of this 1kHz loop).
        attitude_send_count += 1;
        if attitude_send_count >= 250 {
            attitude_send_count = 0;
            let (roll, pitch, yaw) = madgwick.get_euler();
            let frame = mavlink::encode_attitude(mav_seq, time_boot_ms, roll, pitch, yaw, last_gyro.x, last_gyro.y, last_gyro.z);
            mav_seq = mav_seq.wrapping_add(1);
            let _ = serial.write(&frame);
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

            let sys_status = mavlink::encode_sys_status(mav_seq, bit_report.all_passed());
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
