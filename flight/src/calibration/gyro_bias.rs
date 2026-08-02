//! Gyro bias auto-calibration, run once at boot (assumes the vehicle is
//! stationary for the sampling window - the standard assumption every flight
//! controller makes). Not stored persistently: bias drifts with temperature
//! and changes at every power-on, so re-measuring fresh each boot is the
//! correct approach, not a limitation (unlike accelerometer scale/offset,
//! which genuinely needs `flight::calibration::storage`).
//!
//! Includes a stationarity check: if the sampled readings vary too much
//! during the window (someone bumped it, it's not actually stationary), the
//! calibration is rejected rather than silently accepted - accepting a bad
//! bias would corrupt every subsequent rate reading for the rest of the
//! flight, silently.

use math::Vec3;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CalState {
    InProgress,
    Success,
    Failed,
}

pub struct GyroBiasEstimator {
    sum: Vec3,
    sum_sq: Vec3,
    count: u32,
    samples_needed: u32,
    max_stddev: f32,
    bias: Vec3,
    state: CalState,
}

impl GyroBiasEstimator {
    /// `samples_needed`: how many raw gyro samples to average (at the IMU's
    /// sample rate, so e.g. 1000 samples @ 1kHz = 1 second). `max_stddev`
    /// (rad/s): per-axis standard deviation above which the window is judged
    /// "not actually stationary" and the calibration fails.
    pub fn new(samples_needed: u32, max_stddev: f32) -> Self {
        Self {
            sum: Vec3::zero(),
            sum_sq: Vec3::zero(),
            count: 0,
            samples_needed,
            max_stddev,
            bias: Vec3::zero(),
            state: CalState::InProgress,
        }
    }

    /// Feed one raw gyro sample. Returns the current state - keep calling
    /// until it's no longer `InProgress`.
    pub fn accumulate(&mut self, raw_gyro: Vec3) -> CalState {
        if self.state != CalState::InProgress {
            return self.state;
        }

        self.sum = self.sum + raw_gyro;
        self.sum_sq = self.sum_sq + Vec3::new(raw_gyro.x * raw_gyro.x, raw_gyro.y * raw_gyro.y, raw_gyro.z * raw_gyro.z);
        self.count += 1;

        if self.count >= self.samples_needed {
            let n = self.count as f32;
            let mean = self.sum.scale(1.0 / n);
            let mean_sq = Vec3::new(mean.x * mean.x, mean.y * mean.y, mean.z * mean.z);
            let variance = self.sum_sq.scale(1.0 / n) - mean_sq;
            let max_variance = self.max_stddev * self.max_stddev;

            if variance.x <= max_variance && variance.y <= max_variance && variance.z <= max_variance {
                self.bias = mean;
                self.state = CalState::Success;
            } else {
                self.state = CalState::Failed;
            }
        }

        self.state
    }

    pub fn state(&self) -> CalState {
        self.state
    }

    /// The estimated bias. Only meaningful when `state() == Success`; returns
    /// zero (a safe, neutral no-op correction) otherwise.
    pub fn bias(&self) -> Vec3 {
        if self.state == CalState::Success {
            self.bias
        } else {
            Vec3::zero()
        }
    }

    pub fn progress(&self) -> (u32, u32) {
        (self.count, self.samples_needed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stationary_samples_converge_to_the_true_bias() {
        let mut est = GyroBiasEstimator::new(100, 0.01);
        let true_bias = Vec3::new(0.02, -0.015, 0.005);
        let mut state = CalState::InProgress;
        for _ in 0..100 {
            // Noiseless "stationary" samples: constant bias, no motion.
            state = est.accumulate(true_bias);
        }
        assert_eq!(state, CalState::Success);
        let bias = est.bias();
        assert!((bias.x - true_bias.x).abs() < 1e-4);
        assert!((bias.y - true_bias.y).abs() < 1e-4);
        assert!((bias.z - true_bias.z).abs() < 1e-4);
    }

    #[test]
    fn in_progress_until_enough_samples() {
        let mut est = GyroBiasEstimator::new(10, 0.01);
        for _ in 0..9 {
            assert_eq!(est.accumulate(Vec3::zero()), CalState::InProgress);
        }
        assert_ne!(est.accumulate(Vec3::zero()), CalState::InProgress);
    }

    #[test]
    fn excessive_motion_during_window_fails_calibration() {
        let mut est = GyroBiasEstimator::new(100, 0.01);
        let mut state = CalState::InProgress;
        for i in 0..100 {
            // Large, varying "motion" - not stationary.
            let wobble = if i % 2 == 0 { 1.0 } else { -1.0 };
            state = est.accumulate(Vec3::new(wobble, 0.0, 0.0));
        }
        assert_eq!(state, CalState::Failed);
        // A failed calibration must yield a neutral (zero) bias, never a
        // bogus one derived from motion.
        assert_eq!(est.bias(), Vec3::zero());
    }

    #[test]
    fn excessive_motion_on_the_pitch_axis_alone_fails_calibration() {
        // Complements the roll-only wobble test above: the variance check is
        // a short-circuiting `x && y && z`, so a roll-only failure never
        // actually evaluates the y/z conditions. Isolate pitch (y) here so
        // x passes and y is the one that fails.
        let mut est = GyroBiasEstimator::new(100, 0.01);
        let mut state = CalState::InProgress;
        for i in 0..100 {
            let wobble = if i % 2 == 0 { 1.0 } else { -1.0 };
            state = est.accumulate(Vec3::new(0.0, wobble, 0.0));
        }
        assert_eq!(state, CalState::Failed);
    }

    #[test]
    fn excessive_motion_on_the_yaw_axis_alone_fails_calibration() {
        // Isolates z so both x and y pass and z is the one that fails.
        let mut est = GyroBiasEstimator::new(100, 0.01);
        let mut state = CalState::InProgress;
        for i in 0..100 {
            let wobble = if i % 2 == 0 { 1.0 } else { -1.0 };
            state = est.accumulate(Vec3::new(0.0, 0.0, wobble));
        }
        assert_eq!(state, CalState::Failed);
    }

    #[test]
    fn further_samples_after_completion_are_ignored() {
        let mut est = GyroBiasEstimator::new(10, 0.01);
        for _ in 0..10 {
            est.accumulate(Vec3::new(0.1, 0.0, 0.0));
        }
        assert_eq!(est.state(), CalState::Success);
        let bias_before = est.bias();
        // Feed wildly different data after completion - must not perturb the result.
        est.accumulate(Vec3::new(100.0, 100.0, 100.0));
        assert_eq!(est.bias(), bias_before);
    }

    #[test]
    fn progress_reports_sample_count() {
        let mut est = GyroBiasEstimator::new(5, 0.01);
        assert_eq!(est.progress(), (0, 5));
        est.accumulate(Vec3::zero());
        est.accumulate(Vec3::zero());
        assert_eq!(est.progress(), (2, 5));
    }
}
