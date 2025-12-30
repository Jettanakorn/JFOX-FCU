//! Madgwick AHRS sensor fusion algorithm
//!
//! Fuses gyroscope and accelerometer data to estimate attitude.
//! Uses gradient descent to minimize error between measured and predicted gravity.
//!
//! Reference: S.O.H. Madgwick, "An efficient orientation filter for inertial and
//! inertial/magnetic sensor arrays", 2010

use math::{Vec3, Quat};
use libm::sqrtf;
use defmt::trace;

/// Madgwick AHRS filter
pub struct MadgwickFilter {
    /// Current attitude quaternion
    pub q: Quat,

    /// Filter gain (beta)
    /// Typical values: 0.01-0.1
    /// Higher values = faster convergence but more noise
    /// Lower values = slower convergence but smoother
    beta: f32,
}

impl MadgwickFilter {
    /// Create new Madgwick filter
    ///
    /// # Arguments
    ///
    /// * `beta` - Filter gain (0.01-0.1, typically 0.041 for 100Hz update)
    pub fn new(beta: f32) -> Self {
        Self {
            q: Quat::identity(),
            beta,
        }
    }

    /// Update filter with gyroscope and accelerometer
    ///
    /// # Arguments
    ///
    /// * `gyro` - Gyroscope reading (rad/s)
    /// * `accel` - Accelerometer reading (m/s² or any units)
    /// * `dt` - Time step (seconds)
    pub fn update(&mut self, gyro: Vec3, accel: Vec3, dt: f32) {
        // Normalize accelerometer measurement
        let accel_mag = accel.magnitude();
        if accel_mag < 1e-6 {
            // No valid accelerometer data, use gyro only
            self.update_gyro_only(gyro, dt);
            return;
        }

        let ax = accel.x / accel_mag;
        let ay = accel.y / accel_mag;
        let az = accel.z / accel_mag;

        // Short name local variable for readability
        let q0 = self.q.w;
        let q1 = self.q.x;
        let q2 = self.q.y;
        let q3 = self.q.z;

        // Gradient descent algorithm corrective step
        // Objective function: f = 2(q1*q3 - q0*q2) - ax
        //                         2(q0*q1 + q2*q3) - ay
        //                         2(0.5 - q1² - q2²) - az

        let f1 = 2.0 * (q1 * q3 - q0 * q2) - ax;
        let f2 = 2.0 * (q0 * q1 + q2 * q3) - ay;
        let f3 = 2.0 * (0.5 - q1 * q1 - q2 * q2) - az;

        // Jacobian matrix J^T * f
        let j11_24 = 2.0 * q2;
        let j12_23 = 2.0 * q3;
        let j13_22 = 2.0 * q0;
        let j14_21 = 2.0 * q1;
        let j32 = 2.0 * j14_21;
        let j33 = 2.0 * j11_24;

        let s0 = -j13_22 * f2 + j12_23 * f3;
        let s1 = j14_21 * f1 + j11_24 * f2 - j32 * f3;
        let s2 = -j14_21 * f2 + j13_22 * f1 - j33 * f3;
        let s3 = j12_23 * f1 + j11_24 * f2;

        // Normalize step magnitude
        let norm = sqrtf(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3);
        let s0_norm = if norm > 0.0 { s0 / norm } else { 0.0 };
        let s1_norm = if norm > 0.0 { s1 / norm } else { 0.0 };
        let s2_norm = if norm > 0.0 { s2 / norm } else { 0.0 };
        let s3_norm = if norm > 0.0 { s3 / norm } else { 0.0 };

        // Compute rate of change of quaternion (from gyroscope)
        let gx = gyro.x;
        let gy = gyro.y;
        let gz = gyro.z;

        let q_dot0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz);
        let q_dot1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy);
        let q_dot2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx);
        let q_dot3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx);

        // Apply feedback step
        let q0_new = q0 + (q_dot0 - self.beta * s0_norm) * dt;
        let q1_new = q1 + (q_dot1 - self.beta * s1_norm) * dt;
        let q2_new = q2 + (q_dot2 - self.beta * s2_norm) * dt;
        let q3_new = q3 + (q_dot3 - self.beta * s3_norm) * dt;

        // Update quaternion
        self.q.w = q0_new;
        self.q.x = q1_new;
        self.q.y = q2_new;
        self.q.z = q3_new;

        // Normalize quaternion
        self.q.normalize();

        trace!("Madgwick: q=({}, {}, {}, {})",
               self.q.w, self.q.x, self.q.y, self.q.z);
    }

    /// Update with gyroscope only (no accelerometer correction)
    fn update_gyro_only(&mut self, gyro: Vec3, dt: f32) {
        let q0 = self.q.w;
        let q1 = self.q.x;
        let q2 = self.q.y;
        let q3 = self.q.z;

        let gx = gyro.x;
        let gy = gyro.y;
        let gz = gyro.z;

        // Quaternion derivative from gyroscope
        let q_dot0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz);
        let q_dot1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy);
        let q_dot2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx);
        let q_dot3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx);

        // Integrate
        self.q.w += q_dot0 * dt;
        self.q.x += q_dot1 * dt;
        self.q.y += q_dot2 * dt;
        self.q.z += q_dot3 * dt;

        // Normalize
        self.q.normalize();
    }

    /// Get current attitude as Euler angles (roll, pitch, yaw in radians)
    pub fn get_euler(&self) -> (f32, f32, f32) {
        self.q.to_euler()
    }

    /// Get current attitude quaternion
    pub fn get_quaternion(&self) -> Quat {
        self.q
    }

    /// Reset filter to identity orientation
    pub fn reset(&mut self) {
        self.q = Quat::identity();
    }

    /// Set filter gain
    pub fn set_beta(&mut self, beta: f32) {
        self.beta = beta;
    }
}

impl Default for MadgwickFilter {
    fn default() -> Self {
        Self::new(0.041) // Default beta for ~100Hz update rate
    }
}
