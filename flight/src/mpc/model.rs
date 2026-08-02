//! Linear discrete-time body-rate model used by the MPC rate-loop controller.
//!
//! State x = body rates [p, q, r] (rad/s, roll/pitch/yaw). Input u = normalized
//! per-axis torque command in -1.0..=1.0 (the same convention as
//! `flight::mixer::MixerInput::{roll,pitch,yaw}`).
//!
//! Continuous-time model, decoupled per axis (diagonal, symmetric-airframe
//! simplification - no gyroscopic cross-coupling term, which is a legitimate
//! small-perturbation approximation near hover but not exact in aggressive
//! maneuvers):
//!
//!   omega_dot = -D * omega + Beff * u
//!
//! where `D` (rad/s per rad/s, i.e. 1/s) is aerodynamic/mechanical damping and
//! `Beff` (rad/s^2 per unit command) is the control-effectiveness constant -
//! the quantity `flight::adaptive::mrac` estimates online. Discretized with
//! forward Euler at the control loop's `dt` (valid since dt=2ms is much
//! smaller than the rate loop's time constants).

use math::Mat3;

#[derive(Clone, Copy, Debug)]
pub struct RateModel {
    pub ad: Mat3,
    pub bd: Mat3,
    pub dt: f32,
}

impl RateModel {
    pub fn new(damping_diag: [f32; 3], effectiveness_diag: [f32; 3], dt: f32) -> Self {
        let ac = Mat3::from_diagonal([-damping_diag[0], -damping_diag[1], -damping_diag[2]]);
        let bc = Mat3::from_diagonal(effectiveness_diag);

        // Forward Euler: Ad = I + dt*Ac, Bd = dt*Bc
        let ad = Mat3::identity().add(&ac.scale(dt));
        let bd = bc.scale(dt);

        Self { ad, bd, dt }
    }

    pub fn update(&mut self, damping_diag: [f32; 3], effectiveness_diag: [f32; 3], dt: f32) {
        *self = Self::new(damping_diag, effectiveness_diag, dt);
    }

    /// One-step-ahead state prediction: x_next = Ad*x + Bd*u.
    pub fn predict(&self, state: [f32; 3], u: [f32; 3]) -> [f32; 3] {
        let ax = self.ad.mul_vec(&state);
        let bu = self.bd.mul_vec(&u);
        [ax[0] + bu[0], ax[1] + bu[1], ax[2] + bu[2]]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn predict_matches_manual_computation() {
        // damping=2/s, effectiveness=10 (rad/s^2 per unit cmd), dt=0.01s
        // Ad = 1 - 0.02 = 0.98 (per axis), Bd = 0.1 (per axis)
        let model = RateModel::new([2.0, 2.0, 2.0], [10.0, 10.0, 10.0], 0.01);
        let x = [1.0, -1.0, 0.5];
        let u = [0.2, 0.0, -0.3];
        let next = model.predict(x, u);
        assert!((next[0] - (0.98 * 1.0 + 0.1 * 0.2)).abs() < 1e-5);
        assert!((next[1] - (0.98 * -1.0 + 0.1 * 0.0)).abs() < 1e-5);
        assert!((next[2] - (0.98 * 0.5 + 0.1 * -0.3)).abs() < 1e-5);
    }

    #[test]
    fn update_replaces_ad_bd_dt_with_a_freshly_constructed_model() {
        let mut model = RateModel::new([2.0, 2.0, 2.0], [10.0, 10.0, 10.0], 0.01);
        model.update([5.0, 5.0, 5.0], [1.0, 1.0, 1.0], 0.02);

        let rebuilt = RateModel::new([5.0, 5.0, 5.0], [1.0, 1.0, 1.0], 0.02);
        assert_eq!(model.dt, rebuilt.dt);
        assert_eq!(model.ad.data, rebuilt.ad.data);
        assert_eq!(model.bd.data, rebuilt.bd.data);
    }

    #[test]
    fn zero_input_decays_toward_zero_under_damping() {
        let model = RateModel::new([5.0, 5.0, 5.0], [10.0, 10.0, 10.0], 0.01);
        let mut x = [1.0, 1.0, 1.0];
        for _ in 0..200 {
            x = model.predict(x, [0.0, 0.0, 0.0]);
        }
        for v in x {
            assert!(v.abs() < 0.01, "expected decay toward zero, got {v}");
        }
    }
}
