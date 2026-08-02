//! Sensor and peripheral drivers
//!
//! Provides drivers for all sensors and peripherals on the JFOX FCU:
//! - MPU-6000: Primary 6-axis IMU (gyro + accel)
//! - MS5611: Barometric pressure sensor
//! - L3GD20: Backup gyroscope
//! - LSM303D: Backup accelerometer/magnetometer
//! - FM25V01: FRAM non-volatile storage

#![no_std]

pub mod mpu6000;
pub mod ms5611;
pub mod fm25v01;

pub use mpu6000::Mpu6000;
pub use fm25v01::Fm25v01;
