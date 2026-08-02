//! Single-step constrained-MPC rate-loop controller.
//!
//! See `riccati` and `admm` module docs for the exact formulation. Summary:
//! the Riccati-derived infinite-horizon cost-to-go stands in for a full
//! multi-step horizon's tail, so this is a deliberately-scoped "MPC" - a
//! receding-horizon, hard-constrained optimal controller re-solved every
//! control tick, just with an explicit horizon of 1 rather than N. This keeps
//! the solver small enough to hand-verify and to run comfortably within the
//! 2ms `control_task` budget on an STM32F427, at the cost of not looking
//! multiple steps ahead the way TinyMPC-style N=10-20 horizons do.

pub mod model;
pub mod riccati;
pub mod admm;

use math::{Mat3, Vec3};
use model::RateModel;
use riccati::PrecomputedGains;
use admm::AdmmState;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[cfg_attr(not(feature = "std"), derive(defmt::Format))]
pub enum MpcError {
    /// The model/weights don't admit a well-posed LQR solution (a singular
    /// `R + Bd^T P Bd` or `H + rho*I` during Riccati/ADMM precomputation).
    /// This can only happen on `new`/`update_model`, never on `solve` - box
    /// constraints are always feasible once precomputation has succeeded.
    ModelInvalid,
}

pub struct MpcController {
    model: RateModel,
    q: Mat3,
    r: Mat3,
    rho: f32,
    gains: PrecomputedGains,
    admm: AdmmState,
}

impl MpcController {
    pub fn new(model: RateModel, q: Mat3, r: Mat3, rho: f32, riccati_iters: usize) -> Result<Self, MpcError> {
        let gains = riccati::precompute(&model.ad, &model.bd, &q, &r, rho, riccati_iters)
            .ok_or(MpcError::ModelInvalid)?;
        Ok(Self { model, q, r, rho, gains, admm: AdmmState::new() })
    }

    /// Rebuild the model and re-run Riccati/ADMM precomputation - call at a
    /// slow, decimated rate (see `flight::adaptive::mrac`), never every tick.
    /// On failure the previous gains are kept untouched: a bad parameter
    /// estimate must not silently corrupt a previously-valid controller.
    ///
    /// `iterations` is caller-specified (rather than reusing the constructor's
    /// `riccati_iters`) so a recurring, time-budget-sensitive caller can use
    /// fewer iterations here than it affords for the one-time cost in `new`.
    pub fn update_model(&mut self, damping_diag: [f32; 3], effectiveness_diag: [f32; 3], iterations: usize) -> Result<(), MpcError> {
        let candidate = RateModel::new(damping_diag, effectiveness_diag, self.model.dt);
        let gains = riccati::precompute(&candidate.ad, &candidate.bd, &self.q, &self.r, self.rho, iterations)
            .ok_or(MpcError::ModelInvalid)?;
        self.model = candidate;
        self.gains = gains;
        Ok(())
    }

    pub fn model(&self) -> &RateModel {
        &self.model
    }

    /// Solve for a bounded, feasible per-axis command given the current rate
    /// state, its setpoint, and actuator bounds (matching
    /// `flight::mixer::MixerInput`'s -1.0..=1.0 convention). Combines a
    /// feedback correction (drives e=x-x_ref to zero) with a feedforward term
    /// (the steady-state command needed to hold x_ref against the model's
    /// damping) - see `admm` module docs for why both are needed to avoid a
    /// persistent tracking offset.
    pub fn solve(&mut self, measured_rate: Vec3, rate_setpoint: Vec3, bounds: (f32, f32), max_iters: usize) -> Vec3 {
        let e = [measured_rate.x - rate_setpoint.x, measured_rate.y - rate_setpoint.y, measured_rate.z - rate_setpoint.z];
        let x_ref = [rate_setpoint.x, rate_setpoint.y, rate_setpoint.z];
        let u_ff = self.gains.ff_gain.mul_vec(&x_ref);
        let u = admm::solve(&self.gains, e, u_ff, bounds, self.rho, max_iters, &mut self.admm);
        Vec3::new(u[0], u[1], u[2])
    }

    /// Reset ADMM's warm-start state (e.g. on disarm, or on failover away from
    /// this path) so a stale iterate from a previous flight segment doesn't
    /// bias the next solve.
    pub fn reset(&mut self) {
        self.admm.reset();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_controller() -> MpcController {
        let model = RateModel::new([2.0, 2.0, 2.0], [10.0, 10.0, 10.0], 0.002);
        let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
        let r = Mat3::from_diagonal([0.05, 0.05, 0.05]);
        MpcController::new(model, q, r, 1.0, 50).expect("well-posed test model")
    }

    #[test]
    fn zero_error_gives_zero_command() {
        let mut mpc = test_controller();
        let u = mpc.solve(Vec3::zero(), Vec3::zero(), (-1.0, 1.0), 30);
        assert!(u.x.abs() < 1e-5 && u.y.abs() < 1e-5 && u.z.abs() < 1e-5);
    }

    #[test]
    fn closed_loop_simulation_drives_rate_error_to_zero() {
        // Simulate the real model in closed loop with the MPC controller and
        // confirm the rate state actually converges to the setpoint - this is
        // the end-to-end correctness property that matters, beyond the
        // per-module unit tests.
        let mut mpc = test_controller();
        let model = RateModel::new([2.0, 2.0, 2.0], [10.0, 10.0, 10.0], 0.002);
        let setpoint = Vec3::new(2.0, -1.5, 1.0);
        let mut state = Vec3::zero();

        for _ in 0..500 {
            let u = mpc.solve(state, setpoint, (-1.0, 1.0), 30);
            let next = model.predict([state.x, state.y, state.z], [u.x, u.y, u.z]);
            state = Vec3::new(next[0], next[1], next[2]);
        }

        assert!((state.x - setpoint.x).abs() < 0.05, "roll rate did not converge: {}", state.x);
        assert!((state.y - setpoint.y).abs() < 0.05, "pitch rate did not converge: {}", state.y);
        assert!((state.z - setpoint.z).abs() < 0.05, "yaw rate did not converge: {}", state.z);
    }

    #[test]
    fn update_model_keeps_old_gains_on_failure() {
        let mut mpc = test_controller();
        let original_gain = mpc.gains.feedback_gain;

        // A NaN-contaminated effectiveness estimate (e.g. from a diverged
        // MRAC estimator) must be rejected by precompute's Mat3::inverse
        // (finite-determinant guard), not silently propagated into the
        // controller's live gains.
        let result = mpc.update_model([2.0, 2.0, 2.0], [f32::NAN, 10.0, 10.0], 50);

        assert_eq!(result, Err(MpcError::ModelInvalid));
        assert_eq!(mpc.gains.feedback_gain.data, original_gain.data);
    }

    #[test]
    fn update_model_replaces_model_and_gains_on_success() {
        let mut mpc = test_controller();
        let original_model_bd = mpc.model().bd.data;

        mpc.update_model([4.0, 4.0, 4.0], [20.0, 20.0, 20.0], 50).expect("well-posed model");

        // The rebuilt model should differ from the original (different
        // damping/effectiveness -> different Bd), confirming `self.model`
        // was actually replaced rather than left untouched.
        assert_ne!(mpc.model().bd.data, original_model_bd);
        let expected = RateModel::new([4.0, 4.0, 4.0], [20.0, 20.0, 20.0], mpc.model().dt);
        assert_eq!(mpc.model().ad.data, expected.ad.data);
        assert_eq!(mpc.model().bd.data, expected.bd.data);
    }

    #[test]
    fn reset_clears_admm_warm_start() {
        let mut mpc = test_controller();
        // Drive some nonzero warm-start state in.
        let _ = mpc.solve(Vec3::new(1.0, 1.0, 1.0), Vec3::zero(), (-1.0, 1.0), 10);
        mpc.reset();
        assert_eq!(mpc.admm.u, [0.0; 3]);
        assert_eq!(mpc.admm.z, [0.0; 3]);
        assert_eq!(mpc.admm.y, [0.0; 3]);
    }
}
