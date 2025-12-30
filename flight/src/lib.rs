//! Flight control algorithms
//!
//! Provides core flight control functionality:
//! - Sensor fusion (Madgwick/Mahony AHRS)
//! - Attitude control (stabilize mode)
//! - Rate control (acro mode)
//! - Motor mixing
//! - Safety and arming logic

#![no_std]

pub mod sensor_fusion;
pub mod stabilize;
pub mod mixer;

pub use sensor_fusion::MadgwickFilter;
