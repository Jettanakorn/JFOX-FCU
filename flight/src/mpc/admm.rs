//! Bounded-iteration ADMM solver for the single-step box-constrained QP,
//! plus a feedforward term for zero-steady-state-offset tracking.
//!
//! **Feedback part.** With `e = x - x_ref`, minimizing
//! `(Ad*e + Bd*du)^T P (Ad*e + Bd*du) + du^T R du` over the feedback
//! correction `du` gives a standard QP `min (1/2)du^T H du + g^T du` with
//! `H = 2*(Bd^T P Bd + R)` and `g = 2*Bd^T P Ad e` (both from
//! `mpc::riccati::PrecomputedGains`, recomputed only when the model
//! changes). ADMM splits the box constraint on the *total* command
//! `u = u_ff + du` via a slack variable `z`:
//!
//!   u-update:  (H + rho*I) du = rho*(z - y) - g          [precomputed inverse]
//!   z-update:  z = clamp(du + y, u_min - u_ff, u_max - u_ff)  [shifted box, always feasible]
//!   y-update:  y = y + du - z                              [scaled dual ascent]
//!
//! then the returned command is `z + u_ff`, which lies in `[u_min, u_max]`
//! by construction of the shifted bounds.
//!
//! **Feedforward part.** Pure quadratic regulation (feedback alone, no
//! integral action) has a steady-state offset whenever `R > 0`: holding a
//! nonzero rate setpoint against damping requires a nonzero steady-state
//! `u`, but penalizing `u` means the feedback-only optimum never fully
//! reaches it. `u_ff = ff_gain * x_ref` (see `riccati::PrecomputedGains`)
//! supplies that steady-state input directly, so at `e = 0` the closed loop
//! is at a true equilibrium (`du* = 0`, `u = u_ff` exactly cancels the
//! model's drift). This is a standard feedforward+feedback split, not a
//! variationally-exact joint optimum - the R-cost cross-term between `u_ff`
//! and `du` is neglected, which is negligible as long as feedforward doesn't
//! dominate total control effort (verified empirically by
//! `mpc::tests::closed_loop_simulation_drives_rate_error_to_zero`).
//!
//! Box constraints (on the total command) are always feasible, so unlike a
//! general QP there is no "infeasible" outcome here - the returned command is
//! always in-bounds after every single iteration, even before the residual
//! has fully converged. `MpcController` (mpc/mod.rs) is what can fail (a
//! singular model), not this solver.

use super::riccati::PrecomputedGains;

#[derive(Clone, Copy, Debug)]
pub struct AdmmState {
    pub(crate) u: [f32; 3],
    pub(crate) z: [f32; 3],
    pub(crate) y: [f32; 3],
}

impl AdmmState {
    pub const fn new() -> Self {
        Self { u: [0.0; 3], z: [0.0; 3], y: [0.0; 3] }
    }

    pub fn reset(&mut self) {
        *self = Self::new();
    }
}

impl Default for AdmmState {
    fn default() -> Self {
        Self::new()
    }
}

/// Run `max_iters` ADMM iterations warm-started from `state`'s previous
/// solution (fewer iterations are needed once the loop is already near the
/// optimum from the previous control tick, which is the usual receding-horizon
/// warm-start benefit). `e = x - x_ref`, `u_ff` is the feedforward command for
/// the current setpoint. Returns the feasible, in-bounds total command.
pub fn solve(
    gains: &PrecomputedGains,
    e: [f32; 3],
    u_ff: [f32; 3],
    bounds: (f32, f32),
    rho: f32,
    max_iters: usize,
    state: &mut AdmmState,
) -> [f32; 3] {
    let (lo, hi) = bounds;
    let g = gains.feedback_gain.mul_vec(&e).map(|v| 2.0 * v);
    let du_lo = [lo - u_ff[0], lo - u_ff[1], lo - u_ff[2]];
    let du_hi = [hi - u_ff[0], hi - u_ff[1], hi - u_ff[2]];

    for _ in 0..max_iters {
        // u-update: du = H_rho_inv * (rho*(z-y) - g)
        let rhs = [
            rho * (state.z[0] - state.y[0]) - g[0],
            rho * (state.z[1] - state.y[1]) - g[1],
            rho * (state.z[2] - state.y[2]) - g[2],
        ];
        state.u = gains.h_rho_inv.mul_vec(&rhs);

        // z-update: project (du + y) onto the shifted box.
        for i in 0..3 {
            state.z[i] = (state.u[i] + state.y[i]).clamp(du_lo[i], du_hi[i]);
        }

        // y-update: scaled dual ascent.
        for i in 0..3 {
            state.y[i] += state.u[i] - state.z[i];
        }
    }

    [state.z[0] + u_ff[0], state.z[1] + u_ff[1], state.z[2] + u_ff[2]]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mpc::riccati::precompute;
    use math::Mat3;

    const ZERO_FF: [f32; 3] = [0.0, 0.0, 0.0];

    fn test_gains() -> PrecomputedGains {
        let ad = Mat3::from_diagonal([0.98, 0.98, 0.98]);
        let bd = Mat3::from_diagonal([0.1, 0.1, 0.1]);
        let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
        let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);
        precompute(&ad, &bd, &q, &r, 1.0, 100).expect("well-posed decoupled system")
    }

    #[test]
    fn default_matches_new() {
        let default_state = AdmmState::default();
        let new_state = AdmmState::new();
        assert_eq!(default_state.u, new_state.u);
        assert_eq!(default_state.z, new_state.z);
        assert_eq!(default_state.y, new_state.y);
    }

    #[test]
    fn zero_error_and_zero_feedforward_gives_zero_command() {
        let gains = test_gains();
        let mut state = AdmmState::new();
        let u = solve(&gains, [0.0, 0.0, 0.0], ZERO_FF, (-1.0, 1.0), 1.0, 50, &mut state);
        for v in u {
            assert!(v.abs() < 1e-6);
        }
    }

    #[test]
    fn feedforward_alone_passes_through_when_error_is_zero() {
        let gains = test_gains();
        let mut state = AdmmState::new();
        let u_ff = [0.3, -0.2, 0.1];
        let u = solve(&gains, [0.0, 0.0, 0.0], u_ff, (-1.0, 1.0), 1.0, 50, &mut state);
        for i in 0..3 {
            assert!((u[i] - u_ff[i]).abs() < 1e-4, "axis {i}: got {} expected feedforward {}", u[i], u_ff[i]);
        }
    }

    #[test]
    fn unconstrained_feedback_matches_closed_form_lqr_gain() {
        let gains = test_gains();
        let e = [0.5, -0.3, 0.2];

        // Closed form: du* = -H^-1 * g, with very wide bounds so the box
        // constraint never binds and ADMM should converge to the same point.
        let g = gains.feedback_gain.mul_vec(&e).map(|v| 2.0 * v);
        let h_inv = gains.h.inverse().expect("H must be invertible");
        let neg_g = [-g[0], -g[1], -g[2]];
        let du_closed_form = h_inv.mul_vec(&neg_g);

        let mut state = AdmmState::new();
        let u = solve(&gains, e, ZERO_FF, (-100.0, 100.0), 1.0, 200, &mut state);

        for i in 0..3 {
            assert!((u[i] - du_closed_form[i]).abs() < 1e-3, "axis {i}: admm={} closed_form={}", u[i], du_closed_form[i]);
        }
    }

    #[test]
    fn output_opposes_a_positive_rate_error() {
        // Positive rate error (state ahead of setpoint) with positive control
        // effectiveness should produce a negative correction, matching
        // standard state-feedback sign convention (u = -K*e).
        let gains = test_gains();
        let mut state = AdmmState::new();
        let u = solve(&gains, [1.0, 1.0, 1.0], ZERO_FF, (-1.0, 1.0), 1.0, 100, &mut state);
        for v in u {
            assert!(v < 0.0, "expected negative correction, got {v}");
        }
    }

    #[test]
    fn respects_box_constraints_under_large_error() {
        let gains = test_gains();
        let mut state = AdmmState::new();
        let u = solve(&gains, [100.0, -100.0, 100.0], ZERO_FF, (-1.0, 1.0), 1.0, 100, &mut state);
        for v in u {
            assert!((-1.0..=1.0).contains(&v), "output {v} outside bounds");
        }
        // Such a large error should saturate the constraint.
        assert!((u[0] - (-1.0)).abs() < 1e-2);
        assert!((u[1] - 1.0).abs() < 1e-2);
        assert!((u[2] - (-1.0)).abs() < 1e-2);
    }

    #[test]
    fn feedforward_shifts_the_effective_saturation_point() {
        // With a nonzero feedforward already consuming some actuator budget,
        // a large *positive* error (state ahead of setpoint) drives a strongly
        // *negative* feedback correction (see `output_opposes_a_positive_rate_error`),
        // which should still saturate at the true lower bound - not beyond it,
        // and not merely at bound-minus-feedforward.
        let gains = test_gains();
        let mut state = AdmmState::new();
        let u_ff = [0.5, 0.0, 0.0];
        let u = solve(&gains, [100.0, 0.0, 0.0], u_ff, (-1.0, 1.0), 1.0, 100, &mut state);
        assert!((u[0] - (-1.0)).abs() < 1e-2, "expected saturation at -1.0, got {}", u[0]);
    }

    #[test]
    fn warm_start_converges_in_fewer_iterations_than_cold_start() {
        let gains = test_gains();
        let e = [0.5, -0.3, 0.2];

        // Cold start, few iterations.
        let mut cold = AdmmState::new();
        let u_cold_3 = solve(&gains, e, ZERO_FF, (-1.0, 1.0), 1.0, 3, &mut cold);

        // Warm start: run to convergence once, then re-solve for the *same*
        // error with only 1 extra iteration - should already be at the fixed
        // point and barely move, unlike the cold 3-iteration result.
        let mut warm = AdmmState::new();
        let _ = solve(&gains, e, ZERO_FF, (-1.0, 1.0), 1.0, 50, &mut warm);
        let converged = warm.z;
        let u_warm_1 = solve(&gains, e, ZERO_FF, (-1.0, 1.0), 1.0, 1, &mut warm);

        for i in 0..3 {
            assert!((u_warm_1[i] - (converged[i] + ZERO_FF[i])).abs() < 1e-4);
        }
        // Sanity: the cold 3-iteration result should generally still be
        // measurably different from the converged solution.
        let cold_diff: f32 = (0..3).map(|i| (u_cold_3[i] - converged[i]).abs()).sum();
        assert!(cold_diff > 1e-4, "expected cold-start to not yet be converged after 3 iterations");
    }
}
