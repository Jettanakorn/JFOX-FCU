//! 3D vector operations for IMU data

use libm::{sqrtf, atan2f, asinf};

#[derive(Clone, Copy, Debug, Default)]
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
