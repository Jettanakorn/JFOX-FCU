//! JFOX FCU - Simplified Bare-metal Rust Flight Controller
//! Basic version without RTIC for initial hardware testing

#![no_std]
#![no_main]

use panic_probe as _;
use defmt_rtt as _;

use stm32f4 as _; // Provides device interrupt vectors
use defmt::{info, warn};
use cortex_m_rt::entry;
use core::fmt::Write;

use bsp::clocks::Clocks;
use hal::{spi::Spi, uart::Uart, gpio::*};
use drivers::Mpu6000;
use flight::MadgwickFilter;

#[entry]
fn main() -> ! {
    info!("JFOX FCU - Flight Controller Firmware v2.0 (LED + UART)");
    info!("Hardware: PX4FMUv2.4.5 (STM32F427VIT6)");

    // Configure system clocks to 180MHz
    let clocks = unsafe { Clocks::configure() };
    info!("System clock: {}MHz", clocks.sysclk() / 1_000_000);

    // Initialize status LED on PE14
    info!("Initializing status LED (PE14)...");
    let mut led = unsafe { Pin::<'E', 14, Output>::new().into_output() };
    led.set_high(); // Turn on during initialization

    // Initialize UART1 for debug output (TX=PA9, RX=PA10)
    // UART1 is more likely connected to USB serial on PX4 boards
    info!("Initializing UART1 @ 115200 baud...");
    let mut uart = unsafe { Uart::<1>::new() };
    uart.init(115200);

    // Send startup message via UART
    uart.write_str("\r\n========================================\r\n");
    uart.write_str("JFOX FCU v2.0 - Rust Flight Controller\r\n");
    uart.write_str("Hardware: STM32F427VIT6 @ 180MHz\r\n");
    uart.write_str("========================================\r\n\r\n");

    // Initialize SPI1 for MPU-6000
    info!("Initializing SPI1 for MPU-6000...");
    uart.write_str("[INIT] SPI1 for MPU-6000...\r\n");
    let mut spi1 = unsafe { Spi::<1>::new() };
    spi1.init_mode3(3); // APB2=90MHz, div=16 -> 5.625MHz

    // Initialize MPU-6000 IMU
    info!("Initializing MPU-6000 IMU...");
    uart.write_str("[INIT] MPU-6000 IMU...\r\n");
    let mpu_cs = unsafe { Pin::<'C', 2, Output>::new().into_output() };
    let mut mpu6000 = Mpu6000::new(spi1, mpu_cs);
    match mpu6000.init() {
        Ok(()) => {
            info!("MPU-6000 initialized successfully");
            uart.write_str("[OK]   MPU-6000 ready!\r\n");
        }
        Err(()) => {
            warn!("MPU-6000 initialization failed!");
            uart.write_str("[WARN] MPU-6000 failed!\r\n");
        }
    }

    // Initialize Madgwick filter
    let mut madgwick = MadgwickFilter::new(0.01);
    info!("Madgwick filter initialized");
    uart.write_str("[OK]   Madgwick AHRS filter ready\r\n");

    uart.write_str("\r\n[START] Main loop running...\r\n");
    uart.write_str("LED will blink at 1Hz\r\n");
    uart.write_str("Attitude updated at 1Hz\r\n\r\n");

    led.set_low(); // Turn off LED to indicate init complete
    info!("Entering main loop...");

    let mut count = 0u32;
    let mut led_state = false;
    let mut loop_count = 0u32;

    loop {
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

                // Log to UART (visible on serial terminal)
                let _ = write!(
                    uart,
                    "[{:05}] Roll:{:6.1}° Pitch:{:6.1}° Yaw:{:6.1}° Temp:{:5.1}°C LED:{}\r\n",
                    loop_count,
                    roll.to_degrees(),
                    pitch.to_degrees(),
                    yaw.to_degrees(),
                    imu_data.temp,
                    if led_state { "ON " } else { "OFF" }
                );

                count = 0;
            }
        } else {
            // IMU read failed
            if count == 0 {
                warn!("Failed to read IMU data");
                uart.write_str("[ERROR] IMU read failed\r\n");
            }
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
