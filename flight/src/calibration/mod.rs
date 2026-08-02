//! Sensor calibration: gyro bias (auto-measured fresh every boot) and
//! accelerometer bias/scale (persisted to FRAM once available, identity
//! default otherwise). See `gyro_bias`, `accel_cal`, and `storage` module
//! docs for why these are handled so differently.

pub mod gyro_bias;
pub mod accel_cal;
pub mod storage;

pub use gyro_bias::{GyroBiasEstimator, CalState};
pub use accel_cal::AccelCalibration;
pub use storage::CalibrationRecord;
