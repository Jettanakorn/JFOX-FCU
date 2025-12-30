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
