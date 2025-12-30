//! JFOX FCU - Bare-metal Rust Flight Controller
//!
//! This is the main firmware application for the JFOX FCU based on PX4FMUv2.4.5 hardware.
//! It implements a real-time flight control system using RTIC (Real-Time Interrupt-driven Concurrency).
//!
//! Hardware:
//! - STM32F427VIT6 @ 180MHz
//! - MPU-6000 IMU @ 1kHz
//! - MS5611 Barometer
//! - 8x PWM outputs for motors/servos
//!
//! Tasks:
//! - IMU sampling @ 1kHz (priority 3)
//! - Sensor fusion @ 1kHz (priority 3)
//! - Control loop @ 500Hz (priority 2)
//! - Motor output @ 400Hz (priority 1)

#![no_std]
#![no_main]

use panic_probe as _;
use defmt_rtt as _;

use defmt::{info, warn, error};
use rtic_monotonics::systick::prelude::*;
use stm32f4::stm32f427 as pac;

use bsp::clocks::Clocks;
use hal::{gpio::*, spi::*};
use drivers::Mpu6000;
use math::{Vec3, Quat, PidController};
use flight::MadgwickFilter;

// Task rates
const IMU_RATE_HZ: u32 = 1000;
const CONTROL_RATE_HZ: u32 = 500;
const MOTOR_RATE_HZ: u32 = 400;

#[rtic::app(device = pac, dispatchers = [EXTI0, EXTI1, EXTI2, EXTI3])]
mod app {
    use super::*;

    #[shared]
    struct Shared {
        /// Current attitude quaternion
        attitude: Quat,

        /// Angular rates from gyroscope (rad/s)
        gyro_rates: Vec3,

        /// Linear acceleration (m/s²)
        accel: Vec3,

        /// Armed state
        armed: bool,

        /// Temperature (°C)
        temperature: f32,
    }

    #[local]
    struct Local {
        /// MPU-6000 IMU driver
        mpu6000: Mpu6000<Spi<1>>,

        /// Madgwick sensor fusion filter
        madgwick: MadgwickFilter,

        /// Roll PID controller (outer loop: attitude)
        roll_pid: PidController,

        /// Pitch PID controller (outer loop: attitude)
        pitch_pid: PidController,

        /// Yaw PID controller (rate control)
        yaw_pid: PidController,

        /// Status LED (for debugging)
        led: Option<Pin<'E', 14, Output>>,
    }

    #[init]
    fn init(ctx: init::Context) -> (Shared, Local) {
        info!("JFOX FCU - Flight Controller Firmware");
        info!("Hardware: PX4FMUv2.4.5 (STM32F427VIT6)");
        info!("Build: {}", env!("CARGO_PKG_VERSION"));

        // Configure system clocks to 180MHz
        let clocks = unsafe { Clocks::configure() };
        info!("System clock configured: {}MHz", clocks.sysclk() / 1_000_000);

        // Initialize SysTick monotonic timer @ 1kHz
        let systick_token = rtic_monotonics::create_systick_token!();
        Systick::start(ctx.core.SYST, clocks.sysclk(), systick_token);

        // Initialize GPIO for status LED (optional, for debugging)
        let led = None; // TODO: Configure actual LED pin

        // Initialize SPI1 for MPU-6000
        info!("Initializing SPI1 for MPU-6000...");
        let mut spi1 = unsafe { Spi::<1>::new() };
        // SPI1 on APB2 (90MHz), divide by 16 => 5.625MHz (MPU-6000 max = 20MHz)
        spi1.init_mode3(3);

        // Initialize MPU-6000 IMU
        info!("Initializing MPU-6000 IMU...");
        let mut mpu6000 = Mpu6000::new(spi1);
        match mpu6000.init() {
            Ok(()) => info!("MPU-6000 initialized successfully"),
            Err(()) => {
                error!("MPU-6000 initialization failed!");
                // In a real system, we'd enter a safe mode here
            }
        }

        // Initialize Madgwick filter
        // Beta = 0.041 is tuned for ~100Hz, we're running at 1kHz so use lower value
        let madgwick = MadgwickFilter::new(0.01);
        info!("Madgwick filter initialized (beta=0.01)");

        // Initialize PID controllers
        // Tuning values (placeholder - need to be tuned on actual hardware)
        let roll_pid = PidController::new(4.5, 0.0, 0.05, 1.0);
        let pitch_pid = PidController::new(4.5, 0.0, 0.05, 1.0);
        let yaw_pid = PidController::new(4.0, 0.0, 0.0, 1.0);
        info!("PID controllers initialized");

        // Spawn periodic tasks
        imu_task::spawn().ok();
        control_task::spawn().ok();
        motor_task::spawn().ok();
        heartbeat_task::spawn().ok();

        info!("=".repeat(50));
        info!("Initialization complete - entering main loop");
        info!("=".repeat(50));

        (
            Shared {
                attitude: Quat::identity(),
                gyro_rates: Vec3::zero(),
                accel: Vec3::zero(),
                armed: false,
                temperature: 0.0,
            },
            Local {
                mpu6000,
                madgwick,
                roll_pid,
                pitch_pid,
                yaw_pid,
                led,
            },
        )
    }

    /// IMU sampling and sensor fusion @ 1kHz
    ///
    /// This task runs at the highest priority to ensure timely sensor readings.
    /// It reads accelerometer and gyroscope data from the MPU-6000 and updates
    /// the Madgwick filter to estimate attitude.
    #[task(priority = 3, local = [mpu6000, madgwick, sample_count: u32 = 0], shared = [attitude, gyro_rates, accel, temperature])]
    async fn imu_task(mut ctx: imu_task::Context) {
        loop {
            // Read IMU data
            match ctx.local.mpu6000.read_data() {
                Ok(imu_data) => {
                    // Update Madgwick filter with new sensor data
                    ctx.local.madgwick.update(
                        imu_data.gyro,
                        imu_data.accel,
                        1.0 / IMU_RATE_HZ as f32,
                    );

                    // Get current attitude
                    let attitude = ctx.local.madgwick.get_quaternion();

                    // Update shared state
                    (
                        &mut ctx.shared.attitude,
                        &mut ctx.shared.gyro_rates,
                        &mut ctx.shared.accel,
                        &mut ctx.shared.temperature,
                    )
                        .lock(|att, gyro, acc, temp| {
                            *att = attitude;
                            *gyro = imu_data.gyro;
                            *acc = imu_data.accel;
                            *temp = imu_data.temp;
                        });

                    // Log every 1000 samples (1Hz)
                    *ctx.local.sample_count += 1;
                    if *ctx.local.sample_count >= IMU_RATE_HZ {
                        let (roll, pitch, yaw) = attitude.to_euler();
                        info!(
                            "Attitude: roll={:.1}° pitch={:.1}° yaw={:.1}° temp={:.1}°C",
                            roll.to_degrees(),
                            pitch.to_degrees(),
                            yaw.to_degrees(),
                            imu_data.temp
                        );
                        *ctx.local.sample_count = 0;
                    }
                }
                Err(()) => {
                    warn!("Failed to read IMU data");
                }
            }

            // Wait 1ms (1kHz update rate)
            Systick::delay(1_u32.millis()).await;
        }
    }

    /// Attitude control loop @ 500Hz
    ///
    /// This task implements the flight control algorithms:
    /// - Outer loop: Attitude control (converts attitude error to desired rate)
    /// - Inner loop: Rate control (converts rate error to motor commands)
    #[task(priority = 2, local = [roll_pid, pitch_pid, yaw_pid], shared = [attitude, gyro_rates, armed])]
    async fn control_task(mut ctx: control_task::Context) {
        loop {
            // Check if armed
            let is_armed = ctx.shared.armed.lock(|a| *a);

            if is_armed {
                // Get current attitude and rates
                let (attitude, gyro) = (
                    &mut ctx.shared.attitude,
                    &mut ctx.shared.gyro_rates,
                )
                    .lock(|att, gyro| (*att, *gyro));

                let (roll, pitch, yaw) = attitude.to_euler();

                // TODO: Get desired attitude from RC input
                // For now, use zero (level flight)
                let desired_roll = 0.0;
                let desired_pitch = 0.0;
                let desired_yaw_rate = 0.0;

                // Outer loop: Attitude error -> Desired rate
                let roll_error = desired_roll - roll;
                let pitch_error = desired_pitch - pitch;

                let dt = 1.0 / CONTROL_RATE_HZ as f32;
                let _roll_rate_cmd = ctx.local.roll_pid.update(roll_error, dt);
                let _pitch_rate_cmd = ctx.local.pitch_pid.update(pitch_error, dt);
                let _yaw_rate_cmd = ctx.local.yaw_pid.update(desired_yaw_rate - gyro.z, dt);

                // Inner loop: Rate error -> Motor command
                // TODO: Implement rate PIDs and motor mixer
            }

            // Wait 2ms (500Hz update rate)
            Systick::delay(2_u32.millis()).await;
        }
    }

    /// Motor output @ 400Hz
    ///
    /// This task generates PWM signals for motors/servos.
    #[task(priority = 1, shared = [armed])]
    async fn motor_task(mut ctx: motor_task::Context) {
        loop {
            let is_armed = ctx.shared.armed.lock(|a| *a);

            if is_armed {
                // TODO: Output PWM to motors based on mixer output
            } else {
                // Disarmed: Output minimum throttle
            }

            // Wait 2.5ms (400Hz update rate)
            Systick::delay(2500_u32.micros()).await;
        }
    }

    /// Heartbeat task @ 1Hz
    ///
    /// Provides visual feedback that the system is running.
    #[task(priority = 0, local = [led, state: bool = false])]
    async fn heartbeat_task(ctx: heartbeat_task::Context) {
        loop {
            // Toggle LED state
            *ctx.local.state = !*ctx.local.state;

            if let Some(led) = ctx.local.led {
                if *ctx.local.state {
                    led.set_high();
                } else {
                    led.set_low();
                }
            }

            // Wait 500ms
            Systick::delay(500_u32.millis()).await;
        }
    }

}
