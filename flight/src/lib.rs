//! Flight control algorithms
//!
//! Provides core flight control functionality:
//! - Sensor fusion (Madgwick/Mahony AHRS)
//! - Attitude control (stabilize mode)
//! - Rate control (acro mode)
//! - Motor mixing
//! - Safety and arming logic

#![cfg_attr(not(feature = "std"), no_std)]

pub mod sensor_fusion;
pub mod stabilize;
pub mod mixer;
pub mod arming;
pub mod mpc;
pub mod adaptive;
pub mod redundancy;
pub mod calibration;
pub mod bit;

pub use sensor_fusion::MadgwickFilter;
