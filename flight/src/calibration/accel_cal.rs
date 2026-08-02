//! Accelerometer calibration: per-axis bias (offset) and scale correction.
//! Unlike gyro bias, this is not something that can be safely auto-measured
//! at every boot - a real calibration requires the vehicle to be placed on
//! each of its faces in turn (a 6-point calibration) or an equivalent
//! deliberate procedure, which needs a command link this codebase doesn't
//! have yet (see `flight::arming`'s module docs for the same gap). What
//! *can* be done without that: persist a calibration once it exists (see
//! `storage`) and apply it - or, if none is stored yet, use the identity
//! (no-op) correction so the vehicle still boots and flies, just less
//! precisely, rather than refusing to function without one.

use math::Vec3;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AccelCalibration {
    pub bias: Vec3,  // m/s^2, subtracted from the raw reading first
    pub scale: Vec3, // multiplicative correction, applied after bias subtraction
}

impl AccelCalibration {
    /// No-op correction: used when no calibration is stored yet.
    pub fn identity() -> Self {
        Self { bias: Vec3::zero(), scale: Vec3::new(1.0, 1.0, 1.0) }
    }

    pub fn apply(&self, raw: Vec3) -> Vec3 {
        Vec3::new(
            (raw.x - self.bias.x) * self.scale.x,
            (raw.y - self.bias.y) * self.scale.y,
            (raw.z - self.bias.z) * self.scale.z,
        )
    }
}

impl Default for AccelCalibration {
    fn default() -> Self {
        Self::identity()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_calibration_is_a_no_op() {
        let cal = AccelCalibration::identity();
        let raw = Vec3::new(1.0, -2.5, 9.8);
        let corrected = cal.apply(raw);
        assert_eq!(corrected, raw);
    }

    #[test]
    fn bias_and_scale_apply_in_the_right_order() {
        let cal = AccelCalibration { bias: Vec3::new(1.0, 0.0, 0.0), scale: Vec3::new(2.0, 1.0, 1.0) };
        // (5 - 1) * 2 = 8, not 5*2 - 1 = 9: bias subtracted before scaling.
        let corrected = cal.apply(Vec3::new(5.0, 0.0, 0.0));
        assert!((corrected.x - 8.0).abs() < 1e-6);
    }

    #[test]
    fn default_matches_identity() {
        assert_eq!(AccelCalibration::default(), AccelCalibration::identity());
    }
}
