//! Fixed-size, `no_std`, no-heap linear algebra.
//!
//! Deliberately minimal: a naive const-generic dense matrix type covering just
//! the operations needed for small (roughly <=6x6) fixed-size systems -
//! Riccati recursion, an ADMM QP's KKT solve, an RLS covariance update. Not a
//! general-purpose linear algebra library. This mirrors the rest of the
//! codebase's convention of hand-rolling rather than depending on an external
//! abstraction crate (no `nalgebra` here, matching `hal`/`bsp`'s from-scratch
//! register-level style) - and TinyMPC-style embedded MPC, which this exists
//! to support, only ever needs a small, enumerable set of fixed-size
//! operations rather than general dense linear algebra.

use libm::sqrtf;

#[derive(Clone, Copy, Debug)]
pub struct MatN<const R: usize, const C: usize> {
    pub data: [[f32; C]; R],
}

impl<const R: usize, const C: usize> MatN<R, C> {
    pub const fn zero() -> Self {
        Self { data: [[0.0; C]; R] }
    }

    pub fn transpose(&self) -> MatN<C, R> {
        let mut out = MatN::<C, R>::zero();
        for i in 0..R {
            for j in 0..C {
                out.data[j][i] = self.data[i][j];
            }
        }
        out
    }

    pub fn add(&self, other: &Self) -> Self {
        let mut out = Self::zero();
        for i in 0..R {
            for j in 0..C {
                out.data[i][j] = self.data[i][j] + other.data[i][j];
            }
        }
        out
    }

    pub fn sub(&self, other: &Self) -> Self {
        let mut out = Self::zero();
        for i in 0..R {
            for j in 0..C {
                out.data[i][j] = self.data[i][j] - other.data[i][j];
            }
        }
        out
    }

    pub fn scale(&self, s: f32) -> Self {
        let mut out = Self::zero();
        for i in 0..R {
            for j in 0..C {
                out.data[i][j] = self.data[i][j] * s;
            }
        }
        out
    }

    /// Multiply by a column vector: (R x C) * (C) -> (R).
    pub fn mul_vec(&self, v: &[f32; C]) -> [f32; R] {
        let mut out = [0.0f32; R];
        for i in 0..R {
            let mut sum = 0.0f32;
            for j in 0..C {
                sum += self.data[i][j] * v[j];
            }
            out[i] = sum;
        }
        out
    }

    /// Frobenius norm - used for a compact defmt summary rather than dumping
    /// every element (see the `Format` impl below).
    pub fn frobenius_norm(&self) -> f32 {
        let mut sum = 0.0f32;
        for i in 0..R {
            for j in 0..C {
                sum += self.data[i][j] * self.data[i][j];
            }
        }
        sqrtf(sum)
    }
}

impl<const R: usize, const C: usize> Default for MatN<R, C> {
    fn default() -> Self {
        Self::zero()
    }
}

impl<const R: usize, const K: usize, const C: usize> core::ops::Mul<MatN<K, C>> for MatN<R, K> {
    type Output = MatN<R, C>;

    fn mul(self, rhs: MatN<K, C>) -> MatN<R, C> {
        let mut out = MatN::<R, C>::zero();
        for i in 0..R {
            for j in 0..C {
                let mut sum = 0.0f32;
                for k in 0..K {
                    sum += self.data[i][k] * rhs.data[k][j];
                }
                out.data[i][j] = sum;
            }
        }
        out
    }
}

// A per-element Format derive would spam RTT for anything bigger than a
// handful of entries; log a compact summary (shape + Frobenius norm) instead.
// Not needed for host (`std` feature) test builds, where nothing calls it.
#[cfg(not(feature = "std"))]
impl<const R: usize, const C: usize> defmt::Format for MatN<R, C> {
    fn format(&self, f: defmt::Formatter) {
        defmt::write!(f, "MatN<{},{}>(|.|_F={})", R, C, self.frobenius_norm());
    }
}

pub type Mat3 = MatN<3, 3>;
pub type Mat6 = MatN<6, 6>;

impl Mat3 {
    pub const fn identity() -> Self {
        Self {
            data: [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        }
    }

    pub fn from_diagonal(d: [f32; 3]) -> Self {
        Self {
            data: [[d[0], 0.0, 0.0], [0.0, d[1], 0.0], [0.0, 0.0, d[2]]],
        }
    }

    pub fn determinant(&self) -> f32 {
        let m = &self.data;
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    }

    /// Closed-form 3x3 inverse via the adjugate/determinant. Returns `None` if
    /// the matrix is singular (determinant below a small epsilon) - no
    /// general-purpose solve is needed for this fixed size.
    ///
    /// Also rejects a non-finite determinant explicitly: IEEE 754 comparisons
    /// involving NaN are always false, so `det.abs() < 1e-9` alone would let a
    /// NaN-contaminated matrix (e.g. from a bad upstream estimate) silently
    /// produce a NaN "inverse" via `1.0 / NaN` instead of being caught here.
    pub fn inverse(&self) -> Option<Self> {
        let det = self.determinant();
        if !det.is_finite() || det.abs() < 1e-9 {
            return None;
        }
        let inv_det = 1.0 / det;
        let m = &self.data;

        let adj = [
            [
                m[1][1] * m[2][2] - m[1][2] * m[2][1],
                m[0][2] * m[2][1] - m[0][1] * m[2][2],
                m[0][1] * m[1][2] - m[0][2] * m[1][1],
            ],
            [
                m[1][2] * m[2][0] - m[1][0] * m[2][2],
                m[0][0] * m[2][2] - m[0][2] * m[2][0],
                m[0][2] * m[1][0] - m[0][0] * m[1][2],
            ],
            [
                m[1][0] * m[2][1] - m[1][1] * m[2][0],
                m[0][1] * m[2][0] - m[0][0] * m[2][1],
                m[0][0] * m[1][1] - m[0][1] * m[1][0],
            ],
        ];

        let mut out = Self::zero();
        for i in 0..3 {
            for j in 0..3 {
                out.data[i][j] = adj[i][j] * inv_det;
            }
        }
        Some(out)
    }
}

/// Cholesky decomposition of a symmetric positive-definite matrix: returns the
/// lower-triangular `L` such that `A = L * L^T`. Returns `None` if `a` is not
/// SPD (a non-positive value would appear under a square root on the
/// diagonal).
pub fn cholesky<const N: usize>(a: &MatN<N, N>) -> Option<MatN<N, N>> {
    let mut l = MatN::<N, N>::zero();
    for i in 0..N {
        for j in 0..=i {
            let mut sum = a.data[i][j];
            for k in 0..j {
                sum -= l.data[i][k] * l.data[j][k];
            }
            if i == j {
                if sum <= 0.0 {
                    return None;
                }
                l.data[i][j] = sqrtf(sum);
            } else {
                l.data[i][j] = sum / l.data[j][j];
            }
        }
    }
    Some(l)
}

/// Solve `A x = b` given `A`'s Cholesky factor `L` (`A = L * L^T`), via
/// forward substitution (`L y = b`) then back substitution (`L^T x = y`).
pub fn cholesky_solve<const N: usize>(l: &MatN<N, N>, b: &[f32; N]) -> [f32; N] {
    let mut y = [0.0f32; N];
    for i in 0..N {
        let mut sum = b[i];
        for k in 0..i {
            sum -= l.data[i][k] * y[k];
        }
        y[i] = sum / l.data[i][i];
    }

    let mut x = [0.0f32; N];
    for ii in 0..N {
        let i = N - 1 - ii;
        let mut sum = y[i];
        for k in (i + 1)..N {
            sum -= l.data[k][i] * x[k]; // L^T[i][k] = L[k][i]
        }
        x[i] = sum / l.data[i][i];
    }

    x
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn multiply_matches_known_answer() {
        // Textbook 2x3 * 3x2 -> 2x2 example.
        let a = MatN::<2, 3> { data: [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]] };
        let b = MatN::<3, 2> { data: [[7.0, 8.0], [9.0, 10.0], [11.0, 12.0]] };
        let c = a * b;
        assert_eq!(c.data, [[58.0, 64.0], [139.0, 154.0]]);
    }

    #[test]
    fn transpose_swaps_indices() {
        let a = MatN::<2, 3> { data: [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]] };
        let t = a.transpose();
        assert_eq!(t.data, [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]);
    }

    #[test]
    fn mul_vec_matches_manual_computation() {
        let a = MatN::<2, 3> { data: [[1.0, 0.0, 2.0], [0.0, 1.0, -1.0]] };
        let v = [3.0, 4.0, 5.0];
        assert_eq!(a.mul_vec(&v), [13.0, -1.0]);
    }

    #[test]
    fn frobenius_norm_matches_sqrt_of_sum_of_squares() {
        let a = MatN::<2, 2> { data: [[3.0, 0.0], [0.0, 4.0]] };
        assert!((a.frobenius_norm() - 5.0).abs() < 1e-6);
    }

    #[test]
    fn frobenius_norm_of_zero_matrix_is_zero() {
        let a = MatN::<3, 3>::zero();
        assert_eq!(a.frobenius_norm(), 0.0);
    }

    #[test]
    fn default_matches_zero() {
        let a: MatN<2, 3> = Default::default();
        assert_eq!(a.data, MatN::<2, 3>::zero().data);
    }

    #[test]
    fn mat3_inverse_of_diagonal_matrix() {
        let m = Mat3 { data: [[2.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 5.0]] };
        let inv = m.inverse().expect("diagonal matrix with nonzero entries is invertible");
        let expected = [[0.5, 0.0, 0.0], [0.0, 0.25, 0.0], [0.0, 0.0, 0.2]];
        for i in 0..3 {
            for j in 0..3 {
                assert!((inv.data[i][j] - expected[i][j]).abs() < 1e-6);
            }
        }
        // Identity round-trip check: M * M^-1 == I.
        let identity = m * inv;
        for i in 0..3 {
            for j in 0..3 {
                let expected = if i == j { 1.0 } else { 0.0 };
                assert!((identity.data[i][j] - expected).abs() < 1e-5);
            }
        }
    }

    #[test]
    fn mat3_inverse_of_singular_matrix_is_none() {
        // Second row is a multiple of the first: singular.
        let m = Mat3 { data: [[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [0.0, 1.0, 0.0]] };
        assert!(m.inverse().is_none());
    }

    #[test]
    fn mat3_inverse_of_nan_contaminated_matrix_is_none() {
        // A NaN entry must be rejected, not silently propagated through
        // `1.0 / NaN` into a "successful" NaN result - see the `is_finite()`
        // guard in `inverse()`.
        let m = Mat3 { data: [[f32::NAN, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] };
        assert!(m.inverse().is_none());
    }

    #[test]
    fn cholesky_matches_known_textbook_example() {
        // Standard worked example: A = L * L^T.
        let a = MatN::<3, 3> {
            data: [[4.0, 12.0, -16.0], [12.0, 37.0, -43.0], [-16.0, -43.0, 98.0]],
        };
        let l = cholesky(&a).expect("A is SPD");
        let expected = [[2.0, 0.0, 0.0], [6.0, 1.0, 0.0], [-8.0, 5.0, 3.0]];
        for i in 0..3 {
            for j in 0..3 {
                assert!((l.data[i][j] - expected[i][j]).abs() < 1e-4, "L[{i}][{j}] = {}, expected {}", l.data[i][j], expected[i][j]);
            }
        }
    }

    #[test]
    fn cholesky_rejects_indefinite_matrix() {
        // Eigenvalues -1 and 3: indefinite, not SPD.
        let a = MatN::<2, 2> { data: [[1.0, 2.0], [2.0, 1.0]] };
        assert!(cholesky(&a).is_none());
    }

    #[test]
    fn cholesky_solve_recovers_known_solution() {
        let a = MatN::<3, 3> {
            data: [[4.0, 12.0, -16.0], [12.0, 37.0, -43.0], [-16.0, -43.0, 98.0]],
        };
        let l = cholesky(&a).expect("A is SPD");
        let x_expected = [1.0, 2.0, 3.0];
        let b = a.mul_vec(&x_expected);
        let x = cholesky_solve(&l, &b);
        for i in 0..3 {
            assert!((x[i] - x_expected[i]).abs() < 1e-3, "x[{i}] = {}, expected {}", x[i], x_expected[i]);
        }
    }
}
