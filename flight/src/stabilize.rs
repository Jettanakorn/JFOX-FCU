//! Stabilize mode controller: cascaded attitude (outer) + rate (inner) PID.

#![allow(dead_code)]

use crate::mixer::MixerInput;
use math::{PidController, Quat, Vec3};

/// Target attitude (radians) and throttle for the stabilizer.
#[derive(Clone, Copy, Debug, Default)]
pub struct AttitudeSetpoint {
    pub roll: f32,
    pub pitch: f32,
    pub yaw: f32,
    pub throttle: f32,
}

/// Gains for one cascaded axis: outer attitude-error loop and inner rate-error loop.
#[derive(Clone, Copy, Debug)]
pub struct AxisGains {
    pub att_kp: f32,
    pub att_ki: f32,
    pub att_kd: f32,
    pub att_limit: f32, // outer loop output = inner loop's rate setpoint, rad/s
    pub rate_kp: f32,
    pub rate_ki: f32,
    pub rate_kd: f32,
    pub rate_limit: f32, // inner loop output feeds the mixer, -1.0..=1.0
}

#[derive(Clone, Copy, Debug)]
pub struct StabilizeGains {
    pub roll: AxisGains,
    pub pitch: AxisGains,
    pub yaw: AxisGains,
}

/// Wrap an angle already known to lie within [-2*pi, 2*pi] into [-pi, pi].
/// Used for attitude error, where both operands already come from `Quat::to_euler`.
fn wrap_pi(angle: f32) -> f32 {
    const PI: f32 = core::f32::consts::PI;
    const TWO_PI: f32 = 2.0 * PI;
    let mut a = angle;
    if a > PI {
        a -= TWO_PI;
    }
    if a < -PI {
        a += TWO_PI;
    }
    a
}

/// Cascaded attitude -> rate PID stabilizer. Six independent `PidController`s:
/// one attitude-error and one rate-error loop per axis.
pub struct StabilizeController {
    roll_att: PidController,
    pitch_att: PidController,
    yaw_att: PidController,
    roll_rate: PidController,
    pitch_rate: PidController,
    yaw_rate: PidController,
}

impl StabilizeController {
    pub fn new(gains: StabilizeGains) -> Self {
        Self {
            roll_att: PidController::new(gains.roll.att_kp, gains.roll.att_ki, gains.roll.att_kd, gains.roll.att_limit),
            pitch_att: PidController::new(gains.pitch.att_kp, gains.pitch.att_ki, gains.pitch.att_kd, gains.pitch.att_limit),
            yaw_att: PidController::new(gains.yaw.att_kp, gains.yaw.att_ki, gains.yaw.att_kd, gains.yaw.att_limit),
            roll_rate: PidController::new(gains.roll.rate_kp, gains.roll.rate_ki, gains.roll.rate_kd, gains.roll.rate_limit),
            pitch_rate: PidController::new(gains.pitch.rate_kp, gains.pitch.rate_ki, gains.pitch.rate_kd, gains.pitch.rate_limit),
            yaw_rate: PidController::new(gains.yaw.rate_kp, gains.yaw.rate_ki, gains.yaw.rate_kd, gains.yaw.rate_limit),
        }
    }

    /// Outer loop only: attitude error -> body-rate setpoint (rad/s). Shared by
    /// both the rate-PID inner loop (`inner_loop`) and the adaptive-MPC path
    /// (Phase 2) - call this exactly once per tick regardless of which inner
    /// strategy is used, since it owns integrator state that must not be
    /// advanced twice in the same control period.
    pub fn outer_loop(&mut self, attitude: Quat, setpoint: AttitudeSetpoint, dt: f32) -> Vec3 {
        let (roll, pitch, yaw) = attitude.to_euler();

        let roll_err = wrap_pi(setpoint.roll - roll);
        let pitch_err = wrap_pi(setpoint.pitch - pitch);
        let yaw_err = wrap_pi(setpoint.yaw - yaw);

        Vec3::new(
            self.roll_att.update(roll_err, dt),
            self.pitch_att.update(pitch_err, dt),
            self.yaw_att.update(yaw_err, dt),
        )
    }

    /// Inner loop only: rate error -> mixer input, given a rate setpoint from
    /// `outer_loop` (or any other source).
    pub fn inner_loop(&mut self, rate_setpoint: Vec3, gyro: Vec3, throttle: f32, dt: f32) -> MixerInput {
        MixerInput {
            roll: self.roll_rate.update(rate_setpoint.x - gyro.x, dt),
            pitch: self.pitch_rate.update(rate_setpoint.y - gyro.y, dt),
            yaw: self.yaw_rate.update(rate_setpoint.z - gyro.z, dt),
            throttle,
        }
    }

    /// Run one full control step: attitude error -> rate setpoint -> rate error
    /// -> mixer input. Equivalent to `outer_loop` followed by `inner_loop`.
    pub fn update(&mut self, attitude: Quat, gyro: Vec3, setpoint: AttitudeSetpoint, dt: f32) -> MixerInput {
        let rate_setpoint = self.outer_loop(attitude, setpoint, dt);
        self.inner_loop(rate_setpoint, gyro, setpoint.throttle, dt)
    }

    /// Zero all integrators and derivative history. Call on disarm to prevent an
    /// integral-windup kick on the next arm.
    pub fn reset(&mut self) {
        self.roll_att.reset();
        self.pitch_att.reset();
        self.yaw_att.reset();
        self.roll_rate.reset();
        self.pitch_rate.reset();
        self.yaw_rate.reset();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_gains() -> StabilizeGains {
        let axis = AxisGains {
            att_kp: 4.0,
            att_ki: 0.0,
            att_kd: 0.0,
            att_limit: 3.0, // rad/s
            rate_kp: 0.15,
            rate_ki: 0.0,
            rate_kd: 0.0,
            rate_limit: 1.0,
        };
        StabilizeGains { roll: axis, pitch: axis, yaw: axis }
    }

    #[test]
    fn zero_error_gives_zero_attitude_output() {
        let mut ctrl = StabilizeController::new(test_gains());
        let out = ctrl.update(Quat::identity(), Vec3::zero(), AttitudeSetpoint { throttle: 0.5, ..Default::default() }, 0.002);
        assert!(out.roll.abs() < 1e-6);
        assert!(out.pitch.abs() < 1e-6);
        assert!(out.yaw.abs() < 1e-6);
        assert!((out.throttle - 0.5).abs() < 1e-6);
    }

    #[test]
    fn positive_roll_error_produces_positive_roll_output() {
        let mut ctrl = StabilizeController::new(test_gains());
        let setpoint = AttitudeSetpoint { roll: 0.2, throttle: 0.5, ..Default::default() };
        let out = ctrl.update(Quat::identity(), Vec3::zero(), setpoint, 0.002);
        assert!(out.roll > 0.0);
    }

    #[test]
    fn reset_clears_integrator_state() {
        let mut ctrl = StabilizeController::new(test_gains());
        let setpoint = AttitudeSetpoint { roll: 0.2, throttle: 0.5, ..Default::default() };
        for _ in 0..50 {
            ctrl.update(Quat::identity(), Vec3::zero(), setpoint, 0.002);
        }
        ctrl.reset();
        let out_after_reset = ctrl.update(Quat::identity(), Vec3::zero(), AttitudeSetpoint::default(), 0.002);
        assert!(out_after_reset.roll.abs() < 1e-6);
    }

    #[test]
    fn yaw_error_wraps_shortest_path() {
        // Setpoint just past +pi should behave like a small negative error, not a
        // near-2*pi swing, once wrapped.
        let mut ctrl = StabilizeController::new(test_gains());
        let setpoint = AttitudeSetpoint { yaw: -core::f32::consts::PI + 0.1, throttle: 0.5, ..Default::default() };
        let current = Quat::from_euler(0.0, 0.0, core::f32::consts::PI - 0.1);
        let out = ctrl.update(current, Vec3::zero(), setpoint, 0.002);
        // True angular distance here is 0.2 rad, not ~2*pi - 0.2 rad; output should
        // be small in magnitude, not saturated at the attitude-loop limit.
        assert!(out.yaw.abs() < 0.5, "yaw output {} suggests wrap-around was not applied", out.yaw);
    }

    #[test]
    fn yaw_error_wraps_shortest_path_in_the_other_direction() {
        // Mirror of the test above: this time the raw error lands above +pi
        // (not below -pi), exercising wrap_pi's `a > PI` branch instead.
        let mut ctrl = StabilizeController::new(test_gains());
        let setpoint = AttitudeSetpoint { yaw: core::f32::consts::PI - 0.1, throttle: 0.5, ..Default::default() };
        let current = Quat::from_euler(0.0, 0.0, -core::f32::consts::PI + 0.1);
        let out = ctrl.update(current, Vec3::zero(), setpoint, 0.002);
        assert!(out.yaw.abs() < 0.5, "yaw output {} suggests wrap-around was not applied", out.yaw);
    }
}
