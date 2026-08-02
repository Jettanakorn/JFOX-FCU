//! Mathematical utilities for flight control
//!
//! Provides no_std compatible math operations:
//! - 3D vectors for accelerometer/gyro data
//! - Quaternions for attitude representation
//! - PID controllers for stabilization
//! - Filters (low-pass, complementary, Kalman)

#![cfg_attr(not(feature = "std"), no_std)]

pub mod vector;
pub mod quaternion;
pub mod pid;
pub mod filters;
pub mod matrix;

pub use vector::Vec3;
pub use quaternion::Quat;
pub use pid::PidController;
pub use matrix::{MatN, Mat3, Mat6};
