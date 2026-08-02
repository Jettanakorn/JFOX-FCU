//! Discrete-time Riccati recursion and ADMM gain precomputation.
//!
//! Solves the infinite-horizon discrete algebraic Riccati equation (DARE) by
//! fixed-point iteration:
//!
//!   P_{k+1} = Q + Ad^T P_k Ad - Ad^T P_k Bd (R + Bd^T P_k Bd)^-1 Bd^T P_k Ad
//!
//! `P`'s converged value is the infinite-horizon cost-to-go, used as the
//! terminal cost in `mpc::admm`'s single-step constrained optimization (see
//! that module's doc comment for why a 1-step explicit horizon with this
//! terminal cost is a deliberate, documented simplification rather than a
//! full multi-step rollout).

use math::Mat3;

/// Iterate the DARE fixed point. Returns `None` if `R + Bd^T P Bd` becomes
/// singular at any iteration (the model/weights don't admit a well-posed LQR
/// solution).
pub fn solve_riccati(ad: &Mat3, bd: &Mat3, q: &Mat3, r: &Mat3, iterations: usize) -> Option<Mat3> {
    let mut p = *q;
    let bd_t = bd.transpose();
    let ad_t = ad.transpose();

    for _ in 0..iterations {
        let bt_p = bd_t * p; // Bd^T P
        let s = r.add(&(bt_p * *bd)); // R + Bd^T P Bd
        let s_inv = s.inverse()?;
        let gain_term = s_inv * bt_p * *ad; // (R+Bd'PBd)^-1 Bd'PAd

        let at_p = ad_t * p; // Ad^T P
        let p_next = q.add(&(at_p * *ad)).sub(&(at_p * *bd * gain_term));
        p = p_next;
    }
    Some(p)
}

/// Gains derived from the Riccati solution, precomputed once per model update
/// (i.e. at the slow rate `flight::adaptive::mrac` runs at, not every control
/// tick) so the hot-path ADMM solve only ever does matrix-vector products.
///
/// Pure quadratic state regulation (this cost function, no integral action)
/// has an inherent steady-state offset whenever `R > 0`: driving
/// `x_next - x_ref` and `u` to zero simultaneously is generally impossible
/// when holding a nonzero setpoint requires a nonzero steady-state `u` (e.g.
/// any model with damping). `ff_gain` provides that missing steady-state
/// input as a feedforward term, computed once here and applied on top of the
/// feedback correction in `admm::solve` - see that module's doc comment for
/// the full derivation and the one approximation this introduces (the R-cost
/// cross-term between the feedforward and feedback commands is neglected,
/// which is standard practice for feedforward+feedback architectures and
/// negligible as long as feedforward doesn't dominate total control effort).
#[derive(Clone, Copy, Debug)]
pub struct PrecomputedGains {
    /// Infinite-horizon cost-to-go.
    pub p: Mat3,
    /// H = 2*(Bd^T P Bd + R), the QP's Hessian.
    pub h: Mat3,
    /// (H + rho*I)^-1, the factor ADMM's u-update needs every iteration.
    pub h_rho_inv: Mat3,
    /// Bd^T P Ad, used to form the feedback linear term g = 2 * feedback_gain * e,
    /// where e = x - x_ref.
    pub feedback_gain: Mat3,
    /// Bd^-1 * (I - Ad), the feedforward gain: u_ff = ff_gain * x_ref is the
    /// steady-state input needed to hold x = x_ref with zero feedback
    /// correction. Zero if Bd is singular (no feedforward possible; the
    /// feedback term alone still functions, just with the usual droop).
    pub ff_gain: Mat3,
}

pub fn precompute(ad: &Mat3, bd: &Mat3, q: &Mat3, r: &Mat3, rho: f32, iterations: usize) -> Option<PrecomputedGains> {
    let p = solve_riccati(ad, bd, q, r, iterations)?;
    let bt_p = bd.transpose() * p;
    let h = (bt_p * *bd).add(r).scale(2.0);
    let h_rho = h.add(&Mat3::identity().scale(rho));
    let h_rho_inv = h_rho.inverse()?;
    let feedback_gain = bt_p * *ad;
    let i_minus_ad = Mat3::identity().sub(ad);
    let ff_gain = bd.inverse().map(|bd_inv| bd_inv * i_minus_ad).unwrap_or(Mat3::zero());
    Some(PrecomputedGains { p, h, h_rho_inv, feedback_gain, ff_gain })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn riccati_converges_to_a_fixed_point() {
        let ad = Mat3::from_diagonal([0.98, 0.98, 0.98]);
        let bd = Mat3::from_diagonal([0.1, 0.1, 0.1]);
        let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
        let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);

        let p_50 = solve_riccati(&ad, &bd, &q, &r, 50).expect("well-posed decoupled system");
        let p_51 = solve_riccati(&ad, &bd, &q, &r, 51).expect("well-posed decoupled system");

        for i in 0..3 {
            for j in 0..3 {
                assert!((p_50.data[i][j] - p_51.data[i][j]).abs() < 1e-4, "P not converged at [{i}][{j}]: p_50={} p_51={}", p_50.data[i][j], p_51.data[i][j]);
            }
        }
    }

    #[test]
    fn riccati_fixed_point_satisfies_the_dare_residual() {
        let ad = Mat3::from_diagonal([0.98, 0.99, 0.97]);
        let bd = Mat3::from_diagonal([0.1, 0.08, 0.12]);
        let q = Mat3::from_diagonal([1.0, 2.0, 0.5]);
        let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);

        let p = solve_riccati(&ad, &bd, &q, &r, 100).expect("well-posed decoupled system");

        // Plug P back into the DARE right-hand side and confirm it reproduces P.
        let bt_p = bd.transpose() * p;
        let s = r.add(&(bt_p * bd));
        let s_inv = s.inverse().expect("S must be invertible at the fixed point");
        let gain_term = s_inv * bt_p * ad;
        let at_p = ad.transpose() * p;
        let rhs = q.add(&(at_p * ad)).sub(&(at_p * bd * gain_term));

        for i in 0..3 {
            for j in 0..3 {
                assert!((rhs.data[i][j] - p.data[i][j]).abs() < 1e-3, "DARE residual too large at [{i}][{j}]: rhs={} p={}", rhs.data[i][j], p.data[i][j]);
            }
        }
    }

    #[test]
    fn p_is_positive_definite_on_the_diagonal() {
        // For this decoupled, well-posed system P should end up diagonal (no
        // cross-coupling was ever introduced) with strictly positive entries.
        let ad = Mat3::from_diagonal([0.98, 0.98, 0.98]);
        let bd = Mat3::from_diagonal([0.1, 0.1, 0.1]);
        let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
        let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);

        let p = solve_riccati(&ad, &bd, &q, &r, 100).expect("well-posed decoupled system");
        for i in 0..3 {
            assert!(p.data[i][i] > 0.0);
            for j in 0..3 {
                if i != j {
                    assert!(p.data[i][j].abs() < 1e-4, "expected decoupled P, off-diagonal [{i}][{j}]={}", p.data[i][j]);
                }
            }
        }
    }

    #[test]
    fn precompute_produces_a_valid_inverse() {
        let ad = Mat3::from_diagonal([0.98, 0.98, 0.98]);
        let bd = Mat3::from_diagonal([0.1, 0.1, 0.1]);
        let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
        let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);

        let gains = precompute(&ad, &bd, &q, &r, 1.0, 100).expect("well-posed system");
        let identity_check = gains.h.add(&Mat3::identity().scale(1.0)) * gains.h_rho_inv;
        for i in 0..3 {
            for j in 0..3 {
                let expected = if i == j { 1.0 } else { 0.0 };
                assert!((identity_check.data[i][j] - expected).abs() < 1e-3);
            }
        }
    }
}
