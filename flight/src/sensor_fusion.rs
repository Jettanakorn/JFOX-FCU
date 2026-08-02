//! Madgwick AHRS sensor fusion algorithm
//!
//! Fuses gyroscope and accelerometer data to estimate attitude.
//! Uses gradient descent to minimize error between measured and predicted gravity.
//!
//! Reference: S.O.H. Madgwick, "An efficient orientation filter for inertial and
//! inertial/magnetic sensor arrays", 2010

use math::{Vec3, Quat};
use libm::sqrtf;
#[cfg(not(feature = "std"))]
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

        // Gradient = J^T * f, where J is the 3x4 Jacobian of f w.r.t. (q0,q1,q2,q3):
        //   J = [ -2q2,  2q3, -2q0,  2q1 ]
        //       [  2q1,  2q0,  2q3,  2q2 ]
        //       [   0,  -4q1, -4q2,   0  ]
        let s0 = -2.0 * q2 * f1 + 2.0 * q1 * f2;
        let s1 = 2.0 * q3 * f1 + 2.0 * q0 * f2 - 4.0 * q1 * f3;
        let s2 = -2.0 * q0 * f1 + 2.0 * q3 * f2 - 4.0 * q2 * f3;
        let s3 = 2.0 * q1 * f1 + 2.0 * q2 * f2;

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

        #[cfg(not(feature = "std"))]
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

#[cfg(test)]
mod tests {
    use super::*;
    const EPS: f32 = 1e-4;
    const G: f32 = 9.80665;

    fn approx_eq(a: f32, b: f32, tol: f32) -> bool {
        (a - b).abs() < tol
    }

    #[test]
    fn stationary_and_level_stays_at_identity() {
        let mut filter = MadgwickFilter::new(0.1);
        for _ in 0..500 {
            filter.update(Vec3::zero(), Vec3::new(0.0, 0.0, G), 0.01);
        }
        let (roll, pitch, yaw) = filter.get_euler();
        assert!(approx_eq(roll, 0.0, EPS), "roll: {roll}");
        assert!(approx_eq(pitch, 0.0, EPS), "pitch: {pitch}");
        assert!(approx_eq(yaw, 0.0, EPS), "yaw: {yaw}");
    }

    #[test]
    fn get_euler_matches_get_quaternion_to_euler() {
        let mut filter = MadgwickFilter::new(0.05);
        filter.update(Vec3::new(0.1, 0.0, 0.0), Vec3::new(0.0, -1.0, G), 0.01);
        assert_eq!(filter.get_euler(), filter.get_quaternion().to_euler());
    }

    #[test]
    fn accel_only_tilt_converges_toward_the_indicated_attitude() {
        // Zero gyro (sensor isn't rotating), but the accelerometer indicates
        // the vehicle is already resting at a ~0.3 rad roll tilt. The
        // gradient-descent correction should pull the estimate toward that
        // tilt over time using accel alone - the whole point of fusing accel
        // in the first place. A larger-than-production beta (still within
        // the documented 0.01-0.1 "typical" range's order of magnitude) and
        // a generous tolerance keep this a convergence-property test, not a
        // brittle exact-tuning test.
        let true_roll = 0.3f32;
        let tilted_accel = Vec3::new(0.0, G * libm::sinf(true_roll), G * libm::cosf(true_roll));

        let mut filter = MadgwickFilter::new(0.1);
        for _ in 0..2000 {
            filter.update(Vec3::zero(), tilted_accel, 0.01);
        }

        let (roll, pitch, _) = filter.get_euler();
        assert!(approx_eq(roll, true_roll, 0.05), "roll: expected ~{true_roll} got {roll}");
        assert!(approx_eq(pitch, 0.0, 0.05), "pitch: {pitch}");
    }

    #[test]
    fn pure_yaw_rotation_integrates_gyro_over_a_short_window() {
        // Pure rotation about the vertical (yaw) axis with the vehicle level:
        // gravity's reading in the body frame is unchanged throughout (the
        // rotation axis coincides with the measurement axis), so accel gives
        // no yaw correction at all - yaw evolves purely from gyro
        // integration. Over a short window this should closely match
        // omega * time, before any numerical drift accumulates meaningfully.
        let omega = 0.5f32; // rad/s
        let dt = 0.001f32;
        let steps = 200; // 0.2s
        let mut filter = MadgwickFilter::new(0.01);
        for _ in 0..steps {
            filter.update(Vec3::new(0.0, 0.0, omega), Vec3::new(0.0, 0.0, G), dt);
        }
        let (roll, pitch, yaw) = filter.get_euler();
        let expected_yaw = omega * (steps as f32) * dt;
        assert!(approx_eq(yaw, expected_yaw, 0.01), "yaw: expected ~{expected_yaw} got {yaw}");
        assert!(approx_eq(roll, 0.0, 0.01), "roll: {roll}");
        assert!(approx_eq(pitch, 0.0, 0.01), "pitch: {pitch}");
    }

    #[test]
    fn zero_accel_magnitude_takes_the_gyro_only_fallback_without_diverging() {
        // accel magnitude < 1e-6 must route to update_gyro_only rather than
        // dividing by ~zero in the accel-normalization step.
        let mut filter = MadgwickFilter::new(0.1);
        for _ in 0..100 {
            filter.update(Vec3::new(0.2, -0.1, 0.05), Vec3::zero(), 0.01);
        }
        let (roll, pitch, yaw) = filter.get_euler();
        assert!(roll.is_finite() && pitch.is_finite() && yaw.is_finite());
        // Quaternion must remain normalized even through the fallback path.
        assert!(approx_eq(filter.get_quaternion().magnitude(), 1.0, 1e-3));
    }

    #[test]
    fn zero_beta_disables_the_accel_correction_entirely() {
        // With beta=0 the feedback term is exactly zero, so with zero gyro
        // input the estimate must not move at all even though the
        // accelerometer clearly disagrees with the current (identity)
        // estimate - proves the correction step is genuinely gated by beta,
        // not applied unconditionally.
        let mut filter = MadgwickFilter::new(0.0);
        let disagreeing_accel = Vec3::new(0.0, G, 0.0); // wildly tilted reading
        for _ in 0..50 {
            filter.update(Vec3::zero(), disagreeing_accel, 0.01);
        }
        let (roll, pitch, yaw) = filter.get_euler();
        assert!(approx_eq(roll, 0.0, EPS), "roll: {roll}");
        assert!(approx_eq(pitch, 0.0, EPS), "pitch: {pitch}");
        assert!(approx_eq(yaw, 0.0, EPS), "yaw: {yaw}");
    }

    #[test]
    fn set_beta_changes_subsequent_convergence_behavior() {
        let true_roll = 0.3f32;
        let tilted_accel = Vec3::new(0.0, G * libm::sinf(true_roll), G * libm::cosf(true_roll));

        let mut slow = MadgwickFilter::new(0.0);
        slow.set_beta(0.1);
        for _ in 0..2000 {
            slow.update(Vec3::zero(), tilted_accel, 0.01);
        }
        let (roll, _, _) = slow.get_euler();
        // Same scenario/iteration count as accel_only_tilt_converges...:
        // after set_beta raises it from 0, convergence should behave the
        // same as directly constructing with that beta.
        assert!(approx_eq(roll, true_roll, 0.05), "roll: expected ~{true_roll} got {roll}");
    }

    #[test]
    fn reset_returns_to_identity() {
        let mut filter = MadgwickFilter::new(0.1);
        filter.update(Vec3::new(0.5, 0.3, 0.1), Vec3::new(0.0, 1.0, 1.0), 0.01);
        let (roll, _, _) = filter.get_euler();
        assert!(roll.abs() > EPS, "test setup should have moved the estimate away from identity");

        filter.reset();
        let (roll, pitch, yaw) = filter.get_euler();
        assert_eq!(roll, 0.0);
        assert_eq!(pitch, 0.0);
        assert_eq!(yaw, 0.0);
    }

    #[test]
    fn quaternion_stays_normalized_over_an_extended_varying_run() {
        let mut filter = MadgwickFilter::new(0.05);
        for i in 0..5000 {
            let t = i as f32 * 0.01;
            let gyro = Vec3::new(0.3 * libm::sinf(t), 0.2 * libm::cosf(t * 0.7), 0.1);
            let accel = Vec3::new(0.5 * libm::sinf(t * 0.3), 0.3, G);
            filter.update(gyro, accel, 0.01);
        }
        assert!(approx_eq(filter.get_quaternion().magnitude(), 1.0, 1e-3));
    }

    #[test]
    fn default_uses_beta_0_041() {
        // Indirect check (beta is private): a filter constructed via
        // Default and one constructed with new(0.041) must behave
        // identically given the same inputs.
        let mut via_default = MadgwickFilter::default();
        let mut via_new = MadgwickFilter::new(0.041);
        let gyro = Vec3::new(0.1, 0.0, 0.0);
        let accel = Vec3::new(0.0, 0.2, G);
        for _ in 0..50 {
            via_default.update(gyro, accel, 0.01);
            via_new.update(gyro, accel, 0.01);
        }
        assert_eq!(via_default.get_euler(), via_new.get_euler());
    }
}
