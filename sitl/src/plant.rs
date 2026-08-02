//! Independent 6-DOF rotational-dynamics "truth" model for SITL.
//!
//! Deliberately NOT the same model the controller uses internally
//! (`flight::mpc::model::RateModel`, a linearized/decoupled/no-motor-lag
//! approximation) - reusing that here would make every test trivially pass by
//! construction. This model has full nonlinear gyroscopic coupling
//! (`omega x (I*omega)`), first-order motor lag, and torque-gain constants
//! independent of what the controller assumes, so the simulation exercises
//! real model mismatch: exactly what `flight::adaptive::mrac` and
//! `flight::adaptive::l1` exist to handle.
//!
//! Torque-from-motors uses the same linear structure as
//! `flight::mixer::Mixer::mix`'s quad-X convention, inverted (this is a
//! stated simplification, not a claim of aerodynamic accuracy - real rotor
//! thrust/drag and arm geometry are not modeled).

use math::{Mat3, Quat, Vec3};

pub struct Plant {
    pub q: Quat,
    pub omega: Vec3, // body rates (truth), rad/s
    pub motor_thrust: [f32; 4], // lagged actual per-motor output, 0.0..=1.0
    inertia: Mat3,
    inertia_inv: Mat3,
    torque_gain: Vec3, // Nm-equivalent per unit thrust-difference, roll/pitch/yaw
    motor_tau: f32,    // motor first-order lag time constant (s)
}

fn quat_scale(q: Quat, s: f32) -> Quat {
    Quat::new(q.w * s, q.x * s, q.y * s, q.z * s)
}

fn quat_add(a: Quat, b: Quat) -> Quat {
    Quat::new(a.w + b.w, a.x + b.x, a.y + b.y, a.z + b.z)
}

impl Plant {
    pub fn new(inertia_diag: [f32; 3], torque_gain: Vec3, motor_tau: f32) -> Self {
        let inertia = Mat3::from_diagonal(inertia_diag);
        let inertia_inv = inertia.inverse().expect("nonzero diagonal inertia must be invertible");
        Self {
            q: Quat::identity(),
            omega: Vec3::zero(),
            motor_thrust: [0.0; 4],
            inertia,
            inertia_inv,
            torque_gain,
            motor_tau,
        }
    }

    /// Advance the plant by `dt` seconds given commanded motor duty cycles
    /// (0.0..=1.0, matching `flight::mixer`'s output) and an external
    /// disturbance torque (for injecting simulated gusts/impacts).
    pub fn step(&mut self, motor_cmd: [f32; 4], disturbance_torque: Vec3, dt: f32) {
        // First-order motor lag.
        let lag_alpha = (dt / self.motor_tau).min(1.0);
        for i in 0..4 {
            self.motor_thrust[i] += (motor_cmd[i] - self.motor_thrust[i]) * lag_alpha;
        }
        let t = &self.motor_thrust;

        // Inverted quad-X mixer convention (see module docs): M1=front-right,
        // M2=rear-left, M3=front-left, M4=rear-right.
        let roll_torque = self.torque_gain.x * (t[1] + t[2] - t[0] - t[3]);
        let pitch_torque = self.torque_gain.y * (t[0] + t[2] - t[1] - t[3]);
        let yaw_torque = self.torque_gain.z * (t[2] + t[3] - t[0] - t[1]);
        let torque = Vec3::new(roll_torque, pitch_torque, yaw_torque) + disturbance_torque;

        // Full nonlinear rigid-body rotational dynamics:
        // I*omega_dot = torque - omega x (I*omega)
        let i_omega = self.inertia.mul_vec(&[self.omega.x, self.omega.y, self.omega.z]);
        let i_omega_vec = Vec3::new(i_omega[0], i_omega[1], i_omega[2]);
        let gyroscopic = self.omega.cross(&i_omega_vec);
        let net = torque - gyroscopic;
        let omega_dot = self.inertia_inv.mul_vec(&[net.x, net.y, net.z]);
        self.omega = self.omega + Vec3::new(omega_dot[0], omega_dot[1], omega_dot[2]).scale(dt);

        // Quaternion kinematics: q_dot = 0.5 * q * [0, omega].
        let omega_quat = Quat::new(0.0, self.omega.x, self.omega.y, self.omega.z);
        let q_dot = quat_scale(self.q.mul(&omega_quat), 0.5);
        self.q = quat_add(self.q, quat_scale(q_dot, dt));
        self.q.normalize();
    }

    /// Synthesize noiseless gyro/accel readings from the current true state.
    /// No sensor noise is injected - a stated simplification (see sitl's
    /// top-level docs); this validates nominal control-chain behavior, not
    /// noise robustness.
    pub fn synthesize_imu(&self) -> (Vec3, Vec3) {
        const G: f32 = 9.80665;
        let gyro = self.omega;
        // Specific force in body frame: at level attitude (q=identity) this
        // is (0,0,+G), matching the convention `drivers::Mpu6000`/
        // `flight::sensor_fusion::MadgwickFilter` assume (stationary/level
        // accelerometer reads +g on Z).
        let accel = self.q.conjugate().rotate(Vec3::new(0.0, 0.0, G));
        (gyro, accel)
    }
}
