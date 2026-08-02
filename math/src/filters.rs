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

#[cfg(test)]
mod tests {
    use super::*;
    const EPS: f32 = 1e-4;

    fn approx_eq(a: f32, b: f32) -> bool {
        (a - b).abs() < EPS
    }

    #[test]
    fn low_pass_first_update_snaps_to_the_sample_rather_than_blending_from_zero() {
        // `initialized` guard: without it, the first real sample would be
        // blended against the bogus value=0.0 default instead of taken as-is.
        let mut lpf = LowPassFilter::new(10.0, 100.0);
        let output = lpf.update(50.0);
        assert_eq!(output, 50.0);
    }

    #[test]
    fn low_pass_subsequent_updates_blend_toward_the_new_sample() {
        let mut lpf = LowPassFilter::new(10.0, 100.0);
        lpf.update(0.0);
        let output = lpf.update(10.0);
        // alpha = dt/(rc+dt) is in (0,1), so a step from 0 to 10 should land
        // strictly between the two, not jump all the way to 10.
        assert!(output > 0.0 && output < 10.0, "output: {output}");
    }

    #[test]
    fn low_pass_converges_toward_a_constant_input_over_many_updates() {
        let mut lpf = LowPassFilter::new(10.0, 100.0);
        lpf.update(0.0);
        let mut output = 0.0;
        for _ in 0..500 {
            output = lpf.update(5.0);
        }
        assert!(approx_eq(output, 5.0), "output: {output}");
    }

    #[test]
    fn low_pass_reset_forgets_prior_state_so_the_next_update_snaps_again() {
        let mut lpf = LowPassFilter::new(10.0, 100.0);
        lpf.update(0.0);
        lpf.update(0.0);
        lpf.reset();
        // Post-reset, the first update should snap exactly to the sample
        // again (re-exercises the `!initialized` branch), not blend from
        // the pre-reset value of 0.0 (which would look identical for this
        // particular sample - use a nonzero one to actually distinguish
        // "snapped" from "blended from stale 0.0").
        let output = lpf.update(7.0);
        assert_eq!(output, 7.0);
    }

    #[test]
    fn complementary_filter_with_alpha_one_ignores_accel_entirely() {
        let mut cf = ComplementaryFilter::new(1.0);
        // angle = 1.0*(0 + gyro_rate*dt) + 0.0*accel_angle
        let angle = cf.update(2.0, 999.0, 0.5); // gyro contributes 2.0*0.5=1.0; accel_angle should be fully ignored
        assert!(approx_eq(angle, 1.0), "angle: {angle}");
    }

    #[test]
    fn complementary_filter_with_alpha_zero_tracks_accel_entirely() {
        let mut cf = ComplementaryFilter::new(0.0);
        let angle = cf.update(999.0, 3.0, 0.5); // gyro should be fully ignored
        assert!(approx_eq(angle, 3.0), "angle: {angle}");
    }

    #[test]
    fn complementary_filter_blends_gyro_integration_and_accel_angle() {
        let mut cf = ComplementaryFilter::new(0.98);
        // angle = 0.98*(0 + 1.0*1.0) + 0.02*0.0 = 0.98
        let angle = cf.update(1.0, 0.0, 1.0);
        assert!(approx_eq(angle, 0.98), "angle: {angle}");
    }

    #[test]
    fn complementary_filter_reset_returns_angle_to_zero() {
        let mut cf = ComplementaryFilter::new(0.98);
        cf.update(1.0, 1.0, 1.0);
        cf.reset();
        // Immediately after reset, a zero-input update should read back as
        // exactly zero (angle state was cleared, not just decayed).
        let angle = cf.update(0.0, 0.0, 1.0);
        assert_eq!(angle, 0.0);
    }
}
