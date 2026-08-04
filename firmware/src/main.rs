//! JFOX FCU - Bare-metal Rust Flight Controller
//!
//! This is the main firmware application for the JFOX FCU, targeting the PX4 FMUv2
//! board family - PX4FMUv2.4.5 and Pixhawk 2.4.8 are the same reference design.
//! It implements a real-time flight control system using RTIC (Real-Time Interrupt-driven Concurrency).
//!
//! Hardware:
//! - STM32F427VIT6 @ 168MHz ("FMU"; this firmware runs FMU-only, see bsp::pins module docs)
//! - MPU-6000 IMU @ 1kHz
//! - MS5611 Barometer
//! - 4x PWM outputs for quad-X motors (FMU-CH1..CH4, TIM1)
//!
//! Tasks:
//! - IMU sampling @ 1kHz (priority 3)
//! - Sensor fusion @ 1kHz (priority 3)
//! - Control loop @ 500Hz (priority 2)
//! - Motor output @ 400Hz (priority 1)
//! - Heartbeat LED @ 1Hz, on-demand IBIT status re-check (priority 0)
//!
//! Boot sequence runs a power-on Built-In Test (PBIT, see `flight::bit`):
//! IMU communication, gyro bias auto-calibration (fresh every boot, no
//! persistent storage needed - see `flight::calibration::gyro_bias`), an
//! FM25V01 FRAM read/write self-test, a stored accel-calibration load (falls
//! back to an identity/no-op correction if none is stored - see
//! `flight::calibration::accel_cal`), a CCM memory check, and an arming FSM
//! sanity check. A failed PBIT blocks arming for the rest of the boot (see
//! `PreArmChecks::bit_passed`) without blocking boot itself.
//!
//! No RC/telemetry command input exists yet (see flight::arming module docs) - the
//! arm request source and attitude setpoint are placeholders pending a command link.

#![no_std]
#![no_main]

use panic_probe as _;
use defmt_rtt as _;

use defmt::{info, warn, error};
use rtic_monotonics::systick::prelude::*;
use stm32f4::stm32f427 as pac;

use bsp::clocks::Clocks;
use hal::{gpio::*, spi::*, pwm::Pwm, dwt::Dwt};
use drivers::{Mpu6000, Fm25v01};
use math::{Vec3, Quat, Mat3};
use flight::{
    MadgwickFilter,
    arming::{ArmingFsm, ArmRequest, PreArmChecks},
    mixer::{Mixer, FrameType},
    stabilize::{StabilizeController, StabilizeGains, AxisGains, AttitudeSetpoint},
    mpc::{MpcController, model::RateModel},
    adaptive::{mrac::ParamEstimator, l1::L1Filter},
    redundancy::{PathSelector, ControlPath},
    calibration::{GyroBiasEstimator, CalState, AccelCalibration, CalibrationRecord},
    calibration::storage::{CALIBRATION_RECORD_ADDR, FRAM_SELFTEST_SCRATCH_ADDR, RECORD_SIZE},
    bit::{BitReport, BitTestId},
};

// Task rates
const IMU_RATE_HZ: u32 = 1000;
const CONTROL_RATE_HZ: u32 = 500;
const MOTOR_RATE_HZ: u32 = 400;

// Calibration - placeholder values pending real-hardware characterization.
const GYRO_CAL_SAMPLES: u32 = 1000; // ~1s of samples at the natural SPI read rate during boot
const GYRO_CAL_MAX_STDDEV: f32 = 0.05; // rad/s; "was the vehicle actually stationary" threshold

// MPC/adaptive tuning - all placeholder values pending real-hardware
// characterization (see default_stabilize_gains' equivalent note below).
const MPC_ADMM_MAX_ITERS: usize = 10; // warm-started every tick; measure via Dwt before raising
const MPC_RICCATI_ITERS_INIT: usize = 50; // one-time cost at init(), can afford more
const MPC_RICCATI_ITERS_UPDATE: usize = 20; // recurring cost inside control_task, kept smaller
const MPC_RATE_BOUNDS: (f32, f32) = (-1.0, 1.0); // matches MixerInput's roll/pitch/yaw range
const PARAM_ESTIMATOR_DECIM_TICKS: u32 = 10; // 500Hz / 10 = 50Hz decimated update rate
const DWT_LOG_DECIM_TICKS: u32 = 500; // ~1Hz at 500Hz control rate

fn default_rate_model() -> RateModel {
    // Placeholder physical parameters - not yet validated on hardware.
    RateModel::new(
        [1.0, 1.0, 1.0],  // damping (1/s)
        [8.0, 8.0, 4.0],  // control effectiveness (rad/s^2 per unit command); yaw authority typically lower
        1.0 / CONTROL_RATE_HZ as f32,
    )
}

fn default_mpc_controller() -> MpcController {
    let model = default_rate_model();
    let q = Mat3::from_diagonal([1.0, 1.0, 1.0]);
    let r = Mat3::from_diagonal([0.1, 0.1, 0.1]);
    MpcController::new(model, q, r, 1.0, MPC_RICCATI_ITERS_INIT)
        .expect("default MPC model/weights must be well-posed")
}

// SysTick-based monotonic timer, 1us/tick (covers both the millisecond delays
// used by imu/control/heartbeat tasks and the microsecond delay used by
// motor_task). 168MHz sysclk / 1_000_000 = 168, still an exact divisor.
rtic_monotonics::systick_monotonic!(Mono, 1_000_000);

fn default_stabilize_gains() -> StabilizeGains {
    // Placeholder tuning values - not yet validated on hardware.
    let angle_axis = AxisGains {
        att_kp: 4.5,
        att_ki: 0.0,
        att_kd: 0.0,
        att_limit: 3.0, // rad/s rate-setpoint ceiling
        rate_kp: 0.15,
        rate_ki: 0.02,
        rate_kd: 0.002,
        rate_limit: 1.0,
    };
    let yaw_axis = AxisGains {
        att_kp: 4.0,
        att_ki: 0.0,
        att_kd: 0.0,
        att_limit: 3.0,
        rate_kp: 0.2,
        rate_ki: 0.02,
        rate_kd: 0.0,
        rate_limit: 1.0,
    };
    StabilizeGains { roll: angle_axis, pitch: angle_axis, yaw: yaw_axis }
}

/// Quaternion sanity check for the arming pre-check: rejects NaN and any gross
/// deviation from unit length (a healthy, actively-normalized attitude estimate
/// should stay very close to 1.0).
fn is_attitude_valid(q: Quat) -> bool {
    let mag = q.magnitude();
    mag.is_finite() && (mag - 1.0).abs() < 0.05
}

#[rtic::app(device = pac, dispatchers = [EXTI0, EXTI1, EXTI2, EXTI3])]
mod app {
    use super::*;

    #[shared]
    struct Shared {
        /// Current attitude quaternion
        attitude: Quat,

        /// Angular rates from gyroscope (rad/s)
        gyro_rates: Vec3,

        /// Linear acceleration (m/s²)
        accel: Vec3,

        /// Armed state, published by control_task, consumed by motor_task
        armed: bool,

        /// Per-motor mixer output (0.0..=1.0), published by control_task
        motor_outputs: [f32; 4],

        /// Temperature (°C)
        temperature: f32,
    }

    #[local]
    struct Local {
        /// MPU-6000 IMU driver
        mpu6000: Mpu6000<Spi<1>, Pin<'C', 2, Output>>,

        /// Madgwick sensor fusion filter
        madgwick: MadgwickFilter,

        /// Gyro bias measured once at boot (see `init`'s BIT sequence),
        /// subtracted from every raw gyro reading in `imu_task`.
        gyro_bias: Vec3,

        /// Accel calibration loaded from FRAM at boot, or `identity()` if
        /// none was stored, applied to every raw accel reading in `imu_task`.
        accel_cal: AccelCalibration,

        /// Overall power-on Built-In Test result (feeds the arming pre-check)
        bit_passed: bool,

        /// Cascaded attitude+rate stabilizer
        stabilize: StabilizeController,

        /// Quad-X motor mixer
        mixer: Mixer,

        /// Arming state machine
        arming: ArmingFsm,

        /// Adaptive-MPC rate-loop controller (primary control path)
        mpc: MpcController,

        /// Online control-effectiveness estimator feeding `mpc`'s model
        param_estimator: ParamEstimator,

        /// Decimation counter for `param_estimator` (runs at CONTROL_RATE_HZ /
        /// PARAM_ESTIMATOR_DECIM_TICKS, not every control tick)
        param_estimator_counter: u32,

        /// L1 disturbance filter between the MPC's output and the mixer
        l1: L1Filter,

        /// Chooses MPC vs. PID-fallback output each tick
        path_selector: PathSelector,

        /// Decimation counter for periodic DWT cycle-count logging
        dwt_log_counter: u32,

        /// PWM driver for FMU-CH1..CH4 (TIM1)
        pwm: Pwm<1>,

        /// Status LED (FMU-LED_AMBER, PE12)
        led: Pin<'E', 12, Output>,
    }

    #[init]
    fn init(ctx: init::Context) -> (Shared, Local) {
        info!("JFOX FCU - Flight Controller Firmware");
        info!("Hardware: PX4 FMUv2 family - 2.4.5 / Pixhawk 2.4.8 (STM32F427VIT6, FMU-only)");
        info!("Build: {}", env!("CARGO_PKG_VERSION"));

        // Configure system clocks to 168MHz (see bsp::clocks for why not 180)
        let clocks = unsafe { Clocks::configure() };
        info!("System clock configured: {}MHz", clocks.sysclk() / 1_000_000);

        // Initialize SysTick monotonic timer @ 1MHz (1us/tick)
        Mono::start(ctx.core.SYST, clocks.sysclk());

        // Status LED: FMU-LED_AMBER (PE12), a dedicated GPIO independent of any
        // SPI/PWM/CAN pin (see bsp::pins module docs).
        let led = unsafe { Pin::<'E', 12, Output>::new().into_output() };

        // PWM: FMU-CH1..CH4 on TIM1 (PE14/PE13/PE11/PE9, AF1).
        info!("Initializing PWM (FMU-CH1..CH4, TIM1)...");
        unsafe {
            let _ = Pin::<'E', 14, Alternate<1>>::new().into_alternate();
            let _ = Pin::<'E', 13, Alternate<1>>::new().into_alternate();
            let _ = Pin::<'E', 11, Alternate<1>>::new().into_alternate();
            let _ = Pin::<'E', 9, Alternate<1>>::new().into_alternate();
        }
        let mut pwm = unsafe { Pwm::<1>::new() };
        pwm.init(clocks.tim_pclk2(), MOTOR_RATE_HZ);

        // Initialize SPI1 for MPU-6000 (SPI_INT bus: PA5/PA6/PA7, see bsp::pins).
        info!("Initializing SPI1 for MPU-6000...");
        let mut spi1 = unsafe { Spi::<1>::new() };
        // SPI1 on APB2 (84MHz), divide by 16 => 5.25MHz (MPU-6000 max = 20MHz)
        spi1.init_mode3(3);

        // Initialize MPU-6000 IMU
        info!("Initializing MPU-6000 IMU...");
        let mpu_cs = unsafe { Pin::<'C', 2, Output>::new().into_output() };
        let mut mpu6000 = Mpu6000::new(spi1, mpu_cs);
        let imu_ok = match mpu6000.init() {
            Ok(variant) => {
                info!("IMU initialized: {}", variant.name());
                if !variant.is_hardware_verified() {
                    // Accepted on register compatibility with the MPU-6000, not
                    // on evidence. Worth saying out loud in the flight
                    // application specifically.
                    warn!(
                        "IMU {} accepted on datasheet compatibility, never verified on silicon by this project",
                        variant.name()
                    );
                }
                true
            }
            Err(()) => {
                error!("IMU initialization failed! Arming will be refused.");
                false
            }
        };

        // ==== Power-on Built-In Test (PBIT) ====
        // Runs once, here, with exclusive access to every peripheral before
        // any task is spawned. See `flight::bit` module docs for the
        // PBIT/IBIT distinction (`bit_task`, defined below, is IBIT).
        let mut bit_report = BitReport::new();
        bit_report.record(BitTestId::ImuCommunication, imu_ok);

        // Gyro bias auto-calibration: assumes the vehicle is stationary for
        // this window (the standard assumption every flight controller
        // makes - see flight::calibration::gyro_bias module docs). Not
        // stored persistently; re-measured fresh every boot on purpose.
        let gyro_bias = if imu_ok {
            info!("Calibrating gyro bias ({} samples, keep the vehicle stationary)...", GYRO_CAL_SAMPLES);
            let mut estimator = GyroBiasEstimator::new(GYRO_CAL_SAMPLES, GYRO_CAL_MAX_STDDEV);
            let mut state = CalState::InProgress;
            while state == CalState::InProgress {
                match mpu6000.read_data() {
                    Ok(sample) => state = estimator.accumulate(sample.gyro),
                    Err(()) => {
                        warn!("Gyro cal: IMU read failed mid-calibration, aborting");
                        break;
                    }
                }
            }
            match state {
                CalState::Success => {
                    let b = estimator.bias();
                    info!("Gyro bias calibrated: ({}, {}, {}) rad/s", b.x, b.y, b.z);
                }
                CalState::Failed => {
                    error!("Gyro bias calibration FAILED - vehicle was not stationary. Using zero bias; arming refused until a successful BIT.");
                }
                CalState::InProgress => {
                    error!("Gyro bias calibration aborted (IMU read failure). Using zero bias; arming refused until a successful BIT.");
                }
            }
            bit_report.record(BitTestId::GyroCalibration, state == CalState::Success);
            estimator.bias()
        } else {
            bit_report.record(BitTestId::GyroCalibration, false);
            Vec3::zero()
        };

        // Initialize Madgwick filter
        // Beta = 0.041 is tuned for ~100Hz, we're running at 1kHz so use lower value
        let madgwick = MadgwickFilter::new(0.01);
        info!("Madgwick filter initialized (beta=0.01)");

        // Initialize SPI2 for FRAM (PB13/PB14/PB15, CS on PD10, see bsp::pins).
        info!("Initializing SPI2 for FM25V01 FRAM...");
        unsafe {
            let _ = Pin::<'B', 13, Alternate<5>>::new().into_alternate();
            let _ = Pin::<'B', 14, Alternate<5>>::new().into_alternate();
            let _ = Pin::<'B', 15, Alternate<5>>::new().into_alternate();
        }
        let mut spi2 = unsafe { Spi::<2>::new() };
        spi2.init_mode0(3);
        let fram_cs = unsafe { Pin::<'D', 10, Output>::new().into_output() };
        let mut fram = Fm25v01::new(spi2, fram_cs);

        let fram_ok = match fram.self_test(FRAM_SELFTEST_SCRATCH_ADDR) {
            Ok(true) => {
                info!("FRAM self-test passed");
                true
            }
            Ok(false) => {
                error!("FRAM self-test FAILED (readback mismatch)");
                false
            }
            Err(()) => {
                error!("FRAM self-test FAILED (SPI error)");
                false
            }
        };
        bit_report.record(BitTestId::FramSelfTest, fram_ok);

        // Load a stored accel calibration if one exists and validates; a
        // missing/corrupt/blank record is not a BIT failure by itself (the
        // vehicle still boots and flies with an uncalibrated-but-safe
        // identity correction) - only a bad FRAM chip (fram_ok == false) is.
        let accel_cal = if fram_ok {
            let mut record_bytes = [0u8; RECORD_SIZE];
            match fram.read(CALIBRATION_RECORD_ADDR, &mut record_bytes) {
                Ok(()) => match CalibrationRecord::from_bytes(&record_bytes) {
                    Some(record) => {
                        info!("Loaded stored accel calibration from FRAM");
                        record.accel
                    }
                    None => {
                        warn!("No valid accel calibration stored (blank or corrupt) - using identity (uncalibrated)");
                        AccelCalibration::identity()
                    }
                },
                Err(()) => {
                    warn!("FRAM read failed - using identity accel calibration");
                    AccelCalibration::identity()
                }
            }
        } else {
            AccelCalibration::identity()
        };

        // CCM (core-coupled memory) write/readback sanity check. Uses
        // addr_of_mut! rather than `&CCM_REGION_MARKER as *const _ as *mut _`
        // deliberately: deriving a raw pointer through a shared reference to
        // a non-`mut` static and then writing through it is unsound (the
        // compiler is entitled to assume the static's value never changes).
        let ccm_ok = unsafe {
            let ptr = core::ptr::addr_of_mut!(CCM_REGION_MARKER);
            ptr.write_volatile(0xDEAD_BEEF);
            ptr.read_volatile() == 0xDEAD_BEEF
        };
        bit_report.record(BitTestId::CcmMemory, ccm_ok);

        let stabilize = StabilizeController::new(default_stabilize_gains());
        let mixer = Mixer::new(FrameType::QuadX);
        let arming = ArmingFsm::new();
        bit_report.record(BitTestId::ArmingFsmInitialState, arming.state() == flight::arming::ArmState::Disarmed);
        info!("Stabilizer, mixer, and arming FSM initialized");

        let bit_passed = bit_report.all_passed();
        if bit_passed {
            info!("Power-on BIT: ALL TESTS PASSED");
        } else {
            error!("Power-on BIT: FAILURE(S) DETECTED - arming will be refused until resolved");
            for failed in bit_report.failed_tests() {
                error!("  FAILED: {:?}", failed);
            }
        }

        // Adaptive-MPC path: MPC core + online effectiveness estimator + L1
        // disturbance filter + PID-fallback selector.
        let mpc = default_mpc_controller();
        let param_estimator = ParamEstimator::new(Vec3::new(8.0, 8.0, 4.0), 50.0, 0.995);
        // adaptation_gain=5.0: empirically chosen via SITL (see sitl/README.md),
        // not the originally-hardcoded 30.0. At 30.0, SITL's nonlinear plant
        // model (deliberately different from this filter's internal linear
        // model - see flight::mpc::model::RateModel's doc comment) produces a
        // small but persistent one-step prediction-error residual every tick;
        // amplified 30x and only lightly damped by a 10Hz LPF at 500Hz, that
        // residual closed a near-Nyquist limit cycle - motor commands
        // chattered full-scale (0.0<->1.0) every tick even at a fully
        // converged, undisturbed hover, despite the attitude *estimate*
        // looking converged (the oscillation averages out in position, not in
        // the actuator commands themselves). SITL testing at gain=10 still
        // showed the same chatter; gain=5 was the first value with clean,
        // settled motor output across all three SITL scenarios, so 5.0 is
        // used here with some margin below the empirically-found instability
        // threshold, not merely "smaller than 30."
        let l1 = L1Filter::new(10.0, CONTROL_RATE_HZ as f32, 5.0);
        let path_selector = PathSelector::new();
        info!("Adaptive-MPC controller, parameter estimator, and L1 filter initialized");

        // DWT cycle counter, for measuring actual control_task headroom on
        // real hardware (see MPC_ADMM_MAX_ITERS' doc comment).
        unsafe { Dwt::enable() };

        // Spawn periodic tasks
        imu_task::spawn().ok();
        control_task::spawn().ok();
        motor_task::spawn().ok();
        heartbeat_task::spawn().ok();

        info!("==================================================");
        info!("Initialization complete - entering main loop");
        info!("==================================================");

        (
            Shared {
                attitude: Quat::identity(),
                gyro_rates: Vec3::zero(),
                accel: Vec3::zero(),
                armed: false,
                motor_outputs: [0.0; 4],
                temperature: 0.0,
            },
            Local {
                mpu6000,
                madgwick,
                gyro_bias,
                accel_cal,
                bit_passed,
                stabilize,
                mixer,
                arming,
                mpc,
                param_estimator,
                param_estimator_counter: 0,
                l1,
                path_selector,
                dwt_log_counter: 0,
                pwm,
                led,
            },
        )
    }

    /// IMU sampling and sensor fusion @ 1kHz
    ///
    /// This task runs at the highest priority to ensure timely sensor readings.
    /// It reads accelerometer and gyroscope data from the MPU-6000, applies the
    /// boot-time gyro bias and accel calibration (see `init`'s BIT sequence and
    /// `flight::calibration`), and updates the Madgwick filter to estimate
    /// attitude.
    #[task(priority = 3, local = [mpu6000, madgwick, gyro_bias, accel_cal, sample_count: u32 = 0], shared = [attitude, gyro_rates, accel, temperature])]
    async fn imu_task(mut ctx: imu_task::Context) {
        loop {
            // Read IMU data
            match ctx.local.mpu6000.read_data() {
                Ok(imu_data) => {
                    let corrected_gyro = imu_data.gyro - *ctx.local.gyro_bias;
                    let corrected_accel = ctx.local.accel_cal.apply(imu_data.accel);

                    // Update Madgwick filter with corrected sensor data
                    ctx.local.madgwick.update(
                        corrected_gyro,
                        corrected_accel,
                        1.0 / IMU_RATE_HZ as f32,
                    );

                    // Get current attitude
                    let attitude = ctx.local.madgwick.get_quaternion();

                    // Update shared state
                    (
                        &mut ctx.shared.attitude,
                        &mut ctx.shared.gyro_rates,
                        &mut ctx.shared.accel,
                        &mut ctx.shared.temperature,
                    )
                        .lock(|att, gyro, acc, temp| {
                            *att = attitude;
                            *gyro = corrected_gyro;
                            *acc = corrected_accel;
                            *temp = imu_data.temp;
                        });

                    // Log every 1000 samples (1Hz)
                    *ctx.local.sample_count += 1;
                    if *ctx.local.sample_count >= IMU_RATE_HZ {
                        let (roll, pitch, yaw) = attitude.to_euler();
                        info!(
                            "Attitude: roll={}° pitch={}° yaw={}° temp={}°C",
                            roll.to_degrees(),
                            pitch.to_degrees(),
                            yaw.to_degrees(),
                            imu_data.temp
                        );
                        *ctx.local.sample_count = 0;
                    }
                }
                Err(()) => {
                    warn!("Failed to read IMU data");
                }
            }

            // Wait 1ms (1kHz update rate)
            Mono::delay(1_u32.millis()).await;
        }
    }

    /// Attitude + rate control loop @ 500Hz
    ///
    /// Runs the arming state machine every tick (so a fault or explicit disarm
    /// is never delayed). While armed: the outer attitude loop runs once
    /// (shared by both inner strategies, since it owns integrator state that
    /// must not be advanced twice per tick); the adaptive-MPC path and the
    /// PID-fallback inner loop are *both* computed every tick regardless of
    /// which one is selected, so the fallback is never stale/cold at the
    /// moment a failover actually needs it; `PathSelector` then picks the
    /// output that reaches `L1Filter` (MPC path only) and the mixer.
    /// `ParamEstimator` runs decimated (~50Hz) to keep the MPC's internal
    /// model matched to the airframe. Integrators/filters are kept reset the
    /// whole time the vehicle is not armed.
    #[task(priority = 2, local = [
        bit_passed, stabilize, mixer, arming, mpc, param_estimator,
        param_estimator_counter, l1, path_selector, dwt_log_counter,
    ], shared = [attitude, gyro_rates, armed, motor_outputs])]
    async fn control_task(mut ctx: control_task::Context) {
        loop {
            let dt = 1.0 / CONTROL_RATE_HZ as f32;
            let cycle_start = Dwt::cycle_count();

            let (attitude, gyro) = (&mut ctx.shared.attitude, &mut ctx.shared.gyro_rates)
                .lock(|att, gyro| (*att, *gyro));

            let checks = PreArmChecks {
                bit_passed: *ctx.local.bit_passed,
                attitude_valid: is_attitude_valid(attitude),
            };

            // TODO: source a real arm request and attitude/throttle setpoint from
            // an RC or telemetry command link once one exists (see flight::arming
            // and this module's doc comment). Until then the vehicle never arms.
            let request = ArmRequest::None;
            let setpoint = AttitudeSetpoint::default();

            ctx.local.arming.update(request, checks, dt);
            let armed = ctx.local.arming.output_allowed();

            let motor_outputs = if armed {
                let rate_setpoint = ctx.local.stabilize.outer_loop(attitude, setpoint, dt);

                let mpc_cmd = ctx.local.mpc.solve(gyro, rate_setpoint, MPC_RATE_BOUNDS, MPC_ADMM_MAX_ITERS);
                let mpc_valid = mpc_cmd.x.is_finite() && mpc_cmd.y.is_finite() && mpc_cmd.z.is_finite();

                // PID fallback: computed unconditionally, every tick, so its
                // integrator state is never stale/cold at the moment a
                // failover actually needs it.
                let pid_mixer_input = ctx.local.stabilize.inner_loop(rate_setpoint, gyro, setpoint.throttle, dt);
                let pid_cmd = Vec3::new(pid_mixer_input.roll, pid_mixer_input.pitch, pid_mixer_input.yaw);

                let path = ctx.local.path_selector.select(mpc_valid);
                let rate_cmd = match path {
                    ControlPath::AdaptiveMpc => mpc_cmd,
                    ControlPath::PidFallback => pid_cmd,
                };

                // L1 augmentation only applies on the MPC path - the PID
                // fallback is deliberately the simple, unaugmented path.
                let augmented_cmd = match path {
                    ControlPath::AdaptiveMpc => ctx.local.l1.update(gyro, rate_cmd, ctx.local.mpc.model(), dt),
                    ControlPath::PidFallback => {
                        ctx.local.l1.reset();
                        rate_cmd
                    }
                };

                // Decimated online effectiveness estimation, feeding the MPC model.
                *ctx.local.param_estimator_counter += 1;
                if *ctx.local.param_estimator_counter >= PARAM_ESTIMATOR_DECIM_TICKS {
                    let decim_dt = PARAM_ESTIMATOR_DECIM_TICKS as f32 * dt;
                    *ctx.local.param_estimator_counter = 0;
                    if let Some(effectiveness) = ctx.local.param_estimator.update(gyro, rate_cmd, decim_dt) {
                        let damping = [1.0, 1.0, 1.0]; // damping is not currently estimated, only effectiveness
                        if let Err(e) = ctx.local.mpc.update_model(damping, [effectiveness.x, effectiveness.y, effectiveness.z], MPC_RICCATI_ITERS_UPDATE) {
                            warn!("MPC model update rejected: {:?}", e);
                        }
                    }
                }

                let mixer_input = flight::mixer::MixerInput {
                    roll: augmented_cmd.x,
                    pitch: augmented_cmd.y,
                    yaw: augmented_cmd.z,
                    throttle: setpoint.throttle,
                };
                ctx.local.mixer.mix(mixer_input)
            } else {
                ctx.local.stabilize.reset();
                ctx.local.mpc.reset();
                ctx.local.l1.reset();
                [0.0; 4]
            };

            (&mut ctx.shared.armed, &mut ctx.shared.motor_outputs).lock(|a, m| {
                *a = armed;
                *m = motor_outputs;
            });

            // Periodic (~1Hz) control-loop timing log - the real headroom
            // measurement MPC_ADMM_MAX_ITERS should eventually be sized from.
            *ctx.local.dwt_log_counter += 1;
            if *ctx.local.dwt_log_counter >= DWT_LOG_DECIM_TICKS {
                *ctx.local.dwt_log_counter = 0;
                let elapsed_cycles = Dwt::elapsed_since(cycle_start);
                // Derived from bsp rather than a literal so the microsecond
                // figure stays correct if the clock tree moves again.
                const CYCLES_PER_US: u32 = bsp::clocks::HCLK_FREQ_HZ / 1_000_000;
                info!(
                    "control_task: {} cycles ({}us @ {}MHz)",
                    elapsed_cycles,
                    elapsed_cycles / CYCLES_PER_US,
                    bsp::clocks::HCLK_FREQ_HZ / 1_000_000
                );
            }

            // Wait 2ms (500Hz update rate)
            Mono::delay(2_u32.millis()).await;
        }
    }

    /// Motor output @ 400Hz
    ///
    /// Applies the mixer output computed by control_task to PWM. Always writes
    /// an explicit 0 duty cycle while disarmed, rather than leaving whatever
    /// value was last set.
    #[task(priority = 1, local = [pwm], shared = [armed, motor_outputs])]
    async fn motor_task(mut ctx: motor_task::Context) {
        loop {
            let (armed, outputs) = (&mut ctx.shared.armed, &mut ctx.shared.motor_outputs)
                .lock(|a, m| (*a, *m));

            for (i, &duty) in outputs.iter().enumerate() {
                let channel = (i as u8) + 1;
                if armed {
                    ctx.local.pwm.set_channel_duty(channel, duty);
                } else {
                    ctx.local.pwm.set_channel_duty(channel, 0.0);
                }
            }

            // Wait 2.5ms (400Hz update rate)
            Mono::delay(2500_u32.micros()).await;
        }
    }

    /// Heartbeat task @ 1Hz
    ///
    /// Provides visual feedback that the system is running.
    #[task(priority = 0, local = [led, state: bool = false])]
    async fn heartbeat_task(ctx: heartbeat_task::Context) {
        loop {
            *ctx.local.state = !*ctx.local.state;

            if *ctx.local.state {
                ctx.local.led.set_high();
            } else {
                ctx.local.led.set_low();
            }

            // Wait 500ms
            Mono::delay(500_u32.millis()).await;
        }
    }

    /// On-demand status re-check (**IBIT** - Initiated BIT), distinct from
    /// the power-on BIT (**PBIT**) run once in `init` - see `flight::bit`
    /// module docs. Reports currently-tracked health/state (arming FSM
    /// state, attitude validity, armed status) rather than re-running
    /// invasive SPI transactions against peripherals `imu_task` owns
    /// continuously (re-doing e.g. the FRAM self-test here concurrently with
    /// `imu_task`'s/`control_task`'s hardware access would need those
    /// peripherals turned into shared, lock-arbitrated resources - real
    /// future work, not done here).
    ///
    /// Not spawned anywhere yet: there is no command link to trigger it from
    /// (see `flight::arming`'s module docs for the same gap). Call
    /// `bit_task::spawn()` once one exists - e.g. from a future UART/CAN
    /// command handler - to let a technician request a status readout on
    /// demand without rebooting the board.
    #[task(priority = 0, shared = [attitude, armed])]
    async fn bit_task(mut ctx: bit_task::Context) {
        let (attitude, armed) = (&mut ctx.shared.attitude, &mut ctx.shared.armed).lock(|a, b| (*a, *b));
        info!(
            "IBIT status: armed={}, attitude_valid={}",
            armed,
            is_attitude_valid(attitude)
        );
    }

}

/// Write/readback-tested by the power-on BIT's CCM memory check (see `init`)
/// to prove the `.ccmram` linker section (`ccmram.x`/`memory.x`) actually
/// places data in core-coupled memory at 0x1000_0000. Its source-level
/// initial value below is never actually loaded at boot (`.ccmram` is a
/// NOLOAD section - see `ccmram.x`'s doc comment), so the BIT check
/// deliberately writes-then-reads-back a known pattern rather than trusting
/// this value to be present at startup. Phase 2's MPC solver scratch
/// matrices remain the intended long-term occupant of this region.
#[used]
#[link_section = ".ccmram"]
static mut CCM_REGION_MARKER: u32 = 0xC1C1_C1C1;
