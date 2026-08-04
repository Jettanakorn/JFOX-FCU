//! Sensor and peripheral drivers
//!
//! What is actually implemented, as opposed to what the board can carry:
//!
//! | Part | State |
//! |---|---|
//! | MPU-6000 primary IMU | driver, verified on hardware |
//! | MS5611 barometer | driver, compensation unit-tested against the datasheet's worked example; not yet run on hardware |
//! | FM25V01 FRAM | driver |
//! | L3GD20 backup gyro | **detected only** - see [`probe`] |
//! | LSM303D accel/mag | **detected only** - see [`probe`] |
//!
//! Sensor population on the PX4 FMUv2 family is a per-unit build option, so
//! [`probe`] identifies what is really on the bus before anything tries to read
//! it. Positions that are populated with a part this crate cannot drive are
//! reported rather than ignored - knowing an LSM303D is present and unused is
//! more useful than silently pretending the position is empty.

#![no_std]

pub mod fm25v01;
pub mod mpu6000;
pub mod ms5611;
pub mod probe;

pub use fm25v01::Fm25v01;
pub use mpu6000::Mpu6000;
pub use ms5611::Ms5611;
pub use probe::{BusScan, Device};
