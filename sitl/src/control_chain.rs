//! Host-runnable mirror of `firmware/src/main.rs`'s `control_task` logic,
//! built from the exact same `flight::` production types (not reimplemented
//! or approximated) - only the RTIC scheduling/hardware-register parts are
//! left out, since those can't run on a host and aren't what this exists to
//! validate. Kept in sync with `control_task` by hand; if that logic changes,
//! this should change with it.

use math::{Mat3, Quat, Vec3};
use flight::{
    MadgwickFilter,
    mixer::{Mixer, FrameType, MixerInput},
    stabilize::{StabilizeController, StabilizeGains, AxisGains, AttitudeSetpoint},
    mpc::{MpcController, model::RateModel},
    adaptive::{mrac::ParamEstimator, l1::L1Filter},
    redundancy::{PathSelector, ControlPath},
};

pub const IMU_RATE_HZ: f32 = 1000.0;
pub const CONTROL_RATE_HZ: f32 = 500.0;
pub const MPC_ADMM_MAX_ITERS: usize = 10;
pub const MPC_RICCATI_ITERS_UPDATE: usize = 20;
pub const MPC_RATE_BOUNDS: (f32, f32) = (-1.0, 1.0);
pub const PARAM_ESTIMATOR_DECIM_TICKS: u32 = 10;

fn default_stabilize_gains() -> StabilizeGains {
    let angle_axis = AxisGains {
        att_kp: 4.5, att_ki: 0.0, att_kd: 0.0, att_limit: 3.0,
        rate_kp: 0.15, rate_ki: 0.02, rate_kd: 0.002, rate_limit: 1.0,
    };
    let yaw_axis = AxisGains {
        att_kp: 4.0, att_ki: 0.0, att_kd: 0.0, att_limit: 3.0,
        rate_kp: 0.2, rate_ki: 0.02, rate_kd: 0.0, rate_limit: 1.0,
    };
    StabilizeGains { roll: angle_axis, pitch: angle_axis, yaw: yaw_axis }
}

fn default_rate_model() -> RateModel {
    RateModel::new([1.0, 1.0, 1.0], [8.0, 8.0, 4.0], 1.0 / CONTROL_RATE_HZ)
}

fn default_mpc_controller() -> MpcController {
    let model = default_rate_model();
    let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
    let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);
    MpcController::new(model, q, r, 1.0, 50).expect("default MPC model/weights must be well-posed")
}

pub struct TickOutput {
    pub motor_outputs: [f32; 4],
    pub path: ControlPath,
    pub attitude_estimate: Quat,
    pub rate_setpoint: Vec3,
}

pub struct ControlChain {
    madgwick: MadgwickFilter,
    stabilize: StabilizeController,
    mixer: Mixer,
    mpc: MpcController,
    param_estimator: ParamEstimator,
    param_estimator_counter: u32,
    l1: L1Filter,
    path_selector: PathSelector,
}

impl ControlChain {
    pub fn new() -> Self {
        Self {
            madgwick: MadgwickFilter::new(0.01),
            stabilize: StabilizeController::new(default_stabilize_gains()),
            mixer: Mixer::new(FrameType::QuadX),
            mpc: default_mpc_controller(),
            param_estimator: ParamEstimator::new(Vec3::new(8.0, 8.0, 4.0), 50.0, 0.995),
            param_estimator_counter: 0,
            // See firmware/src/main.rs's matching L1Filter::new call for why
            // this is 5.0, not the originally-shipped 30.0 - that gain caused
            // full-scale motor chatter against this crate's nonlinear plant,
            // found by running these very scenarios.
            l1: L1Filter::new(10.0, CONTROL_RATE_HZ, 5.0),
            path_selector: PathSelector::new(),
        }
    }

    /// Sensor fusion step, at IMU_RATE_HZ - call this every simulated IMU tick.
    pub fn imu_tick(&mut self, gyro: Vec3, accel: Vec3) {
        self.madgwick.update(gyro, accel, 1.0 / IMU_RATE_HZ);
    }

    /// Control step, at CONTROL_RATE_HZ - call this every simulated control
    /// tick. `force_mpc_invalid` lets tests exercise the PID-fallback path
    /// deterministically (see `PathSelector`'s doc comment: it doesn't care
    /// *why* `mpc_valid` is false, so forcing it here is a legitimate way to
    /// fault-inject at this interface, not a reimplementation of the real
    /// validity check).
    pub fn control_tick(&mut self, gyro: Vec3, setpoint: AttitudeSetpoint, dt: f32, force_mpc_invalid: bool) -> TickOutput {
        let attitude = self.madgwick.get_quaternion();
        let rate_setpoint = self.stabilize.outer_loop(attitude, setpoint, dt);

        let mpc_cmd = self.mpc.solve(gyro, rate_setpoint, MPC_RATE_BOUNDS, MPC_ADMM_MAX_ITERS);
        let mpc_valid = !force_mpc_invalid && mpc_cmd.x.is_finite() && mpc_cmd.y.is_finite() && mpc_cmd.z.is_finite();

        let pid_mixer_input = self.stabilize.inner_loop(rate_setpoint, gyro, setpoint.throttle, dt);
        let pid_cmd = Vec3::new(pid_mixer_input.roll, pid_mixer_input.pitch, pid_mixer_input.yaw);

        let path = self.path_selector.select(mpc_valid);
        let rate_cmd = match path {
            ControlPath::AdaptiveMpc => mpc_cmd,
            ControlPath::PidFallback => pid_cmd,
        };

        let augmented_cmd = match path {
            ControlPath::AdaptiveMpc => self.l1.update(gyro, rate_cmd, self.mpc.model(), dt),
            ControlPath::PidFallback => {
                self.l1.reset();
                rate_cmd
            }
        };

        self.param_estimator_counter += 1;
        if self.param_estimator_counter >= PARAM_ESTIMATOR_DECIM_TICKS {
            let decim_dt = PARAM_ESTIMATOR_DECIM_TICKS as f32 * dt;
            self.param_estimator_counter = 0;
            if let Some(effectiveness) = self.param_estimator.update(gyro, rate_cmd, decim_dt) {
                let damping = [1.0, 1.0, 1.0];
                let _ = self.mpc.update_model(damping, [effectiveness.x, effectiveness.y, effectiveness.z], MPC_RICCATI_ITERS_UPDATE);
            }
        }

        let mixer_input = MixerInput { roll: augmented_cmd.x, pitch: augmented_cmd.y, yaw: augmented_cmd.z, throttle: setpoint.throttle };
        let motor_outputs = self.mixer.mix(mixer_input);

        TickOutput { motor_outputs, path, attitude_estimate: attitude, rate_setpoint }
    }
}

impl Default for ControlChain {
    fn default() -> Self {
        Self::new()
    }
}
