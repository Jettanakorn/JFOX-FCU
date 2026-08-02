# JFOX-FCU Requirements Traceability Matrix

Maps each requirement in `SOFTWARE_REQUIREMENTS.md` to its implementing code
and its verification evidence. **Status legend:**

- ✓ **Direct** - a specific unit test asserts exactly this requirement.
- **~ Indirect** - exercised as a side effect of other tests, but no test
  isolates and asserts this specific requirement on its own.
- ✗ **Inspection only** - no automated test; requirement is believed true
  from reading the code, nothing more. Anything marked this way is a real
  gap, not a formality - see "Gaps this exercise found" at the bottom.

## Arming (`flight/src/arming.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-ARM-001 | `ArmingFsm::new()` | `starts_disarmed_and_refuses_output` | ✓ |
| REQ-ARM-002 | `ArmingFsm::output_allowed()` | `starts_disarmed_and_refuses_output`, `arm_request_requires_debounced_hold` | ✓ |
| REQ-ARM-003 | `update()`, `Disarmed` arm | `arm_request_requires_debounced_hold`, `cannot_arm_while_prearm_checks_fail` | ✓ |
| REQ-ARM-004 | `update()`, `Arming` arm | `sustained_arm_request_reaches_armed_after_hold_time` | ✓ |
| REQ-ARM-005 | `update()`, `Arming` abort path | `releasing_arm_request_mid_hold_aborts_to_disarmed` | ✓ |
| REQ-ARM-006 | `update()`, `Armed` check-fail path | `armed_disarms_immediately_on_check_failure_no_debounce` | ✓ |
| REQ-ARM-007 | `update()`, `Armed` disarm-request path | `armed_disarms_on_explicit_disarm_request` | ✓ |
| REQ-ARM-008 | `PreArmChecks::all_pass()` | Exercised via every FSM test's `good_checks()`/`bad_checks()` helpers | ~ |
| REQ-ARM-009 | `last_disarm_reason()` | `armed_disarms_immediately_on_check_failure_no_debounce`, `armed_disarms_on_explicit_disarm_request` | ✓ |

## Motor mixing (`flight/src/mixer.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-MIX-001 | `Mixer::mix_quad_x()` | `hover_throttle_no_attitude_gives_equal_motors` | ✓ |
| REQ-MIX-002 | `mix_quad_x()`, final clamp | `all_outputs_always_within_bounds_under_extreme_input` | ✓ |
| REQ-MIX-003 | `mix_quad_x()`, shift logic | `saturation_is_proportional_not_independently_clamped`, `negative_demand_is_shifted_up_not_clamped_to_zero` | ✓ |
| REQ-MIX-004 | `mix_quad_x()`, shift + hard clamp | `extreme_saturation_still_clips_safely_and_preserves_order` | ✓ |

## Stabilization (`flight/src/stabilize.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-STB-001 | `outer_loop()` | `positive_roll_error_produces_positive_roll_output`, `zero_error_gives_zero_attitude_output` (both via `update()`) | ~ |
| REQ-STB-002 | `wrap_pi()` | `yaw_error_wraps_shortest_path` | ✓ |
| REQ-STB-003 | `inner_loop()` | Exercised only via `update()` in the tests above; no test calls `inner_loop()` directly with a controlled rate setpoint | ~ |
| REQ-STB-004 | `update()` | All `stabilize::tests` (all go through `update()`) | ✓ |
| REQ-STB-005 | `reset()` | `reset_clears_integrator_state` | ✓ |
| REQ-STB-006 | `outer_loop()`/`inner_loop()` split, non-double-integration | None | ✗ |

## Adaptive-MPC (`flight/src/mpc/`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-MPC-001 | `admm::solve()` | `respects_box_constraints_under_large_error`, `feedforward_shifts_the_effective_saturation_point` | ✓ |
| REQ-MPC-002 | `admm::solve()` | `admm::zero_error_and_zero_feedforward_gives_zero_command`, `mpc::zero_error_gives_zero_command` | ✓ |
| REQ-MPC-003 | `admm::solve()` | `output_opposes_a_positive_rate_error` | ✓ |
| REQ-MPC-004 | `MpcController::solve()` feedforward | `closed_loop_simulation_drives_rate_error_to_zero` | ✓ |
| REQ-MPC-005 | `riccati::precompute()`, `Mat3::inverse()`'s finite-determinant guard | `update_model_keeps_old_gains_on_failure` (NaN case only - a singular-but-finite model is not separately tested) | ~ |
| REQ-MPC-006 | `MpcController::update_model()` | `update_model_keeps_old_gains_on_failure` | ✓ |
| REQ-MPC-007 | `MpcController::reset()` | `reset_clears_admm_warm_start` | ✓ |

## Online parameter estimation (`flight/src/adaptive/mrac.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-ADP-001 | `ScalarRls::update()` | `scalar_rls_converges_to_known_effectiveness`, `param_estimator_converges_on_synthetic_plant` | ✓ |
| REQ-ADP-002 | `ScalarRls::update()`, near-zero-regressor guard | `scalar_rls_skips_update_on_near_zero_regressor` | ✓ |
| REQ-ADP-003 | `ParamEstimator::update()` | `param_estimator_first_call_returns_none` | ✓ |
| REQ-ADP-004 | `ParamEstimator::reset()` | `reset_clears_history_and_restarts_from_given_values` | ✓ |

## L1 filter (`flight/src/adaptive/l1.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-ADP-005 | `L1Filter::update()` | `no_prediction_error_gives_negligible_compensation` | ✓ |
| REQ-ADP-006 | `L1Filter::update()` | `constant_disturbance_produces_persistent_opposing_compensation` | ✓ |
| REQ-ADP-007 | `L1Filter::reset()` | `reset_clears_adaptation_and_prediction_state` | ✓ |

## Redundancy / voting (`flight/src/redundancy/`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-RED-001 | `PathSelector::select()` | `valid_mpc_selects_adaptive_path`, `recovery_is_immediate_not_sticky` | ✓ |
| REQ-RED-002 | `PathSelector::select()` | `invalid_mpc_selects_fallback_and_counts_failures`, `recovery_is_immediate_not_sticky` | ✓ |
| REQ-RED-003 | `TmrVoter::vote()`, 3-agree branch | `all_three_agree_averages_all_three` | ✓ |
| REQ-RED-004 | `TmrVoter::vote()`, majority branch | `one_outlier_produces_majority_and_flags_correct_board`, `outlier_flagging_identifies_board_zero`, `outlier_flagging_identifies_board_one` | ✓ |
| REQ-RED-005 | `TmrVoter::vote()`, no-consensus branch | `all_three_disagree_gives_no_consensus` | ✓ |
| REQ-RED-006 | `TmrVoter::vote()`, 2-present branch | `one_missing_board_falls_back_to_two_board_agreement`, `two_present_but_disagreeing_gives_no_consensus_not_a_guess` | ✓ |
| REQ-RED-007 | `TmrVoter::vote()`, `<2`-present branch | `fewer_than_two_boards_present_is_insufficient_data` | ✓ |

## Gyro bias calibration (`flight/src/calibration/gyro_bias.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-CAL-001 | `GyroBiasEstimator::accumulate()` | `stationary_samples_converge_to_the_true_bias` | ✓ |
| REQ-CAL-002 | `accumulate()`, variance check | `excessive_motion_during_window_fails_calibration` | ✓ |
| REQ-CAL-003 | `bias()` | `excessive_motion_during_window_fails_calibration` | ✓ |
| REQ-CAL-004 | `accumulate()`, post-completion guard | `further_samples_after_completion_are_ignored` | ✓ |

## Accelerometer calibration (`flight/src/calibration/accel_cal.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-CAL-005 | `AccelCalibration::identity()` | `identity_calibration_is_a_no_op` | ✓ |
| REQ-CAL-006 | `AccelCalibration::apply()` | `bias_and_scale_apply_in_the_right_order` | ✓ |

## Calibration persistence (`flight/src/calibration/storage.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-CAL-007 | `to_bytes()`/`from_bytes()` | `roundtrips_through_bytes` | ✓ |
| REQ-CAL-008 | `from_bytes()`, magic check | `blank_erased_fram_is_rejected` | ✓ |
| REQ-CAL-009 | `from_bytes()`, checksum check | `corrupted_payload_fails_checksum` | ✓ |
| REQ-CAL-010 | `from_bytes()`, version check | `wrong_version_is_rejected` | ✓ |

## Built-In Test (`flight/src/bit/mod.rs`)

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-BIT-001 | `BitReport::all_passed()` | `empty_report_is_not_all_passed` | ✓ |
| REQ-BIT-002 | `all_passed()` | `all_tests_passing_gives_all_passed`, `one_failure_fails_the_whole_report_and_is_identified` | ✓ |
| REQ-BIT-003 | `failed_tests()` | `results_preserves_insertion_order`, `one_failure_fails_the_whole_report_and_is_identified` | ✓ |

## System-level integration (`firmware/src/main.rs`)

RTIC tasks don't run on a host, so none of these have a unit test in the
usual sense; `sitl/` exercises the real `flight::` types end-to-end but
mirrors `control_task` by hand rather than running the actual RTIC binary
(see `sitl/README.md`'s "keeping this in sync" note - there is no automated
check that the mirror and the real task haven't drifted apart).

| REQ | Implementing code | Verified by | Status |
|---|---|---|---|
| REQ-SYS-001 | `control_task`, arming update placement | Code inspection only | ✗ |
| REQ-SYS-002 | `control_task`, unconditional PID-fallback computation | SITL `mpc_failover` scenario (via `sitl::control_chain`, not the real task) | ~ |
| REQ-SYS-003 | `control_task`, single `outer_loop()` call | Code inspection only | ✗ |
| REQ-SYS-004 | `control_task`, L1 path gating | SITL `mpc_failover` scenario (via `sitl::control_chain`) | ~ |
| REQ-SYS-005 | `motor_task`, zero-duty-when-disarmed | Code inspection only; see `HARDWARE_BRINGUP.md` Stage 1 for the planned real check | ✗ |
| REQ-SYS-006 | `init()`, BIT sequencing and `PreArmChecks::bit_passed` gating | Code inspection only | ✗ |
| REQ-SYS-007 | `imu_task`, calibration application | Code inspection only | ✗ |

## Gaps this exercise found

Writing this matrix is itself a DO-178C-aligned activity, and it did its
job - it surfaced real, previously-undocumented coverage gaps rather than
confirming everything was already fine:

1. **REQ-STB-006 has no test at all.** The specific property that makes the
   MPC/PID-fallback split safe - that `outer_loop()` can be called once and
   shared without `inner_loop()` accidentally being called in a way that
   double-advances integrator state - is asserted by this document but not
   verified by any test. A concrete, addressable next step: a test that
   calls `outer_loop()` once then `inner_loop()` twice with different rate
   setpoints and confirms the second call doesn't reflect a corrupted
   integrator from a phantom second `outer_loop()` invocation.
2. **REQ-MPC-005 is only partially tested** - the NaN-contaminated-input case
   is covered, but a merely-singular (non-NaN) model/weight combination that
   should also be rejected by `Mat3::inverse()`'s near-zero-determinant check
   has no dedicated test.
3. **All seven REQ-SYS-* requirements rest on code inspection alone**, or on
   `sitl`'s hand-mirrored approximation of `control_task` rather than the
   real RTIC task. This is the single biggest structural gap: the properties
   that matter most for flight safety (arming checked every tick, PWM zeroed
   when disarmed, BIT gating arming) are exactly the ones with the weakest
   verification evidence, because they only exist inside code that can't run
   on a host. Closing this requires hardware-in-the-loop testing (see
   `HARDWARE_BRINGUP.md`), not more host-side unit tests.
4. **REQ-ARM-008 and REQ-STB-001/003 are "indirect" only** - true today
   (nothing contradicts them), but a change that broke `all_pass()`'s exact
   AND-of-both-fields logic, or `outer_loop()`/`inner_loop()`'s specific
   composition order, would not necessarily be caught by an existing test
   failing; it would need a test that isolates that exact statement to
   guarantee that.
