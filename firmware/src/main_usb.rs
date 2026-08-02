//! JFOX FCU v3.0 - USB CDC + MAVLink Compatible Firmware
//!
//! This version implements:
//! - USB CDC (virtual COM port) for Mission Planner compatibility
//! - Basic MAVLink heartbeat messages
//! - Same LED status and IMU functionality as v2.0

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

// USB imports
use usb_device::prelude::*;
use usbd_serial::SerialPort;
use synopsys_usb_otg::UsbBus;

/// USB device buffer
static mut EP_MEMORY: [u32; 1024] = [0; 1024];

/// MAVLink heartbeat packet (MAVLink v1 format) - 15 bytes total
const MAVLINK_HEARTBEAT: [u8; 15] = [
    0xFE,       // STX (start byte)
    0x09,       // Length (9 bytes payload)
    0x00,       // Sequence
    0x01,       // System ID
    0x01,       // Component ID
    0x00,       // Message ID: HEARTBEAT
    // Payload (9 bytes):
    0x00, 0x00, 0x00, 0x00,  // custom_mode (u32)
    0x06,                     // type: MAV_TYPE_GENERIC (6)
    0x00,                     // autopilot: MAV_AUTOPILOT_GENERIC (0)
    0x00,                     // base_mode
    0x04,                     // system_status: MAV_STATE_ACTIVE (4)
    0x03,                     // mavlink_version (3)
];

#[entry]
fn main() -> ! {
    info!("JFOX FCU v3.0 - USB CDC + MAVLink Firmware");
    info!("Hardware: PX4FMUv2.4.5 (STM32F427VIT6)");

    // Get peripherals
    let dp = pac::Peripherals::take().unwrap();

    // Configure system clocks to 180MHz
    let clocks = unsafe { Clocks::configure() };
    info!("System clock: {}MHz", clocks.sysclk() / 1_000_000);

    // Initialize status LED on PE14
    info!("Initializing status LED (PE14)...");
    let mut led = unsafe { Pin::<'E', 14, Output>::new().into_output() };
    led.set_high(); // Turn on during initialization

    // Initialize USB pins (PA11=DM, PA12=DP) as AF10
    info!("Configuring USB pins...");
    unsafe {
        // Enable GPIOA clock
        let rcc = 0x4002_3800 as *mut u32;
        let ahb1enr = (rcc as usize + 0x30) as *mut u32;
        ahb1enr.write_volatile(ahb1enr.read_volatile() | (1 << 0)); // GPIOAEN

        // Configure PA11 and PA12 as AF10 (USB OTG FS)
        let gpioa = 0x4002_0000 as *mut u32;
        let moder = (gpioa as usize + 0x00) as *mut u32;
        let afrh = (gpioa as usize + 0x24) as *mut u32;

        // PA11, PA12: Alternate function mode (10)
        let mut mode_val = moder.read_volatile();
        mode_val &= !(0x3 << 22); // Clear PA11
        mode_val |= 0x2 << 22;    // Set PA11 to AF
        mode_val &= !(0x3 << 24); // Clear PA12
        mode_val |= 0x2 << 24;    // Set PA12 to AF
        moder.write_volatile(mode_val);

        // PA11, PA12: AF10 (USB OTG FS)
        let mut afr_val = afrh.read_volatile();
        afr_val &= !(0xF << 12); // Clear PA11 AF
        afr_val |= 0xA << 12;    // Set PA11 to AF10
        afr_val &= !(0xF << 16); // Clear PA12 AF
        afr_val |= 0xA << 16;    // Set PA12 to AF10
        afrh.write_volatile(afr_val);

        // Enable USB OTG FS clock
        let ahb2enr = (rcc as usize + 0x34) as *mut u32;
        ahb2enr.write_volatile(ahb2enr.read_volatile() | (1 << 7)); // OTGFSEN
    }

    // Initialize USB peripheral
    info!("Initializing USB OTG FS...");

    let usb_bus = UsbBus::new(dp.OTG_FS_GLOBAL, dp.OTG_FS_DEVICE, dp.OTG_FS_PWRCLK, unsafe { &mut EP_MEMORY });

    let mut serial = SerialPort::new(&usb_bus);

    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x26AC, 0x0011))
        .max_packet_size_0(64)
        .build();

    info!("USB CDC initialized!");

    // Initialize SPI1 for MPU-6000
    info!("Initializing SPI1 for MPU-6000...");
    let mut spi1 = unsafe { Spi::<1>::new() };
    spi1.init_mode3(3); // APB2=90MHz, div=16 -> 5.625MHz

    // Initialize MPU-6000 IMU
    info!("Initializing MPU-6000 IMU...");
    let mpu_cs = unsafe { Pin::<'C', 2, Output>::new().into_output() };
    let mut mpu6000 = Mpu6000::new(spi1, mpu_cs);
    match mpu6000.init() {
        Ok(()) => {
            info!("MPU-6000 initialized successfully");
        }
        Err(()) => {
            warn!("MPU-6000 initialization failed!");
        }
    }

    // Initialize Madgwick filter
    let mut madgwick = MadgwickFilter::new(0.01);
    info!("Madgwick filter initialized");

    // Send startup message via USB (buffered)
    let startup_msg = b"\r\n========================================\r\n\
JFOX FCU v3.0 - USB CDC + MAVLink\r\n\
Hardware: STM32F427VIT6 @ 180MHz\r\n\
========================================\r\n\r\n\
[OK] USB CDC ready\r\n\
[OK] MAVLink heartbeat enabled\r\n\
[OK] Connect with Mission Planner!\r\n\r\n";

    led.set_low(); // Turn off LED to indicate init complete
    info!("Entering main loop...");

    let mut count = 0u32;
    let mut led_state = false;
    let mut loop_count = 0u32;
    let mut usb_count = 0u32;
    let mut heartbeat_seq = 0u8;
    let mut startup_sent = false;

    loop {
        // Poll USB - CRITICAL for USB operation!
        if usb_dev.poll(&mut [&mut serial]) {
            // USB activity detected
            if !startup_sent {
                let _ = serial.write(startup_msg);
                startup_sent = true;
            }
        }

        // Read IMU data
        if let Ok(imu_data) = mpu6000.read_data() {
            // Update Madgwick filter
            madgwick.update(
                imu_data.gyro,
                imu_data.accel,
                0.001, // 1kHz = 1ms = 0.001s
            );

            // Update every 1000 samples (1Hz at 1kHz sample rate)
            count += 1;
            if count >= 1000 {
                // Toggle LED
                led_state = !led_state;
                if led_state {
                    led.set_high();
                } else {
                    led.set_low();
                }

                // Get attitude
                let (roll, pitch, yaw) = madgwick.get_euler();
                loop_count += 1;

                // Log to RTT (requires ST-Link)
                info!(
                    "Attitude: roll={} pitch={} yaw={} temp={}",
                    roll.to_degrees() as i32,
                    pitch.to_degrees() as i32,
                    yaw.to_degrees() as i32,
                    imu_data.temp as i32
                );

                // Send MAVLink heartbeat (1Hz)
                let mut heartbeat = MAVLINK_HEARTBEAT;
                heartbeat[2] = heartbeat_seq; // Update sequence
                heartbeat_seq = heartbeat_seq.wrapping_add(1);

                // Send heartbeat packet
                let _ = serial.write(&heartbeat);

                // Also send human-readable status (simple format)
                let msg = if led_state {
                    b"[IMU] OK LED:ON\r\n"
                } else {
                    b"[IMU] OK LED:OFF\r\n"
                };
                let _ = serial.write(msg);

                count = 0;
            }
        } else {
            // IMU read failed
            if count == 0 {
                warn!("Failed to read IMU data");
                let _ = serial.write(b"[ERROR] IMU read failed\r\n");
            }
        }

        // Send periodic heartbeat even if IMU fails (every ~100ms)
        usb_count += 1;
        if usb_count >= 100 {
            let mut heartbeat = MAVLINK_HEARTBEAT;
            heartbeat[2] = heartbeat_seq;
            heartbeat_seq = heartbeat_seq.wrapping_add(1);
            let _ = serial.write(&heartbeat);
            usb_count = 0;
        }

        // Simple delay (~1ms at 180MHz)
        delay_cycles(180_000);
    }
}

/// Simple delay function (approximate)
#[inline(always)]
fn delay_cycles(cycles: u32) {
    for _ in 0..cycles {
        cortex_m::asm::nop();
    }
}
