//! Arming state machine.
//!
//! Gates motor output behind an explicit, debounced arm request plus continuous
//! pre-arm health checks. Disarming is never debounced: a failed check while
//! armed, or an explicit disarm request, moves out of `Armed` on the very next
//! `update()` call. This module contains no hardware access - callers (e.g.
//! `motor_task`) must gate all PWM output on `ArmingFsm::output_allowed()`.

#![allow(dead_code)]

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ArmState {
    Disarmed,
    Arming,
    Armed,
    Disarming,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum ArmRequest {
    #[default]
    None,
    Arm,
    Disarm,
}

/// Continuous pre-arm health checks. All fields must be true to enter or stay
/// armed. `bit_passed` is the result of the power-on Built-In Test sequence
/// (see `flight::bit`) - a boot-time snapshot, not re-run every tick, but
/// checked every tick like everything else here so a BIT failure blocks
/// arming for the rest of this boot rather than only being consulted once.
#[derive(Clone, Copy, Debug, Default)]
pub struct PreArmChecks {
    pub bit_passed: bool,
    pub attitude_valid: bool,
}

impl PreArmChecks {
    pub fn all_pass(&self) -> bool {
        self.bit_passed && self.attitude_valid
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum DisarmReason {
    #[default]
    None,
    UserRequest,
    PreArmCheckFailed,
}

/// Minimum continuous hold time on an `Arm` request (with checks passing) before
/// `Arming` transitions to `Armed`. Deliberately not required for the reverse
/// direction - see module docs.
const ARM_HOLD_SECONDS: f32 = 0.5;

pub struct ArmingFsm {
    state: ArmState,
    arming_hold_time: f32,
    last_disarm_reason: DisarmReason,
}

impl ArmingFsm {
    pub fn new() -> Self {
        Self {
            state: ArmState::Disarmed,
            arming_hold_time: 0.0,
            last_disarm_reason: DisarmReason::None,
        }
    }

    pub fn state(&self) -> ArmState {
        self.state
    }

    /// Whether motor output should be allowed this tick. Callers must gate all
    /// PWM/motor writes on this - `ArmingFsm` itself never touches hardware.
    pub fn output_allowed(&self) -> bool {
        self.state == ArmState::Armed
    }

    pub fn last_disarm_reason(&self) -> DisarmReason {
        self.last_disarm_reason
    }

    /// Advance the state machine by one control-loop tick. Exactly one state
    /// transition happens per call (a check-triggered disarm from `Armed` passes
    /// through one `Disarming` tick before reaching `Disarmed`, so the
    /// transition is observable to telemetry/logging, not silently skipped).
    pub fn update(&mut self, request: ArmRequest, checks: PreArmChecks, dt: f32) -> ArmState {
        let next = match self.state {
            ArmState::Disarmed => {
                self.arming_hold_time = 0.0;
                if request == ArmRequest::Arm && checks.all_pass() {
                    ArmState::Arming
                } else {
                    ArmState::Disarmed
                }
            }
            ArmState::Arming => {
                if request != ArmRequest::Arm || !checks.all_pass() {
                    // Released early, or a check failed mid-hold: abort, no partial arm.
                    self.arming_hold_time = 0.0;
                    ArmState::Disarmed
                } else {
                    self.arming_hold_time += dt;
                    if self.arming_hold_time >= ARM_HOLD_SECONDS {
                        self.arming_hold_time = 0.0;
                        ArmState::Armed
                    } else {
                        ArmState::Arming
                    }
                }
            }
            ArmState::Armed => {
                if !checks.all_pass() {
                    self.last_disarm_reason = DisarmReason::PreArmCheckFailed;
                    ArmState::Disarming
                } else if request == ArmRequest::Disarm {
                    self.last_disarm_reason = DisarmReason::UserRequest;
                    ArmState::Disarming
                } else {
                    ArmState::Armed
                }
            }
            ArmState::Disarming => ArmState::Disarmed,
        };

        self.state = next;
        self.state
    }
}

impl Default for ArmingFsm {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f32 = 0.002; // 500Hz control loop
    fn good_checks() -> PreArmChecks {
        PreArmChecks { bit_passed: true, attitude_valid: true }
    }
    fn bad_checks() -> PreArmChecks {
        PreArmChecks { bit_passed: false, attitude_valid: true }
    }

    #[test]
    fn starts_disarmed_and_refuses_output() {
        let fsm = ArmingFsm::new();
        assert_eq!(fsm.state(), ArmState::Disarmed);
        assert!(!fsm.output_allowed());
    }

    #[test]
    fn idle_request_while_disarmed_stays_disarmed() {
        let mut fsm = ArmingFsm::new();
        let state = fsm.update(ArmRequest::None, good_checks(), DT);
        assert_eq!(state, ArmState::Disarmed);
    }

    #[test]
    fn arm_request_requires_debounced_hold() {
        let mut fsm = ArmingFsm::new();
        let state = fsm.update(ArmRequest::Arm, good_checks(), DT);
        assert_eq!(state, ArmState::Arming);
        assert!(!fsm.output_allowed(), "must not allow output mid-arming-hold");
    }

    #[test]
    fn sustained_arm_request_reaches_armed_after_hold_time() {
        let mut fsm = ArmingFsm::new();
        let ticks = (ARM_HOLD_SECONDS / DT).ceil() as u32 + 1;
        let mut final_state = ArmState::Disarmed;
        for _ in 0..ticks {
            final_state = fsm.update(ArmRequest::Arm, good_checks(), DT);
        }
        assert_eq!(final_state, ArmState::Armed);
        assert!(fsm.output_allowed());
    }

    #[test]
    fn releasing_arm_request_mid_hold_aborts_to_disarmed() {
        let mut fsm = ArmingFsm::new();
        fsm.update(ArmRequest::Arm, good_checks(), DT);
        assert_eq!(fsm.state(), ArmState::Arming);
        let state = fsm.update(ArmRequest::None, good_checks(), DT);
        assert_eq!(state, ArmState::Disarmed);
    }

    #[test]
    fn cannot_arm_while_prearm_checks_fail() {
        let mut fsm = ArmingFsm::new();
        let state = fsm.update(ArmRequest::Arm, bad_checks(), DT);
        assert_eq!(state, ArmState::Disarmed);
    }

    #[test]
    fn check_failure_mid_hold_aborts_even_while_still_requesting_arm() {
        // Distinct from `releasing_arm_request_mid_hold_aborts_to_disarmed`:
        // here the request never lets up, only the checks fail - must still
        // abort, not stay in Arming waiting for checks to recover.
        let mut fsm = ArmingFsm::new();
        fsm.update(ArmRequest::Arm, good_checks(), DT);
        assert_eq!(fsm.state(), ArmState::Arming);
        let state = fsm.update(ArmRequest::Arm, bad_checks(), DT);
        assert_eq!(state, ArmState::Disarmed);
    }

    #[test]
    fn armed_disarms_immediately_on_check_failure_no_debounce() {
        let mut fsm = ArmingFsm::new();
        let ticks = (ARM_HOLD_SECONDS / DT).ceil() as u32 + 1;
        for _ in 0..ticks {
            fsm.update(ArmRequest::Arm, good_checks(), DT);
        }
        assert_eq!(fsm.state(), ArmState::Armed);

        // One bad tick: must leave Armed immediately (into Disarming), not stay
        // armed waiting for any hold/debounce period.
        let state = fsm.update(ArmRequest::None, bad_checks(), DT);
        assert_ne!(state, ArmState::Armed);
        assert!(!fsm.output_allowed());
        assert_eq!(fsm.last_disarm_reason(), DisarmReason::PreArmCheckFailed);

        // Fully settles to Disarmed on the following tick even if checks recover.
        let state = fsm.update(ArmRequest::None, good_checks(), DT);
        assert_eq!(state, ArmState::Disarmed);
    }

    #[test]
    fn stays_armed_while_checks_pass_and_no_disarm_is_requested() {
        let mut fsm = ArmingFsm::new();
        let ticks = (ARM_HOLD_SECONDS / DT).ceil() as u32 + 1;
        for _ in 0..ticks {
            fsm.update(ArmRequest::Arm, good_checks(), DT);
        }
        assert_eq!(fsm.state(), ArmState::Armed);

        let state = fsm.update(ArmRequest::None, good_checks(), DT);
        assert_eq!(state, ArmState::Armed);
        assert!(fsm.output_allowed());
    }

    #[test]
    fn default_matches_new() {
        let fsm = ArmingFsm::default();
        assert_eq!(fsm.state(), ArmState::Disarmed);
        assert!(!fsm.output_allowed());
    }

    #[test]
    fn armed_disarms_on_explicit_disarm_request() {
        let mut fsm = ArmingFsm::new();
        let ticks = (ARM_HOLD_SECONDS / DT).ceil() as u32 + 1;
        for _ in 0..ticks {
            fsm.update(ArmRequest::Arm, good_checks(), DT);
        }
        assert_eq!(fsm.state(), ArmState::Armed);

        let state = fsm.update(ArmRequest::Disarm, good_checks(), DT);
        assert_ne!(state, ArmState::Armed);
        assert_eq!(fsm.last_disarm_reason(), DisarmReason::UserRequest);
    }
}
