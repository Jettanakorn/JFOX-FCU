//! Quaternion representation for attitude
//!
//! Quaternions provide a singularity-free representation of 3D rotations.
//! Used for sensor fusion and attitude estimation.

use libm::{sqrtf, cosf, sinf, atan2f, asinf};
use crate::vector::Vec3;

#[derive(Clone, Copy, Debug)]
pub struct Quat {
    pub w: f32,
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Quat {
    pub const fn identity() -> Self {
        Self {
            w: 1.0,
            x: 0.0,
            y: 0.0,
            z: 0.0,
        }
    }

    pub const fn new(w: f32, x: f32, y: f32, z: f32) -> Self {
        Self { w, x, y, z }
    }

    /// Create quaternion from axis-angle representation
    pub fn from_axis_angle(axis: Vec3, angle: f32) -> Self {
        let half_angle = angle * 0.5;
        let s = sinf(half_angle);
        let axis_norm = axis.normalize();

        Self {
            w: cosf(half_angle),
            x: axis_norm.x * s,
            y: axis_norm.y * s,
            z: axis_norm.z * s,
        }
    }

    /// Create quaternion from Euler angles (roll, pitch, yaw in radians)
    pub fn from_euler(roll: f32, pitch: f32, yaw: f32) -> Self {
        let cr = cosf(roll * 0.5);
        let sr = sinf(roll * 0.5);
        let cp = cosf(pitch * 0.5);
        let sp = sinf(pitch * 0.5);
        let cy = cosf(yaw * 0.5);
        let sy = sinf(yaw * 0.5);

        Self {
            w: cr * cp * cy + sr * sp * sy,
            x: sr * cp * cy - cr * sp * sy,
            y: cr * sp * cy + sr * cp * sy,
            z: cr * cp * sy - sr * sp * cy,
        }
    }

    /// Quaternion multiplication (Hamilton product)
    pub fn mul(&self, q: &Quat) -> Quat {
        Quat {
            w: self.w * q.w - self.x * q.x - self.y * q.y - self.z * q.z,
            x: self.w * q.x + self.x * q.w + self.y * q.z - self.z * q.y,
            y: self.w * q.y - self.x * q.z + self.y * q.w + self.z * q.x,
            z: self.w * q.z + self.x * q.y - self.y * q.x + self.z * q.w,
        }
    }

    /// Calculate magnitude
    pub fn magnitude(&self) -> f32 {
        sqrtf(self.w * self.w + self.x * self.x + self.y * self.y + self.z * self.z)
    }

    /// Normalize quaternion to unit length
    pub fn normalize(&mut self) {
        let mag = self.magnitude();
        if mag > 1e-6 {
            self.w /= mag;
            self.x /= mag;
            self.y /= mag;
            self.z /= mag;
        }
    }

    /// Get normalized copy
    pub fn normalized(&self) -> Self {
        let mut q = *self;
        q.normalize();
        q
    }

    /// Conjugate (inverse for unit quaternions)
    pub fn conjugate(&self) -> Quat {
        Quat {
            w: self.w,
            x: -self.x,
            y: -self.y,
            z: -self.z,
        }
    }

    /// Rotate a vector by this quaternion
    pub fn rotate(&self, v: Vec3) -> Vec3 {
        let q_v = Quat::new(0.0, v.x, v.y, v.z);
        let result = self.mul(&q_v).mul(&self.conjugate());
        Vec3::new(result.x, result.y, result.z)
    }

    /// Convert to Euler angles (roll, pitch, yaw in radians)
    /// Returns (roll, pitch, yaw) in radians
    pub fn to_euler(&self) -> (f32, f32, f32) {
        // Roll (x-axis rotation)
        let sinr_cosp = 2.0 * (self.w * self.x + self.y * self.z);
        let cosr_cosp = 1.0 - 2.0 * (self.x * self.x + self.y * self.y);
        let roll = atan2f(sinr_cosp, cosr_cosp);

        // Pitch (y-axis rotation)
        let sinp = 2.0 * (self.w * self.y - self.z * self.x);
        let pitch = if sinp.abs() >= 1.0 {
            core::f32::consts::FRAC_PI_2.copysign(sinp) // Use 90 degrees if out of range
        } else {
            asinf(sinp)
        };

        // Yaw (z-axis rotation)
        let siny_cosp = 2.0 * (self.w * self.z + self.x * self.y);
        let cosy_cosp = 1.0 - 2.0 * (self.y * self.y + self.z * self.z);
        let yaw = atan2f(siny_cosp, cosy_cosp);

        (roll, pitch, yaw)
    }

    /// Spherical linear interpolation
    pub fn slerp(&self, other: &Quat, t: f32) -> Quat {
        let dot = self.w * other.w + self.x * other.x + self.y * other.y + self.z * other.z;

        // If quaternions are close, use linear interpolation
        if dot.abs() > 0.9995 {
            return Quat {
                w: self.w + t * (other.w - self.w),
                x: self.x + t * (other.x - self.x),
                y: self.y + t * (other.y - self.y),
                z: self.z + t * (other.z - self.z),
            }
            .normalized();
        }

        // Use slerp for accurate interpolation
        let theta = libm::acosf(dot.abs());
        let sin_theta = libm::sinf(theta);

        let w0 = libm::sinf((1.0 - t) * theta) / sin_theta;
        let w1 = libm::sinf(t * theta) / sin_theta;

        Quat {
            w: w0 * self.w + w1 * other.w,
            x: w0 * self.x + w1 * other.x,
            y: w0 * self.y + w1 * other.y,
            z: w0 * self.z + w1 * other.z,
        }
    }
}

impl Default for Quat {
    fn default() -> Self {
        Self::identity()
    }
}

impl core::ops::Mul for Quat {
    type Output = Self;
    fn mul(self, other: Self) -> Self {
        Quat {
            w: self.w * other.w - self.x * other.x - self.y * other.y - self.z * other.z,
            x: self.w * other.x + self.x * other.w + self.y * other.z - self.z * other.y,
            y: self.w * other.y - self.x * other.z + self.y * other.w + self.z * other.x,
            z: self.w * other.z + self.x * other.y - self.y * other.x + self.z * other.w,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const EPS: f32 = 1e-4;

    fn approx_eq(a: f32, b: f32) -> bool {
        (a - b).abs() < EPS
    }

    #[test]
    fn identity_has_zero_euler_angles() {
        let (roll, pitch, yaw) = Quat::identity().to_euler();
        assert!(approx_eq(roll, 0.0));
        assert!(approx_eq(pitch, 0.0));
        assert!(approx_eq(yaw, 0.0));
    }

    #[test]
    fn from_euler_roundtrips_through_to_euler_away_from_gimbal_lock() {
        // Values chosen well clear of the +-pi/2 pitch singularity.
        let cases = [
            (0.3, 0.2, 0.1),
            (-0.5, 0.4, -0.6),
            (1.0, -0.3, 2.0),
            (0.0, 0.0, 0.0),
        ];
        for (roll, pitch, yaw) in cases {
            let q = Quat::from_euler(roll, pitch, yaw);
            let (r2, p2, y2) = q.to_euler();
            assert!(approx_eq(r2, roll), "roll: expected {roll} got {r2}");
            assert!(approx_eq(p2, pitch), "pitch: expected {pitch} got {p2}");
            assert!(approx_eq(y2, yaw), "yaw: expected {yaw} got {y2}");
        }
    }

    #[test]
    fn to_euler_gimbal_lock_branch_positive() {
        // Hand-built (not from_euler-derived) so sinp = 2*(w*y - z*x) is
        // pushed unambiguously >= 1.0 regardless of float rounding
        // direction, deterministically exercising the clamp branch rather
        // than hoping a "natural" construction lands exactly on it.
        let q = Quat::new(1.0, 0.0, 1.0, 0.0);
        let (_, pitch, _) = q.to_euler();
        assert!(approx_eq(pitch, core::f32::consts::FRAC_PI_2));
        assert!(pitch.is_finite());
    }

    #[test]
    fn to_euler_gimbal_lock_branch_negative() {
        let q = Quat::new(1.0, 0.0, -1.0, 0.0);
        let (_, pitch, _) = q.to_euler();
        assert!(approx_eq(pitch, -core::f32::consts::FRAC_PI_2));
        assert!(pitch.is_finite());
    }

    #[test]
    fn to_euler_near_gimbal_lock_from_natural_construction_does_not_nan() {
        // A physically-constructed near-vertical pitch: exercises whichever
        // branch float rounding actually takes, and simply must not NaN or
        // diverge wildly from +pi/2.
        let q = Quat::from_euler(0.0, core::f32::consts::FRAC_PI_2, 0.0);
        let (_, pitch, _) = q.to_euler();
        assert!(pitch.is_finite());
        assert!((pitch - core::f32::consts::FRAC_PI_2).abs() < 0.01);
    }

    #[test]
    fn from_axis_angle_matches_from_euler_for_a_pure_yaw_rotation() {
        let angle = core::f32::consts::FRAC_PI_2;
        let by_axis = Quat::from_axis_angle(Vec3::new(0.0, 0.0, 1.0), angle);
        let by_euler = Quat::from_euler(0.0, 0.0, angle);
        assert!(approx_eq(by_axis.w, by_euler.w));
        assert!(approx_eq(by_axis.x, by_euler.x));
        assert!(approx_eq(by_axis.y, by_euler.y));
        assert!(approx_eq(by_axis.z, by_euler.z));
    }

    #[test]
    fn from_axis_angle_normalizes_a_non_unit_axis() {
        // axis (0,0,5) should behave identically to (0,0,1): from_axis_angle
        // normalizes the axis internally.
        let a = Quat::from_axis_angle(Vec3::new(0.0, 0.0, 5.0), 1.0);
        let b = Quat::from_axis_angle(Vec3::new(0.0, 0.0, 1.0), 1.0);
        assert!(approx_eq(a.x, b.x) && approx_eq(a.y, b.y) && approx_eq(a.z, b.z) && approx_eq(a.w, b.w));
    }

    #[test]
    fn mul_method_and_operator_overload_agree() {
        let a = Quat::from_euler(0.3, 0.1, -0.2);
        let b = Quat::from_euler(-0.1, 0.4, 0.5);
        let via_method = a.mul(&b);
        let via_operator = a * b;
        assert!(approx_eq(via_method.w, via_operator.w));
        assert!(approx_eq(via_method.x, via_operator.x));
        assert!(approx_eq(via_method.y, via_operator.y));
        assert!(approx_eq(via_method.z, via_operator.z));
    }

    #[test]
    fn normalize_produces_unit_magnitude() {
        let mut q = Quat::new(2.0, 1.0, 0.5, 0.5);
        q.normalize();
        assert!(approx_eq(q.magnitude(), 1.0));
    }

    #[test]
    fn normalize_of_near_zero_quaternion_is_a_safe_noop() {
        // mag <= 1e-6 guard: must not divide by ~zero and produce NaN/inf.
        let mut q = Quat::new(0.0, 0.0, 0.0, 0.0);
        q.normalize();
        assert!(q.w.is_finite() && q.x.is_finite() && q.y.is_finite() && q.z.is_finite());
    }

    #[test]
    fn conjugate_negates_the_vector_part_only() {
        let q = Quat::new(0.5, 0.1, 0.2, 0.3);
        let c = q.conjugate();
        assert_eq!(c.w, q.w);
        assert_eq!(c.x, -q.x);
        assert_eq!(c.y, -q.y);
        assert_eq!(c.z, -q.z);
    }

    #[test]
    fn rotate_by_identity_is_a_noop() {
        let v = Vec3::new(1.0, 2.0, 3.0);
        let rotated = Quat::identity().rotate(v);
        assert!(approx_eq(rotated.x, v.x));
        assert!(approx_eq(rotated.y, v.y));
        assert!(approx_eq(rotated.z, v.z));
    }

    #[test]
    fn rotate_90_degrees_about_z_maps_x_axis_to_y_axis() {
        let q = Quat::from_axis_angle(Vec3::new(0.0, 0.0, 1.0), core::f32::consts::FRAC_PI_2);
        let rotated = q.rotate(Vec3::new(1.0, 0.0, 0.0));
        assert!(approx_eq(rotated.x, 0.0), "x: {}", rotated.x);
        assert!(approx_eq(rotated.y, 1.0), "y: {}", rotated.y);
        assert!(approx_eq(rotated.z, 0.0), "z: {}", rotated.z);
    }

    #[test]
    fn slerp_at_t_zero_returns_self() {
        let a = Quat::from_euler(0.1, 0.2, 0.3);
        let b = Quat::from_euler(1.0, -0.5, 0.8);
        let result = a.slerp(&b, 0.0);
        assert!(approx_eq(result.w, a.w) && approx_eq(result.x, a.x) && approx_eq(result.y, a.y) && approx_eq(result.z, a.z));
    }

    #[test]
    fn slerp_at_t_one_returns_other() {
        let a = Quat::from_euler(0.1, 0.2, 0.3);
        let b = Quat::from_euler(1.0, -0.5, 0.8);
        let result = a.slerp(&b, 1.0);
        assert!(approx_eq(result.w, b.w) && approx_eq(result.x, b.x) && approx_eq(result.y, b.y) && approx_eq(result.z, b.z));
    }

    #[test]
    fn slerp_close_quaternions_takes_the_linear_interpolation_branch() {
        // Two nearly-identical quaternions: dot product > 0.9995, exercising
        // the linear-interpolation shortcut branch specifically.
        let a = Quat::identity();
        let b = Quat::from_euler(0.001, 0.0, 0.0);
        let result = a.slerp(&b, 0.5);
        assert!(approx_eq(result.magnitude(), 1.0));
    }

    #[test]
    fn slerp_far_quaternions_takes_the_spherical_interpolation_branch() {
        // ~90 degrees apart: dot product well below 0.9995, exercising the
        // full spherical (non-shortcut) interpolation branch.
        let a = Quat::identity();
        let b = Quat::from_axis_angle(Vec3::new(0.0, 0.0, 1.0), core::f32::consts::FRAC_PI_2);
        let result = a.slerp(&b, 0.5);
        assert!(approx_eq(result.magnitude(), 1.0));
        // Halfway through a 90 degree rotation should be close to a 45 degree one.
        let expected = Quat::from_axis_angle(Vec3::new(0.0, 0.0, 1.0), core::f32::consts::FRAC_PI_4);
        assert!(approx_eq(result.w, expected.w), "w: got {} expected {}", result.w, expected.w);
        assert!(approx_eq(result.z, expected.z), "z: got {} expected {}", result.z, expected.z);
    }

    #[test]
    fn default_is_identity() {
        let q = Quat::default();
        assert_eq!(q.w, 1.0);
        assert_eq!(q.x, 0.0);
        assert_eq!(q.y, 0.0);
        assert_eq!(q.z, 0.0);
    }
}
