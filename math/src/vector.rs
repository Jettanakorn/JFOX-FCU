//! 3D vector operations for IMU data

use libm::{sqrtf, atan2f};

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub const fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    pub const fn zero() -> Self {
        Self::new(0.0, 0.0, 0.0)
    }

    /// Calculate magnitude (length) of vector
    pub fn magnitude(&self) -> f32 {
        sqrtf(self.x * self.x + self.y * self.y + self.z * self.z)
    }

    /// Normalize vector to unit length
    pub fn normalize(&self) -> Self {
        let mag = self.magnitude();
        if mag > 1e-6 {
            Self {
                x: self.x / mag,
                y: self.y / mag,
                z: self.z / mag,
            }
        } else {
            *self
        }
    }

    /// Dot product
    pub fn dot(&self, other: &Self) -> f32 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }

    /// Cross product
    pub fn cross(&self, other: &Self) -> Self {
        Self {
            x: self.y * other.z - self.z * other.y,
            y: self.z * other.x - self.x * other.z,
            z: self.x * other.y - self.y * other.x,
        }
    }

    /// Add two vectors
    pub fn add(&self, other: &Self) -> Self {
        Self {
            x: self.x + other.x,
            y: self.y + other.y,
            z: self.z + other.z,
        }
    }

    /// Subtract two vectors
    pub fn sub(&self, other: &Self) -> Self {
        Self {
            x: self.x - other.x,
            y: self.y - other.y,
            z: self.z - other.z,
        }
    }

    /// Multiply by scalar
    pub fn scale(&self, scalar: f32) -> Self {
        Self {
            x: self.x * scalar,
            y: self.y * scalar,
            z: self.z * scalar,
        }
    }

    /// Convert to Euler angles (roll, pitch) from accelerometer
    /// Assumes z-axis is up (NED frame)
    pub fn to_euler_accel(&self) -> (f32, f32) {
        let roll = atan2f(self.y, self.z);
        let pitch = atan2f(-self.x, sqrtf(self.y * self.y + self.z * self.z));
        (roll, pitch)
    }
}

impl core::ops::Add for Vec3 {
    type Output = Self;
    fn add(self, other: Self) -> Self {
        Vec3::add(&self, &other)
    }
}

impl core::ops::Sub for Vec3 {
    type Output = Self;
    fn sub(self, other: Self) -> Self {
        Vec3::sub(&self, &other)
    }
}

impl core::ops::Mul<f32> for Vec3 {
    type Output = Self;
    fn mul(self, scalar: f32) -> Self {
        self.scale(scalar)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const EPS: f32 = 1e-5;

    fn approx_eq(a: f32, b: f32) -> bool {
        (a - b).abs() < EPS
    }

    #[test]
    fn magnitude_of_a_3_4_0_triangle_is_5() {
        assert!(approx_eq(Vec3::new(3.0, 4.0, 0.0).magnitude(), 5.0));
    }

    #[test]
    fn normalize_produces_unit_length() {
        let v = Vec3::new(3.0, 4.0, 0.0).normalize();
        assert!(approx_eq(v.magnitude(), 1.0));
        assert!(approx_eq(v.x, 0.6));
        assert!(approx_eq(v.y, 0.8));
    }

    #[test]
    fn normalize_of_near_zero_vector_is_a_safe_noop() {
        let v = Vec3::new(0.0, 0.0, 0.0).normalize();
        assert_eq!(v, Vec3::zero());
    }

    #[test]
    fn dot_product_of_orthogonal_vectors_is_zero() {
        let a = Vec3::new(1.0, 0.0, 0.0);
        let b = Vec3::new(0.0, 1.0, 0.0);
        assert!(approx_eq(a.dot(&b), 0.0));
    }

    #[test]
    fn cross_product_of_x_and_y_axes_is_z_axis() {
        let x = Vec3::new(1.0, 0.0, 0.0);
        let y = Vec3::new(0.0, 1.0, 0.0);
        let z = x.cross(&y);
        assert!(approx_eq(z.x, 0.0) && approx_eq(z.y, 0.0) && approx_eq(z.z, 1.0));
    }

    #[test]
    fn add_sub_scale_match_componentwise_arithmetic() {
        let a = Vec3::new(1.0, 2.0, 3.0);
        let b = Vec3::new(0.5, -1.0, 2.0);
        let sum = a.add(&b);
        assert!(approx_eq(sum.x, 1.5) && approx_eq(sum.y, 1.0) && approx_eq(sum.z, 5.0));
        let diff = a.sub(&b);
        assert!(approx_eq(diff.x, 0.5) && approx_eq(diff.y, 3.0) && approx_eq(diff.z, 1.0));
        let scaled = a.scale(2.0);
        assert!(approx_eq(scaled.x, 2.0) && approx_eq(scaled.y, 4.0) && approx_eq(scaled.z, 6.0));
    }

    #[test]
    fn operator_overloads_match_named_methods() {
        let a = Vec3::new(1.0, 2.0, 3.0);
        let b = Vec3::new(0.5, -1.0, 2.0);
        assert_eq!(a + b, a.add(&b));
        assert_eq!(a - b, a.sub(&b));
        assert_eq!(a * 2.0, a.scale(2.0));
    }

    #[test]
    fn to_euler_accel_is_level_when_accel_is_pure_z() {
        // Stationary, level: specific force reads as (0,0,g) in body frame
        // (see flight::sensor_fusion / drivers::Mpu6000's shared convention).
        let (roll, pitch) = Vec3::new(0.0, 0.0, 9.80665).to_euler_accel();
        assert!(approx_eq(roll, 0.0), "roll: {roll}");
        assert!(approx_eq(pitch, 0.0), "pitch: {pitch}");
    }

    #[test]
    fn to_euler_accel_recovers_a_known_roll_angle() {
        let g = 9.80665;
        let angle = 0.3f32; // radians
        // Tilted purely about the roll axis: accel rotates in the Y-Z plane.
        let accel = Vec3::new(0.0, g * libm::sinf(angle), g * libm::cosf(angle));
        let (roll, pitch) = accel.to_euler_accel();
        assert!(approx_eq(roll, angle), "roll: expected {angle} got {roll}");
        assert!(approx_eq(pitch, 0.0), "pitch: {pitch}");
    }

    #[test]
    fn to_euler_accel_recovers_a_known_pitch_angle() {
        let g = 9.80665;
        let angle = -0.4f32;
        // Tilted purely about the pitch axis: accel rotates in the X-Z plane.
        // to_euler_accel's pitch = atan2(-x, sqrt(y^2+z^2)), so x = -g*sin(angle).
        let accel = Vec3::new(-g * libm::sinf(angle), 0.0, g * libm::cosf(angle));
        let (roll, pitch) = accel.to_euler_accel();
        assert!(approx_eq(roll, 0.0), "roll: {roll}");
        assert!(approx_eq(pitch, angle), "pitch: expected {angle} got {pitch}");
    }
}
