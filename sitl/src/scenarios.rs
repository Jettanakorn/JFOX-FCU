//! Scenario definitions and shared metrics for the SITL test program.
//!
//! Each scenario drives real production `flight::` code (not a
//! reimplementation) against independent physics/noise models, entirely on
//! the host. `ScenarioResult` is consumed two ways: `main.rs` runs every
//! scenario, prints PASS/FAIL, and writes a CSV per scenario for offline
//! plotting; the `#[cfg(test)] mod tests` block at the bottom of this file
//! wires the same functions into `cargo test` so CI/a pre-commit check can
//! catch a regression without a human reading CSV output - see
//! `sitl/README.md` for how to run either.
//!
//! **Metrics are windowed, not single-final-sample.** An earlier version of
//! this file checked only the last tick's value, which is fragile against a
//! system that has a persistent low-level oscillation: the pass/fail result
//! would depend on which phase of the oscillation the last tick happened to
//! land on. That fragility is exactly what let a real bug through (see
//! `sitl/README.md`'s "What this test program has already found" section) -
//! `max_motor_step_in_window` exists specifically because that bug's
//! symptom (motor commands chattering full-scale every tick) was invisible
//! to every check that only looked at attitude/rate.

use std::fs::File;
use std::io::Write;

use math::{Quat, Vec3};
use flight::MadgwickFilter;
use flight::stabilize::AttitudeSetpoint;
use flight::redundancy::ControlPath;
use flight::redundancy::voter::{TmrVoter, VoteResult};
use flight::calibration::gyro_bias::{GyroBiasEstimator, CalState};
use flight::arming::{ArmingFsm, ArmRequest, ArmState, PreArmChecks};

use crate::control_chain::{ControlChain, CONTROL_RATE_HZ, IMU_RATE_HZ};
use crate::plant::Plant;

const IMU_SUBSTEPS_PER_CONTROL_TICK: u32 = (IMU_RATE_HZ / CONTROL_RATE_HZ) as u32;
/// Tail window used by every "has it settled" check - long enough (250 ticks
/// @ 500Hz = 0.5s) to contain many periods of the chatter this test program
/// previously missed, so a lucky/unlucky final sample can't hide it.
const SETTLE_WINDOW_S: f32 = 0.5;
/// Above this, a per-tick motor delta is chatter, not settling noise - see
/// this module's doc comment. Empirically: a converged, healthy run shows
/// deltas of order 1e-3..1e-2; the L1-instability bug this test program
/// found showed deltas of 0.3-1.0 (full-scale swings every tick).
const MAX_HEALTHY_MOTOR_STEP: f32 = 0.3;

pub struct ScenarioResult {
    pub name: &'static str,
    pub passed: bool,
    pub detail: String,
}

#[derive(Clone, Copy)]
pub struct TickRecord {
    pub t: f32,
    pub attitude: Vec3, // Madgwick-estimated roll/pitch/yaw, rad
    pub rate_true: Vec3, // plant's true body rate, rad/s
    pub motor_cmd: [f32; 4],
    pub path: ControlPath,
}

fn new_plant() -> Plant {
    // Truth model: deliberately different from the controller's internal
    // assumption (inertia diag [1,1,1]-normalized effectiveness [8,8,4] in
    // control_chain.rs) - see plant.rs module docs for why.
    Plant::new([0.022, 0.022, 0.038], Vec3::new(9.5, 9.5, 3.3), 0.03)
}

/// Deterministic xorshift32 PRNG - reproducible noise injection without an
/// external `rand` crate dependency, matching this codebase's
/// hand-rolled-over-external-abstraction convention (see `math::matrix`'s
/// doc comment for the same rationale elsewhere in this codebase).
pub struct Xorshift32(u32);

impl Xorshift32 {
    pub fn new(seed: u32) -> Self {
        Self(if seed == 0 { 0xDEAD_BEEF } else { seed })
    }

    fn next_u32(&mut self) -> u32 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.0 = x;
        x
    }

    /// Uniform float in [-1.0, 1.0].
    pub fn next_signed_f32(&mut self) -> f32 {
        (self.next_u32() as f32 / u32::MAX as f32) * 2.0 - 1.0
    }
}

/// Runs one scenario to completion, writing `csv_path` and returning the
/// full per-tick history for the caller to assert on. `noise_fn` is called
/// once per *IMU* substep (1kHz) and its output added to that substep's
/// synthesized gyro/accel before it reaches the control chain - pass a
/// zero-returning closure for a noiseless run.
#[allow(clippy::too_many_arguments)]
pub fn run_scenario(
    csv_path: &str,
    duration_s: f32,
    setpoint_fn: impl Fn(f32) -> AttitudeSetpoint,
    disturbance_fn: impl Fn(f32) -> Vec3,
    force_invalid_fn: impl Fn(f32) -> bool,
    mut noise_fn: impl FnMut(&mut Xorshift32) -> (Vec3, Vec3),
) -> Vec<TickRecord> {
    let mut plant = new_plant();
    let mut chain = ControlChain::new();
    let mut motor_cmd = [0.0f32; 4];
    let dt_imu = 1.0 / IMU_RATE_HZ;
    let dt_control = 1.0 / CONTROL_RATE_HZ;
    let total_control_ticks = (duration_s * CONTROL_RATE_HZ) as u32;
    let mut rng = Xorshift32::new(0xC0FFEE);

    let mut file = File::create(csv_path).expect("failed to create CSV output file");
    writeln!(file, "time_s,roll_est,pitch_est,yaw_est,roll_rate_true,pitch_rate_true,yaw_rate_true,roll_rate_sp,pitch_rate_sp,yaw_rate_sp,roll_sp,pitch_sp,yaw_sp,m1,m2,m3,m4,path").unwrap();

    let mut history = Vec::with_capacity(total_control_ticks as usize);
    let mut last_gyro = Vec3::zero();

    for tick in 0..total_control_ticks {
        let t = tick as f32 * dt_control;
        let disturbance = disturbance_fn(t);

        for _ in 0..IMU_SUBSTEPS_PER_CONTROL_TICK {
            plant.step(motor_cmd, disturbance, dt_imu);
            let (gyro, accel) = plant.synthesize_imu();
            let (gyro_noise, accel_noise) = noise_fn(&mut rng);
            let noisy_gyro = gyro + gyro_noise;
            chain.imu_tick(noisy_gyro, accel + accel_noise);
            last_gyro = noisy_gyro;
        }

        let setpoint = setpoint_fn(t);
        let force_invalid = force_invalid_fn(t);
        let out = chain.control_tick(last_gyro, setpoint, dt_control, force_invalid);
        motor_cmd = out.motor_outputs;

        let (roll, pitch, yaw) = out.attitude_estimate.to_euler();
        let path_code = match out.path {
            ControlPath::AdaptiveMpc => 0,
            ControlPath::PidFallback => 1,
        };
        writeln!(
            file,
            "{:.4},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.5},{:.4},{:.4},{:.4},{:.4},{}",
            t, roll, pitch, yaw, plant.omega.x, plant.omega.y, plant.omega.z,
            out.rate_setpoint.x, out.rate_setpoint.y, out.rate_setpoint.z,
            setpoint.roll, setpoint.pitch, setpoint.yaw,
            motor_cmd[0], motor_cmd[1], motor_cmd[2], motor_cmd[3], path_code
        ).unwrap();

        history.push(TickRecord {
            t,
            attitude: Vec3::new(roll, pitch, yaw),
            rate_true: plant.omega,
            motor_cmd,
            path: out.path,
        });
    }

    println!("wrote {csv_path} ({total_control_ticks} ticks)");
    history
}

fn no_noise(_rng: &mut Xorshift32) -> (Vec3, Vec3) {
    (Vec3::zero(), Vec3::zero())
}

// ---- Windowed metrics ----

fn max_abs_axis(v: Vec3) -> f32 {
    v.x.abs().max(v.y.abs()).max(v.z.abs())
}

pub fn tail_window(history: &[TickRecord], window_s: f32) -> &[TickRecord] {
    if history.len() < 2 {
        return history;
    }
    let dt = history[1].t - history[0].t;
    let window_ticks = ((window_s / dt) as usize).max(1);
    let start = history.len().saturating_sub(window_ticks);
    &history[start..]
}

pub fn max_rate_in_window(window: &[TickRecord]) -> f32 {
    window.iter().map(|r| max_abs_axis(r.rate_true)).fold(0.0, f32::max)
}

pub fn max_attitude_err_in_window(window: &[TickRecord], setpoint: AttitudeSetpoint) -> f32 {
    window
        .iter()
        .map(|r| {
            let e = Vec3::new(r.attitude.x - setpoint.roll, r.attitude.y - setpoint.pitch, r.attitude.z - setpoint.yaw);
            max_abs_axis(e)
        })
        .fold(0.0, f32::max)
}

/// Largest single-tick change on any motor within the window - see this
/// module's doc comment for why this check exists.
pub fn max_motor_step_in_window(window: &[TickRecord]) -> f32 {
    let mut max_delta = 0.0f32;
    for pair in window.windows(2) {
        for i in 0..4 {
            let d = (pair[1].motor_cmd[i] - pair[0].motor_cmd[i]).abs();
            max_delta = max_delta.max(d);
        }
    }
    max_delta
}

pub fn all_finite(history: &[TickRecord]) -> bool {
    history.iter().all(|r| {
        r.attitude.x.is_finite()
            && r.attitude.y.is_finite()
            && r.attitude.z.is_finite()
            && r.rate_true.x.is_finite()
            && r.rate_true.y.is_finite()
            && r.rate_true.z.is_finite()
            && r.motor_cmd.iter().all(|m| m.is_finite())
    })
}

// ---- Scenarios ----

pub fn scenario_step_response() -> ScenarioResult {
    let setpoint = AttitudeSetpoint { roll: 0.3, pitch: -0.2, yaw: 0.1, throttle: 0.5 };
    let history = run_scenario("sitl_step_response.csv", 2.0, move |_t| setpoint, |_t| Vec3::zero(), |_t| false, no_noise);

    let tail = tail_window(&history, SETTLE_WINDOW_S);
    let max_err = max_attitude_err_in_window(tail, setpoint);
    let max_motor_step = max_motor_step_in_window(tail);
    let passed = max_err < 0.05 && max_motor_step < MAX_HEALTHY_MOTOR_STEP && all_finite(&history);
    ScenarioResult {
        name: "step_response",
        passed,
        detail: format!("settled attitude error (max axis, last {SETTLE_WINDOW_S}s) = {max_err:.4} rad, max motor step = {max_motor_step:.4}"),
    }
}

pub fn scenario_disturbance_rejection() -> ScenarioResult {
    let setpoint = AttitudeSetpoint { roll: 0.0, pitch: 0.0, yaw: 0.0, throttle: 0.5 };
    let history = run_scenario(
        "sitl_disturbance_rejection.csv",
        3.0,
        move |_t| setpoint,
        |t| if (1.0..1.5).contains(&t) { Vec3::new(0.6, 0.0, 0.0) } else { Vec3::zero() },
        |_t| false,
        no_noise,
    );

    let tail = tail_window(&history, SETTLE_WINDOW_S);
    let max_err = max_attitude_err_in_window(tail, setpoint);
    let max_rate = max_rate_in_window(tail);
    let max_motor_step = max_motor_step_in_window(tail);
    let recovered = max_err < 0.05 && max_rate < 0.05 && max_motor_step < MAX_HEALTHY_MOTOR_STEP && all_finite(&history);
    ScenarioResult {
        name: "disturbance_rejection",
        passed: recovered,
        detail: format!("post-recovery (last {SETTLE_WINDOW_S}s): max attitude err={max_err:.4} rad, max rate={max_rate:.4} rad/s, max motor step={max_motor_step:.4}"),
    }
}

pub fn scenario_mpc_failover() -> ScenarioResult {
    let setpoint = AttitudeSetpoint { roll: 0.15, pitch: 0.0, yaw: 0.0, throttle: 0.5 };
    let history = run_scenario(
        "sitl_mpc_failover.csv",
        2.0,
        move |_t| setpoint,
        |_t| Vec3::zero(),
        |t| (0.5..1.0).contains(&t),
        no_noise,
    );

    // Correct path selected in and out of the forced-invalid window.
    let path_correct = history.iter().all(|r| {
        let expected = if (0.5..1.0).contains(&r.t) { ControlPath::PidFallback } else { ControlPath::AdaptiveMpc };
        r.path == expected
    });
    let finite = all_finite(&history);

    let tail = tail_window(&history, SETTLE_WINDOW_S);
    let max_err = max_attitude_err_in_window(tail, setpoint);
    let max_motor_step = max_motor_step_in_window(tail);
    let recovered = max_err < 0.05 && max_motor_step < MAX_HEALTHY_MOTOR_STEP;

    let passed = path_correct && finite && recovered;
    ScenarioResult {
        name: "mpc_failover",
        passed,
        detail: format!(
            "path_selection_correct={path_correct}, all_finite={finite}, post-recovery max attitude err={max_err:.4} rad, max motor step={max_motor_step:.4}"
        ),
    }
}

pub fn scenario_combined_maneuver() -> ScenarioResult {
    // All three axes commanded simultaneously and non-triv1ially (unlike
    // step_response, which only ever settles once) - roll/pitch step
    // immediately, then a yaw reversal partway through, so the mixer/MPC
    // have to handle simultaneous cross-axis commands changing mid-flight,
    // not just converge once and sit still.
    let history = run_scenario(
        "sitl_combined_maneuver.csv",
        3.0,
        |t| {
            let yaw = if t < 1.5 { 0.4 } else { -0.4 };
            AttitudeSetpoint { roll: 0.25, pitch: -0.25, yaw, throttle: 0.6 }
        },
        |_t| Vec3::zero(),
        |_t| false,
        no_noise,
    );

    let final_setpoint = AttitudeSetpoint { roll: 0.25, pitch: -0.25, yaw: -0.4, throttle: 0.6 };
    let tail = tail_window(&history, SETTLE_WINDOW_S);
    let max_err = max_attitude_err_in_window(tail, final_setpoint);
    let max_motor_step = max_motor_step_in_window(tail);
    let passed = max_err < 0.05 && max_motor_step < MAX_HEALTHY_MOTOR_STEP && all_finite(&history);
    ScenarioResult {
        name: "combined_maneuver",
        passed,
        detail: format!("post-yaw-reversal settled error (max axis) = {max_err:.4} rad, max motor step = {max_motor_step:.4}"),
    }
}

pub fn scenario_sensor_noise_robustness() -> ScenarioResult {
    // Uniform +-noise on every IMU substep - not a claim of matching real
    // MPU-6000 noise density, just enough continuous excitation to show the
    // control chain degrades gracefully (bounded, finite, roughly converged)
    // rather than diverging or amplifying noise into instability. Magnitudes:
    // ~0.01 rad/s gyro (small compared to the ~0.1-0.4 rad/s rates this
    // maneuver commands) and ~0.3 m/s^2 accel (~3% of g).
    let setpoint = AttitudeSetpoint { roll: 0.2, pitch: 0.1, yaw: 0.0, throttle: 0.5 };
    let history = run_scenario(
        "sitl_sensor_noise_robustness.csv",
        3.0,
        move |_t| setpoint,
        |_t| Vec3::zero(),
        |_t| false,
        |rng| {
            let gyro_noise = Vec3::new(rng.next_signed_f32(), rng.next_signed_f32(), rng.next_signed_f32()).scale(0.01);
            let accel_noise = Vec3::new(rng.next_signed_f32(), rng.next_signed_f32(), rng.next_signed_f32()).scale(0.3);
            (gyro_noise, accel_noise)
        },
    );

    // Looser tolerance than the noiseless scenarios (noise means it never
    // settles to an exact point), and averaged rather than max-in-window
    // since a noisy signal legitimately has occasional larger excursions -
    // what matters is the *average* stays near the setpoint, not that every
    // single sample does.
    let tail = tail_window(&history, SETTLE_WINDOW_S);
    let avg_err: f32 = {
        let sum: f32 = tail
            .iter()
            .map(|r| {
                let e = Vec3::new(r.attitude.x - setpoint.roll, r.attitude.y - setpoint.pitch, r.attitude.z - setpoint.yaw);
                max_abs_axis(e)
            })
            .sum();
        sum / tail.len() as f32
    };
    let finite = all_finite(&history);
    let passed = avg_err < 0.1 && finite;
    ScenarioResult {
        name: "sensor_noise_robustness",
        passed,
        detail: format!("mean settled attitude error under noise = {avg_err:.4} rad, all_finite={finite}"),
    }
}

/// Drives 3 independent boards' attitude estimation (separate `Plant` +
/// `MadgwickFilter` pairs, one shared "true" trajectory but independent
/// per-board sensor bias/noise) through the real production `TmrVoter`, to
/// exercise it against SITL-realistic synthetic data instead of only the
/// hand-crafted numeric arrays `flight::redundancy::voter`'s own unit tests
/// use. Board 2 gets a large injected bias starting at t=1.0s (a stuck/faulty
/// IMU), and the voter must flag it as the outlier once its estimate has
/// diverged enough to fall outside tolerance, without ever corrupting the
/// 2-of-3 majority value used for control.
pub fn scenario_tmr_voter_fault_detection() -> ScenarioResult {
    let dt = 1.0 / IMU_RATE_HZ;
    let duration_s = 2.0;
    let total_ticks = (duration_s / dt) as u32;
    let fault_start_s = 1.0;
    let tolerance = 0.05; // quaternion-component tolerance, matching common::can_frames' intended usage

    // Shared true trajectory: constant slow roll, driven kinematically (no
    // motor/plant dynamics needed here - this scenario is about the voter,
    // not the control chain).
    let true_rate = Vec3::new(0.3, 0.0, 0.0);
    let mut true_q = Quat::identity();

    let mut boards = [MadgwickFilter::new(0.05), MadgwickFilter::new(0.05), MadgwickFilter::new(0.05)];
    let mut rng = Xorshift32::new(0xFACADE);

    let mut correctly_flagged_after_fault = true;
    let mut ever_flagged_before_fault = false;
    let mut majority_value_stayed_accurate = true;
    const G: f32 = 9.80665;

    for tick in 0..total_ticks {
        let t = tick as f32 * dt;

        // Advance true state.
        let omega_quat = Quat::new(0.0, true_rate.x, true_rate.y, true_rate.z);
        let q_dot = true_q.mul(&omega_quat);
        true_q = Quat::new(
            true_q.w + 0.5 * q_dot.w * dt,
            true_q.x + 0.5 * q_dot.x * dt,
            true_q.y + 0.5 * q_dot.y * dt,
            true_q.z + 0.5 * q_dot.z * dt,
        );
        true_q.normalize();
        let true_accel = true_q.conjugate().rotate(Vec3::new(0.0, 0.0, G));

        // Board 2 develops a large stuck-gyro fault after fault_start_s: it
        // stops integrating real motion and just drifts on noise, so its
        // quaternion estimate diverges from the true (and boards 0/1's)
        // attitude.
        for (i, board) in boards.iter_mut().enumerate() {
            let small_noise = Vec3::new(rng.next_signed_f32(), rng.next_signed_f32(), rng.next_signed_f32()).scale(0.005);
            if i == 2 && t >= fault_start_s {
                // Stuck/faulty gyro: reports near-zero rate regardless of true motion.
                board.update(small_noise, Vec3::new(0.0, 0.0, G), dt);
            } else {
                board.update(true_rate + small_noise, true_accel, dt);
            }
        }

        let samples: [Option<[f32; 4]>; 3] = std::array::from_fn(|i| {
            let q = boards[i].get_quaternion();
            Some([q.w, q.x, q.y, q.z])
        });

        let result = TmrVoter::vote_sensor(samples, tolerance);
        match result {
            VoteResult::Majority { value, outlier_board } => {
                if t >= fault_start_s + 0.3 {
                    // Give it 0.3s after the fault starts to actually
                    // diverge past tolerance before requiring detection.
                    if outlier_board != 2 {
                        correctly_flagged_after_fault = false;
                    }
                    let true_arr = [true_q.w, true_q.x, true_q.y, true_q.z];
                    let err = (0..4).map(|i| (value[i] - true_arr[i]).abs()).fold(0.0f32, f32::max);
                    if err > 0.1 {
                        majority_value_stayed_accurate = false;
                    }
                } else if t < fault_start_s {
                    ever_flagged_before_fault = true;
                }
            }
            VoteResult::Agreed(_) => {}
            VoteResult::NoConsensus | VoteResult::InsufficientData => {
                if t >= fault_start_s + 0.3 {
                    correctly_flagged_after_fault = false;
                }
            }
        }
    }

    let passed = correctly_flagged_after_fault && !ever_flagged_before_fault && majority_value_stayed_accurate;
    ScenarioResult {
        name: "tmr_voter_fault_detection",
        passed,
        detail: format!(
            "correctly_flagged_board_2_after_fault={correctly_flagged_after_fault}, no_false_positive_before_fault={}, majority_value_stayed_accurate={majority_value_stayed_accurate}",
            !ever_flagged_before_fault
        ),
    }
}

/// End-to-end boot sequence: gyro bias auto-calibration (stationary vehicle)
/// must complete before `ArmingFsm` will accept an arm request, mirroring
/// `firmware/src/main.rs::init()`'s PBIT sequence - these two subsystems are
/// each unit-tested in isolation (`flight::calibration::gyro_bias`,
/// `flight::arming`) but never previously driven together against a
/// simulated timeline.
pub fn scenario_boot_sequence() -> ScenarioResult {
    let samples_needed = 500; // 0.5s @ 1kHz
    let mut estimator = GyroBiasEstimator::new(samples_needed, 0.02);
    let mut rng = Xorshift32::new(0x600D_B007);

    // Stationary vehicle: true rate is zero, tiny sensor noise only.
    let mut cal_state = CalState::InProgress;
    let mut cal_ticks = 0u32;
    while cal_state == CalState::InProgress && cal_ticks < samples_needed * 2 {
        let noisy_gyro = Vec3::new(rng.next_signed_f32(), rng.next_signed_f32(), rng.next_signed_f32()).scale(0.005);
        cal_state = estimator.accumulate(noisy_gyro);
        cal_ticks += 1;
    }
    let calibration_succeeded = cal_state == CalState::Success;

    // Arming FSM: bit_passed is gated on calibration having succeeded here
    // (a SITL stand-in for the real PBIT sequence's several checks, of
    // which gyro calibration is one - see firmware/src/main.rs::init()).
    let mut fsm = ArmingFsm::new();
    let checks = PreArmChecks { bit_passed: calibration_succeeded, attitude_valid: true };
    let control_dt = 1.0 / CONTROL_RATE_HZ;
    let ticks_needed = (0.5 / control_dt) as u32 + 2; // ARM_HOLD_SECONDS margin

    let mut armed_too_early = false;
    let mut final_state = ArmState::Disarmed;
    for i in 0..ticks_needed {
        final_state = fsm.update(ArmRequest::Arm, checks, control_dt);
        // Must never jump straight to Armed on tick 0 - the debounce hold is
        // the entire point of `Arming`'s existence.
        if i == 0 && final_state == ArmState::Armed {
            armed_too_early = true;
        }
    }

    let reached_armed = final_state == ArmState::Armed;
    let passed = calibration_succeeded && !armed_too_early && reached_armed && fsm.output_allowed();
    ScenarioResult {
        name: "boot_sequence",
        passed,
        detail: format!(
            "gyro_cal={calibration_succeeded:?} after {cal_ticks} samples, armed_too_early={armed_too_early}, reached_armed={reached_armed}"
        ),
    }
}

pub fn all_scenarios() -> Vec<ScenarioResult> {
    vec![
        scenario_step_response(),
        scenario_disturbance_rejection(),
        scenario_mpc_failover(),
        scenario_combined_maneuver(),
        scenario_sensor_noise_robustness(),
        scenario_tmr_voter_fault_detection(),
        scenario_boot_sequence(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    macro_rules! scenario_test {
        ($fn_name:ident, $scenario:expr) => {
            #[test]
            fn $fn_name() {
                let result = $scenario;
                assert!(result.passed, "{}: {}", result.name, result.detail);
            }
        };
    }

    scenario_test!(step_response, scenario_step_response());
    scenario_test!(disturbance_rejection, scenario_disturbance_rejection());
    scenario_test!(mpc_failover, scenario_mpc_failover());
    scenario_test!(combined_maneuver, scenario_combined_maneuver());
    scenario_test!(sensor_noise_robustness, scenario_sensor_noise_robustness());
    scenario_test!(tmr_voter_fault_detection, scenario_tmr_voter_fault_detection());
    scenario_test!(boot_sequence, scenario_boot_sequence());
}
