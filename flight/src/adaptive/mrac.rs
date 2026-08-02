//! Online control-effectiveness estimator, feeding `mpc::MpcController`'s
//! internal model - this is the "MRAC" piece of the layered architecture: not
//! a separate parallel controller, but a slow parameter estimator that keeps
//! the MPC's linear model matched to the real airframe (mass/inertia shifts,
//! partial motor degradation, etc).
//!
//! One scalar recursive-least-squares (RLS) estimator per axis, independent
//! (no cross-axis coupling estimated) - simpler and more robust than a full
//! matrix RLS, and sufficient for the diagonal `RateModel` this feeds.

/// Scalar RLS with a forgetting factor. Estimates `theta` in
/// `measurement ~= theta * regressor`.
#[derive(Clone, Copy, Debug)]
pub struct ScalarRls {
    pub theta: f32,
    covariance: f32,
    lambda: f32,
    min_covariance: f32,
    max_covariance: f32,
}

/// Below this regressor magnitude, an update is treated as "no real
/// excitation" and skipped entirely (see `ScalarRls::update`'s doc comment
/// for why this exists and isn't redundant with the `denom` guard).
const EXCITATION_DEADZONE: f32 = 0.01;

impl ScalarRls {
    pub fn new(initial_theta: f32, initial_covariance: f32, lambda: f32) -> Self {
        Self {
            theta: initial_theta,
            covariance: initial_covariance,
            lambda,
            min_covariance: 1e-6,
            max_covariance: 1e6,
        }
    }

    /// One RLS update step.
    ///
    /// INVARIANT: `regressor` must be gated by `EXCITATION_DEADZONE` before
    /// touching `covariance` at all - this is not just an optimization.
    /// Found via SITL (see `sitl/README.md`): with `lambda` close to 1 (the
    /// only realistic range - see `ParamEstimator::new`'s callers), `denom =
    /// lambda + regressor^2*covariance` stays close to `lambda` for *any*
    /// small regressor, so the old `denom.abs() < 1e-12` check never actually
    /// caught near-zero excitation - it only guarded the degenerate
    /// `lambda≈0` case. During real flight's quiet periods (near-setpoint,
    /// near-zero commanded rate change), `regressor` sits in the ~1e-4 range
    /// for many consecutive updates; with no real skip, `covariance ≈
    /// covariance/lambda` grows every single update (compounding, since
    /// `gain*regressor*covariance` is a product of two near-zero terms and
    /// so contributes ~nothing back). Once wound up anywhere near
    /// `max_covariance`, the next merely-small (not tiny) regressor produces
    /// `gain = covariance*regressor/denom` on the order of 1e4-1e5, so a
    /// single noisy sample can swing `theta` through zero and past its true
    /// sign - which is exactly what happened: `flight::mpc`'s control-
    /// effectiveness model went negative mid-flight, making the controller's
    /// commands actively wrong-signed and driving a real divergence in SITL.
    /// A dead-zone (skip entirely below a real excitation threshold) is the
    /// standard fix for this class of RLS/MRAC "estimator windup" failure -
    /// not a tuned magic number, a structural gate on when identification is
    /// even possible.
    pub fn update(&mut self, regressor: f32, measurement: f32) {
        if regressor.abs() < EXCITATION_DEADZONE {
            return;
        }
        let denom = self.lambda + regressor * regressor * self.covariance;
        if denom.abs() < 1e-12 {
            // Degenerate lambda (near-zero forgetting factor): skip the
            // update rather than divide by ~zero. Distinct from the
            // dead-zone above - see this function's doc comment.
            return;
        }
        let gain = self.covariance * regressor / denom;
        let error = measurement - self.theta * regressor;
        self.theta += gain * error;
        self.covariance = (self.covariance - gain * regressor * self.covariance) / self.lambda;
        // Anti-windup: prevent covariance blow-up under sustained poor excitation.
        self.covariance = self.covariance.clamp(self.min_covariance, self.max_covariance);
    }

    pub fn reset(&mut self, initial_theta: f32, initial_covariance: f32) {
        self.theta = initial_theta;
        self.covariance = initial_covariance;
    }
}

use math::Vec3;

pub struct ParamEstimator {
    roll: ScalarRls,
    pitch: ScalarRls,
    yaw: ScalarRls,
    prev_gyro: Option<Vec3>,
}

impl ParamEstimator {
    pub fn new(initial_effectiveness: Vec3, initial_covariance: f32, lambda: f32) -> Self {
        Self {
            roll: ScalarRls::new(initial_effectiveness.x, initial_covariance, lambda),
            pitch: ScalarRls::new(initial_effectiveness.y, initial_covariance, lambda),
            yaw: ScalarRls::new(initial_effectiveness.z, initial_covariance, lambda),
            prev_gyro: None,
        }
    }

    /// Call at a decimated rate (e.g. ~50-100Hz, not every 500Hz control
    /// tick) with the current gyro rate, the motor command that produced the
    /// *next* reading (i.e. the command applied over the interval ending at
    /// this `gyro` sample), and the elapsed time since the last call. Returns
    /// `None` on the first call (no previous sample to difference against).
    pub fn update(&mut self, gyro: Vec3, motor_cmd: Vec3, dt: f32) -> Option<Vec3> {
        let prev = self.prev_gyro.replace(gyro)?;
        if dt <= 0.0 {
            return None;
        }
        let alpha = (gyro - prev).scale(1.0 / dt); // finite-difference angular accel

        self.roll.update(motor_cmd.x, alpha.x);
        self.pitch.update(motor_cmd.y, alpha.y);
        self.yaw.update(motor_cmd.z, alpha.z);

        Some(Vec3::new(self.roll.theta, self.pitch.theta, self.yaw.theta))
    }

    pub fn reset(&mut self, initial_effectiveness: Vec3, initial_covariance: f32) {
        self.roll.reset(initial_effectiveness.x, initial_covariance);
        self.pitch.reset(initial_effectiveness.y, initial_covariance);
        self.yaw.reset(initial_effectiveness.z, initial_covariance);
        self.prev_gyro = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scalar_rls_converges_to_known_effectiveness() {
        let theta_true = 5.0f32;
        let mut rls = ScalarRls::new(0.0, 100.0, 0.98);

        // Persistently-exciting regressor (varying, not constant) is required
        // for RLS convergence - a fixed regressor only constrains one
        // direction and would not identify theta uniquely in general, though
        // for a scalar system even a constant nonzero regressor converges;
        // vary it anyway to match how a real motor command sequence would look.
        for i in 0..500 {
            let regressor = 0.3 + 0.2 * ((i as f32) * 0.1).sin();
            let measurement = theta_true * regressor; // noiseless synthetic plant
            rls.update(regressor, measurement);
        }

        assert!((rls.theta - theta_true).abs() < 0.01, "theta={} expected close to {}", rls.theta, theta_true);
    }

    #[test]
    fn scalar_rls_skips_update_on_near_zero_regressor() {
        let mut rls = ScalarRls::new(3.0, 1.0, 0.98);
        rls.update(0.0, 100.0); // huge "measurement" but zero excitation
        assert_eq!(rls.theta, 3.0, "near-zero regressor must not perturb theta");
    }

    #[test]
    fn scalar_rls_skips_update_when_denominator_is_degenerate() {
        // denom = lambda + regressor^2*covariance: with lambda=0.0 and a
        // zero regressor, denom is exactly 0.0, hitting the `denom.abs() <
        // 1e-12` guard directly (unlike the near-zero-regressor test above,
        // where a typical nonzero lambda keeps denom well away from zero and
        // the no-op instead falls out of gain=0).
        let mut rls = ScalarRls::new(3.0, 1.0, 0.0);
        rls.update(0.0, 100.0);
        assert_eq!(rls.theta, 3.0, "degenerate denominator must not perturb theta");
    }

    #[test]
    fn scalar_rls_dead_zone_ignores_sustained_sub_threshold_regressor_without_perturbing_theta() {
        let mut rls = ScalarRls::new(3.0, 1.0, 0.995);
        // Below EXCITATION_DEADZONE (0.01) but not exactly zero - the case
        // the old denom-based guard did NOT actually catch for a realistic
        // lambda close to 1 (see `update`'s doc comment).
        for _ in 0..500 {
            rls.update(0.005, 999.0); // a wildly wrong "measurement" too, to make sure it's truly ignored
        }
        assert_eq!(rls.theta, 3.0, "sub-deadzone regressor must never perturb theta, however long it's sustained");
    }

    #[test]
    fn scalar_rls_dead_zone_prevents_covariance_windup_during_a_quiet_period() {
        // The bug this dead-zone fixes: with no gate, `covariance` grows by
        // ~1/lambda every update whenever regressor is small (see `update`'s
        // doc comment) - "quiet" flight is exactly this condition. Confirm
        // covariance is completely unmoved by a long quiet period, not just
        // "still bounded by max_covariance".
        let mut rls = ScalarRls::new(3.0, 50.0, 0.995);
        for _ in 0..1000 {
            rls.update(0.005, 0.0);
        }
        assert_eq!(rls.covariance, 50.0, "covariance must not wind up during sustained sub-deadzone excitation");
    }

    #[test]
    fn param_estimator_first_call_returns_none() {
        let mut est = ParamEstimator::new(Vec3::new(10.0, 10.0, 10.0), 10.0, 0.98);
        assert!(est.update(Vec3::zero(), Vec3::zero(), 0.02).is_none());
    }

    #[test]
    fn param_estimator_rejects_a_non_positive_dt_after_the_first_call() {
        let mut est = ParamEstimator::new(Vec3::new(10.0, 10.0, 10.0), 10.0, 0.98);
        est.update(Vec3::new(1.0, 1.0, 1.0), Vec3::new(0.5, 0.5, 0.5), 0.02); // establishes prev_gyro
        assert!(est.update(Vec3::new(2.0, 2.0, 2.0), Vec3::new(0.5, 0.5, 0.5), 0.0).is_none());
        assert!(est.update(Vec3::new(2.0, 2.0, 2.0), Vec3::new(0.5, 0.5, 0.5), -0.01).is_none());
    }

    #[test]
    fn param_estimator_converges_on_synthetic_plant() {
        let true_effectiveness = Vec3::new(8.0, 6.0, 4.0);
        let mut est = ParamEstimator::new(Vec3::new(1.0, 1.0, 1.0), 50.0, 0.98);
        let dt = 0.02;
        let mut gyro = Vec3::zero();

        for i in 0..500 {
            let cmd = Vec3::new(
                0.3 + 0.2 * ((i as f32) * 0.1).sin(),
                0.2 + 0.15 * ((i as f32) * 0.13).cos(),
                -0.1 + 0.1 * ((i as f32) * 0.07).sin(),
            );
            // Synthetic plant: alpha = effectiveness * cmd (noiseless), integrate to get next gyro.
            let alpha = Vec3::new(true_effectiveness.x * cmd.x, true_effectiveness.y * cmd.y, true_effectiveness.z * cmd.z);
            let next_gyro = gyro + alpha.scale(dt);

            let estimate = est.update(next_gyro, cmd, dt);
            gyro = next_gyro;
            let _ = estimate;
        }

        let final_estimate = Vec3::new(est.roll.theta, est.pitch.theta, est.yaw.theta);
        assert!((final_estimate.x - true_effectiveness.x).abs() < 0.1, "roll estimate {} vs true {}", final_estimate.x, true_effectiveness.x);
        assert!((final_estimate.y - true_effectiveness.y).abs() < 0.1, "pitch estimate {} vs true {}", final_estimate.y, true_effectiveness.y);
        assert!((final_estimate.z - true_effectiveness.z).abs() < 0.1, "yaw estimate {} vs true {}", final_estimate.z, true_effectiveness.z);
    }

    #[test]
    fn reset_clears_history_and_restarts_from_given_values() {
        let mut est = ParamEstimator::new(Vec3::new(10.0, 10.0, 10.0), 10.0, 0.98);
        let _ = est.update(Vec3::new(1.0, 1.0, 1.0), Vec3::new(0.5, 0.5, 0.5), 0.02);
        est.reset(Vec3::new(2.0, 2.0, 2.0), 10.0);
        // After reset, first update must again return None (no previous sample).
        assert!(est.update(Vec3::zero(), Vec3::zero(), 0.02).is_none());
        assert_eq!(est.roll.theta, 2.0);
    }
}
