//! Digital filters for sensor data

/// Low-pass filter (exponential moving average)
#[derive(Clone, Copy, Debug)]
pub struct LowPassFilter {
    alpha: f32,
    value: f32,
    initialized: bool,
}

impl LowPassFilter {
    /// Create new low-pass filter
    ///
    /// # Arguments
    ///
    /// * `cutoff_freq` - Cutoff frequency in Hz
    /// * `sample_rate` - Sample rate in Hz
    pub fn new(cutoff_freq: f32, sample_rate: f32) -> Self {
        let rc = 1.0 / (2.0 * core::f32::consts::PI * cutoff_freq);
        let dt = 1.0 / sample_rate;
        let alpha = dt / (rc + dt);

        Self {
            alpha,
            value: 0.0,
            initialized: false,
        }
    }

    /// Update filter with new sample
    pub fn update(&mut self, sample: f32) -> f32 {
        if !self.initialized {
            self.value = sample;
            self.initialized = true;
        } else {
            self.value = self.alpha * sample + (1.0 - self.alpha) * self.value;
        }
        self.value
    }

    /// Reset filter
    pub fn reset(&mut self) {
        self.value = 0.0;
        self.initialized = false;
    }
}

/// Complementary filter for sensor fusion
#[derive(Clone, Copy, Debug)]
pub struct ComplementaryFilter {
    alpha: f32,
    angle: f32,
}

impl ComplementaryFilter {
    /// Create new complementary filter
    ///
    /// # Arguments
    ///
    /// * `alpha` - Weight for gyroscope (0.0-1.0, typically 0.98)
    pub fn new(alpha: f32) -> Self {
        Self { alpha, angle: 0.0 }
    }

    /// Update filter with gyro and accelerometer
    ///
    /// # Arguments
    ///
    /// * `gyro_rate` - Angular rate from gyroscope (rad/s)
    /// * `accel_angle` - Angle from accelerometer (rad)
    /// * `dt` - Time step (s)
    pub fn update(&mut self, gyro_rate: f32, accel_angle: f32, dt: f32) -> f32 {
        self.angle = self.alpha * (self.angle + gyro_rate * dt) + (1.0 - self.alpha) * accel_angle;
        self.angle
    }

    /// Reset filter
    pub fn reset(&mut self) {
        self.angle = 0.0;
    }
}
