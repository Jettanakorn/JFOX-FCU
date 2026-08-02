//! L1-style adaptive disturbance filter, sitting between the MPC's nominal
//! command and the mixer.
//!
//! Structure (the defining L1 property): a *fast* adaptation law estimates a
//! matched disturbance from the one-step-ahead prediction error, but that
//! estimate is only ever applied to the plant through a *low-pass filter* -
//! decoupling how quickly the estimator reacts from how quickly the
//! correction hits the actuators. This is what gives L1 its robustness
//! advantage over plain MRAC: raising the adaptation gain improves disturbance
//! tracking without directly raising the bandwidth of what reaches the motors
//! (that's set by the filter cutoff instead), so fast adaptation doesn't by
//! itself erode phase margin the way it does in classical MRAC.
//!
//! Simplification, stated plainly: a rigorous L1 state predictor estimates
//! the disturbance in the plant's own units and inverts it through the
//! control-effectiveness matrix (`Bd^-1`) before filtering. Here the estimate
//! is formed directly in command-space (`adaptation_gain * prediction_error`,
//! with `adaptation_gain` absorbing the missing `Bd^-1` scaling as a single
//! tunable constant) rather than a dimensionally-exact matched-uncertainty
//! inversion - a common simplification for a rate-loop compensator whose job
//! is empirical disturbance rejection, not system identification (that's
//! `adaptive::mrac`'s job).

use math::Vec3;
use math::filters::LowPassFilter;
use crate::mpc::model::RateModel;

pub struct L1Filter {
    sigma_hat: Vec3,
    lpf: [LowPassFilter; 3],
    adaptation_gain: f32,
    predicted_next: Option<Vec3>,
}

impl L1Filter {
    pub fn new(cutoff_hz: f32, sample_rate_hz: f32, adaptation_gain: f32) -> Self {
        Self {
            sigma_hat: Vec3::zero(),
            lpf: [
                LowPassFilter::new(cutoff_hz, sample_rate_hz),
                LowPassFilter::new(cutoff_hz, sample_rate_hz),
                LowPassFilter::new(cutoff_hz, sample_rate_hz),
            ],
            adaptation_gain,
            predicted_next: None,
        }
    }

    /// One filter step. `measured_rate` is this tick's gyro reading,
    /// `mpc_cmd` is the MPC's nominal (pre-augmentation) command, `model` is
    /// the MPC's current internal model (for forming next tick's prediction).
    /// Returns the L1-augmented command to hand to the mixer.
    pub fn update(&mut self, measured_rate: Vec3, mpc_cmd: Vec3, model: &RateModel, dt: f32) -> Vec3 {
        let _ = dt; // reserved: LowPassFilter's cutoff is baked in at construction, not per-call
        if let Some(predicted) = self.predicted_next {
            let prediction_error = measured_rate - predicted;
            self.sigma_hat = prediction_error.scale(self.adaptation_gain);
        }

        let filtered = Vec3::new(
            self.lpf[0].update(self.sigma_hat.x),
            self.lpf[1].update(self.sigma_hat.y),
            self.lpf[2].update(self.sigma_hat.z),
        );

        self.predicted_next = Some({
            let next = model.predict([measured_rate.x, measured_rate.y, measured_rate.z], [mpc_cmd.x, mpc_cmd.y, mpc_cmd.z]);
            Vec3::new(next[0], next[1], next[2])
        });

        mpc_cmd - filtered
    }

    pub fn reset(&mut self) {
        self.sigma_hat = Vec3::zero();
        for f in &mut self.lpf {
            f.reset();
        }
        self.predicted_next = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_model() -> RateModel {
        RateModel::new([2.0, 2.0, 2.0], [10.0, 10.0, 10.0], 0.002)
    }

    #[test]
    fn no_prediction_error_gives_negligible_compensation() {
        let model = test_model();
        let mut l1 = L1Filter::new(5.0, 500.0, 1.0);
        let mut rate = Vec3::zero();
        let cmd = Vec3::new(0.2, -0.1, 0.05);

        // Drive the filter with measurements that exactly match the model's
        // own predictions (a perfectly-modeled, undisturbed plant).
        for _ in 0..50 {
            let out = l1.update(rate, cmd, &model, 0.002);
            assert!((out - cmd).magnitude() < 1e-3, "expected near-zero compensation, got {:?}", out);
            let next = model.predict([rate.x, rate.y, rate.z], [cmd.x, cmd.y, cmd.z]);
            rate = Vec3::new(next[0], next[1], next[2]);
        }
    }

    #[test]
    fn constant_disturbance_produces_persistent_opposing_compensation() {
        let model = test_model();
        // adaptation_gain=50: the raw prediction error each tick is only
        // ~disturbance*dt (a single step's worth, since the prediction is
        // re-based on the actual, already-disturbed state every tick - it
        // does not accumulate), so a gain of order 1/dt is needed for the
        // resulting sigma_hat to be a command-scale (not floating-point-noise
        // scale) correction. This is exactly the "adaptation_gain absorbs the
        // missing Bd^-1 scaling" simplification from the module doc comment.
        let mut l1 = L1Filter::new(5.0, 500.0, 50.0);
        let cmd = Vec3::new(0.2, 0.0, 0.0);
        let mut rate = Vec3::zero();
        let disturbance = Vec3::new(0.5, 0.0, 0.0); // constant extra rate-of-change on roll only

        let mut last_out = cmd;
        for _ in 0..300 {
            last_out = l1.update(rate, cmd, &model, 0.002);
            let next = model.predict([rate.x, rate.y, rate.z], [cmd.x, cmd.y, cmd.z]);
            // Apply the true (disturbed) plant, not the nominal model, to get
            // the *next* measurement - this is what creates a persistent
            // prediction error for the filter to adapt against.
            rate = Vec3::new(next[0], next[1], next[2]) + disturbance.scale(0.002);
        }

        // A sustained positive disturbance on roll should settle into a
        // persistent, clearly-nonzero negative compensation on roll (opposing
        // it), and leave the undisturbed axes essentially unaffected.
        assert!(last_out.x < cmd.x - 0.02, "expected a clearly nonzero opposing roll compensation, got {}", last_out.x);
        assert!((last_out.y - cmd.y).abs() < 1e-3);
        assert!((last_out.z - cmd.z).abs() < 1e-3);
    }

    #[test]
    fn reset_clears_adaptation_and_prediction_state() {
        let model = test_model();
        let mut l1 = L1Filter::new(5.0, 500.0, 2.0);
        let _ = l1.update(Vec3::new(1.0, 1.0, 1.0), Vec3::new(0.2, 0.2, 0.2), &model, 0.002);
        l1.reset();
        assert_eq!(l1.sigma_hat, Vec3::zero());
        assert!(l1.predicted_next.is_none());

        // Immediately after reset, behaves like a fresh filter: first call
        // can't yet have a prediction error, so output should equal the raw
        // command exactly.
        let cmd = Vec3::new(0.3, -0.2, 0.1);
        let out = l1.update(Vec3::new(5.0, 5.0, 5.0), cmd, &model, 0.002);
        assert_eq!(out, cmd);
    }
}
