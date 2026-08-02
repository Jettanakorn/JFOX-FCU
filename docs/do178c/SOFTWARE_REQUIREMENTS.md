# JFOX-FCU Software Requirements

Aligned with DO-178C's software requirements process. **Important limitation,
stated plainly**: these requirements were written by reverse-documenting
already-implemented, already-tested code, not independently specified ahead
of implementation and then implemented against. That ordering matters to
DO-178C's actual intent (requirements-driven development, verified by tests
derived independently from the requirements) - what follows is honest
after-the-fact traceability, valuable for review and regression protection,
but not equivalent to a requirements-first process. See
`docs/do178c/README.md` for the full scope statement.

Each requirement has a unique ID. Verification method and evidence are in
`TRACEABILITY_MATRIX.md`, not repeated here, to keep the two documents from
drifting out of sync with each other.

---

## Arming (`flight::arming`)

- **REQ-ARM-001**: The arming state machine SHALL start in the `Disarmed` state.
- **REQ-ARM-002**: Motor output SHALL be disallowed (`output_allowed() == false`) in every state except `Armed`.
- **REQ-ARM-003**: A transition from `Disarmed` to `Arming` SHALL require both an `ArmRequest::Arm` request and `PreArmChecks::all_pass()` being true.
- **REQ-ARM-004**: A transition from `Arming` to `Armed` SHALL require `ArmRequest::Arm` to be continuously asserted, with pre-arm checks continuously passing, for at least `ARM_HOLD_SECONDS` (0.5s) before the transition occurs.
- **REQ-ARM-005**: If the arm request is released or a pre-arm check fails at any point while in `Arming`, the state machine SHALL abort to `Disarmed` with no partial-armed state possible.
- **REQ-ARM-006**: While `Armed`, if a pre-arm check fails, the state machine SHALL leave `Armed` (via `Disarming`) on the very next `update()` call - never debounced or delayed.
- **REQ-ARM-007**: While `Armed`, an explicit `ArmRequest::Disarm` SHALL leave `Armed` (via `Disarming`) on the next `update()` call.
- **REQ-ARM-008**: `PreArmChecks::all_pass()` SHALL be true only when both `bit_passed` and `attitude_valid` are true.
- **REQ-ARM-009**: `last_disarm_reason()` SHALL report `PreArmCheckFailed` when the disarm was check-triggered and `UserRequest` when it was request-triggered.

## Motor mixing (`flight::mixer`)

- **REQ-MIX-001**: For zero roll/pitch/yaw demand, `Mixer::mix()` SHALL set all four motor outputs equal to the commanded throttle.
- **REQ-MIX-002**: `mix()` SHALL clamp every motor output to `[0.0, 1.0]` for any input.
- **REQ-MIX-003**: When combined demand would push any single motor output outside `[0,1]` but the total spread across all four motors is `<= 1.0`, `mix()` SHALL shift all four outputs by a common offset before clamping, preserving the pairwise differences between motors exactly - not clamp each motor independently, which would silently and asymmetrically reduce attitude authority near saturation.
- **REQ-MIX-004**: When the spread exceeds `1.0` (shifting alone cannot fit every motor in range), `mix()` SHALL still keep every output within `[0.0, 1.0]` via a final hard clamp, and SHALL preserve the relative ordering between opposing motor pairs as far as the physical bound allows.

## Attitude/rate stabilization (`flight::stabilize`)

- **REQ-STB-001**: `outer_loop()` SHALL compute a body-rate setpoint from the wrapped attitude error (commanded minus estimated attitude) via three independent PID controllers, one per axis.
- **REQ-STB-002**: Attitude error SHALL be computed with shortest-path angle wrapping into `[-pi, pi]`, not raw subtraction, so a setpoint/estimate pair near the `+-pi` boundary produces a small error rather than a near-`2*pi` error.
- **REQ-STB-003**: `inner_loop()` SHALL compute the mixer's roll/pitch/yaw command from rate error (setpoint minus measured rate) via three independent PID controllers, one per axis.
- **REQ-STB-004**: `update()` SHALL be equivalent to one call to `outer_loop()` followed by one call to `inner_loop()`, with the former's output feeding the latter's setpoint.
- **REQ-STB-005**: `reset()` SHALL zero all six PID controllers' integrator and derivative-history state.
- **REQ-STB-006**: `outer_loop()` SHALL be safely callable exactly once per control tick independent of `inner_loop()`, so a caller running both the adaptive-MPC path and the PID-fallback path in the same tick does not advance the outer loop's integrators twice.

## Adaptive-MPC rate controller (`flight::mpc`)

- **REQ-MPC-001**: `MpcController::solve()` SHALL return a command within the caller-supplied `[lo, hi]` bounds for any finite rate/setpoint input.
- **REQ-MPC-002**: For zero rate error and zero rate setpoint, `solve()` SHALL return an (approximately) zero command.
- **REQ-MPC-003**: The feedback component of `solve()`'s output SHALL oppose a positive rate error (negative correction for positive error), consistent with stabilizing state feedback.
- **REQ-MPC-004**: `solve()` SHALL include a feedforward term that cancels the model's steady-state drift at the commanded setpoint, so a sustained nonzero rate setpoint is tracked without persistent steady-state offset.
- **REQ-MPC-005**: `MpcController::new()`/`update_model()` SHALL return `Err(ModelInvalid)` for any model/weight combination that does not admit a well-posed solution (including a non-finite/NaN-contaminated parameter), rather than silently constructing a corrupted controller.
- **REQ-MPC-006**: A failed `update_model()` call SHALL leave the controller's previously-valid gains completely unmodified.
- **REQ-MPC-007**: `reset()` SHALL clear the ADMM solver's warm-start state.

## Online parameter estimation (`flight::adaptive::mrac`)

- **REQ-ADP-001**: Given a persistently-exciting (non-constant) regressor and noiseless linear measurements, `ScalarRls`'s estimate SHALL converge toward the true parameter.
- **REQ-ADP-002**: `ScalarRls` SHALL not update its estimate when the regressor is within `1e-12` of zero, to avoid an erroneous gain from dividing by a near-zero denominator.
- **REQ-ADP-003**: `ParamEstimator::update()` SHALL return `None` on its first call after construction or reset (no previous sample exists to difference against), and SHALL return an updated per-axis effectiveness estimate on every subsequent call.
- **REQ-ADP-004**: `ParamEstimator::reset()` SHALL clear the previous-sample history, such that the next `update()` call again returns `None`.

## L1 disturbance filter (`flight::adaptive::l1`)

- **REQ-ADP-005**: With zero one-step-ahead prediction error (measured state matches the internal model's prediction), `L1Filter::update()` SHALL apply negligible compensation to the passed-through command.
- **REQ-ADP-006**: Under a sustained, constant matched disturbance on one axis, the filter's compensation on that axis SHALL settle to a persistent value opposing the disturbance, while unaffected axes' compensation SHALL remain near zero.
- **REQ-ADP-007**: `reset()` SHALL clear the disturbance estimate, the low-pass filter state, and the one-step prediction history, such that the immediately following `update()` call applies zero compensation.

## Redundancy / voting (`flight::redundancy`)

- **REQ-RED-001**: `PathSelector::select()` SHALL choose `AdaptiveMpc` when its `mpc_valid` argument is true and `PidFallback` when false, as a pure function of that tick's argument only (never sticky across ticks).
- **REQ-RED-002**: `PathSelector` SHALL count consecutive `mpc_valid == false` calls, resetting the count to zero on the first `mpc_valid == true` call.
- **REQ-RED-003**: `TmrVoter::vote()` given 3 present samples all pairwise within `tolerance` SHALL return `Agreed` with their 3-way average.
- **REQ-RED-004**: `TmrVoter::vote()` given 3 present samples where exactly one pair is within `tolerance` SHALL return `Majority` with that pair's average and `outlier_board` correctly identifying the third board's index.
- **REQ-RED-005**: `TmrVoter::vote()` given 3 present samples where no pair is within `tolerance` SHALL return `NoConsensus` - it SHALL NOT average all three or arbitrarily select one.
- **REQ-RED-006**: `TmrVoter::vote()` given exactly 2 present samples SHALL return `Agreed` (their average) only if they are within `tolerance`, else `NoConsensus` - two disagreeing samples SHALL NOT be treated as a de-facto majority.
- **REQ-RED-007**: `TmrVoter::vote()` given fewer than 2 present samples SHALL return `InsufficientData`.

## Gyro bias calibration (`flight::calibration::gyro_bias`)

- **REQ-CAL-001**: Given `samples_needed` stationary (low-variance) samples, `GyroBiasEstimator` SHALL converge to their sample mean and report `CalState::Success`.
- **REQ-CAL-002**: Given samples whose per-axis variance over the window exceeds `max_stddev^2`, the estimator SHALL report `CalState::Failed`, and `bias()` SHALL return zero rather than a bias derived from non-stationary motion.
- **REQ-CAL-003**: `bias()` SHALL return zero whenever `state() != Success`.
- **REQ-CAL-004**: Samples fed to `accumulate()` after the estimator has already reached `Success` or `Failed` SHALL NOT alter the result.

## Accelerometer calibration (`flight::calibration::accel_cal`)

- **REQ-CAL-005**: `AccelCalibration::identity()` SHALL apply as a strict no-op (output exactly equals input) for any input.
- **REQ-CAL-006**: `apply()` SHALL subtract `bias` before multiplying by `scale`, not the reverse order.

## Calibration persistence format (`flight::calibration::storage`)

- **REQ-CAL-007**: `CalibrationRecord::to_bytes()`/`from_bytes()` SHALL round-trip a valid record's accel bias/scale values exactly (these are raw IEEE-754 bytes, not quantized).
- **REQ-CAL-008**: `from_bytes()` SHALL return `None` for data whose magic value does not match the expected constant, including blank/erased FRAM (all `0xFF` or all `0x00` bytes).
- **REQ-CAL-009**: `from_bytes()` SHALL return `None` for data with any bit-flip corruption in the payload, detected via checksum mismatch.
- **REQ-CAL-010**: `from_bytes()` SHALL return `None` for data whose version field does not equal the current format version.

## Built-In Test aggregation (`flight::bit`)

- **REQ-BIT-001**: `BitReport::all_passed()` SHALL be `false` for a report with zero recorded test results (not vacuously true).
- **REQ-BIT-002**: `all_passed()` SHALL be `true` if and only if every recorded test result passed.
- **REQ-BIT-003**: `failed_tests()` SHALL enumerate exactly the tests recorded with `passed == false`, in the order they were recorded.

## System-level integration (`firmware::main`)

These describe safety-relevant behavior of the RTIC task orchestration
itself, not any single portable module. Most cannot be host-unit-tested
(RTIC does not run on a host) - see `TRACEABILITY_MATRIX.md` for exactly
which are backed by SITL evidence versus code inspection only.

- **REQ-SYS-001**: `control_task` SHALL evaluate the arming state machine every control tick regardless of current armed state, so a fault or explicit disarm is delayed by no more than one control period (2ms).
- **REQ-SYS-002**: While armed, the PID-fallback command path SHALL be computed every control tick unconditionally, regardless of which path is currently selected, so it is never stale at the moment a failover occurs.
- **REQ-SYS-003**: The outer attitude-loop PID SHALL be evaluated exactly once per control tick, shared by both the adaptive-MPC path and the PID-fallback path - never twice, which would double-advance its integrator state.
- **REQ-SYS-004**: L1 augmentation SHALL apply only on the `AdaptiveMpc` path; the PID-fallback path SHALL bypass L1 and reset its state whenever it is not the active path.
- **REQ-SYS-005**: `motor_task` SHALL write an explicit zero duty cycle to every PWM channel on every tick the vehicle is not armed, never leaving a previously-set nonzero value in place.
- **REQ-SYS-006**: The power-on Built-In Test SHALL run to completion before any periodic task is spawned, and its aggregate result SHALL gate arming via `PreArmChecks::bit_passed`.
- **REQ-SYS-007**: The boot-time gyro bias and the loaded (or identity-default) accelerometer calibration SHALL be applied to every raw IMU sample before it reaches sensor fusion or is published for other tasks to read.
