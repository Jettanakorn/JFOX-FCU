# Hardware bring-up runbook: single board → 2-board CAN → 3-board TMR

**Correction**: an earlier version of this file claimed no real hardware had
ever been available. That was wrong - a single PX4FMUv2.4.5 board was
flashed and verified running real firmware on 2025-12-30, predating the
session that wrote this file's original text (see `BUILD_AND_FLASH.md`'s
status table and `VERIFICATION_STATUS.md`/`V2_STATUS.md` for that record).
What's actually true: that verification was of `jfox-fcu` (`main_simple.rs`,
IMU read + Madgwick fusion only) - **`jfox-fcu-flight`, the real flight
application this runbook's Stage 1 is about, has never been flashed to real
hardware.** The gap this file exists to close is real, just narrower than
originally stated.

Everything up to this point (Phases 0-4 of the implementation plan) has been
verified by compiling for the real embedded target, host-run unit tests, and
the SITL simulator (`sitl/`, see its README). This document is what to
actually do once `jfox-fcu-flight` is on the bench, in the order the
original plan specified: single board first, then 2-board CAN, then 3-board
full TMR — do not skip ahead.

## Prerequisites

- ST-Link (or equivalent SWD probe) + `probe-rs` installed (`cargo install
  probe-rs`), or the PX4-bootloader USB flashing path documented in
  `BUILD_AND_FLASH.md`.
- `defmt-rtt` log viewing via `probe-rs run` (the `jfox-fcu-flight` binary
  already links `defmt-rtt`/`panic-probe` and logs at `info` level by
  default — see `.cargo/config.toml`'s `DEFMT_LOG` env var).
- **Propellers removed for every step below until explicitly stated
  otherwise.** The arming FSM currently never arms (no RC/command link
  exists yet — see `flight::arming` module docs and the `TODO` in
  `firmware/src/main.rs::control_task`), so motors cannot spin under normal
  operation, but do not rely on that as a safety measure while bringing up
  new hardware/firmware paths.

## Stage 1 — Single board bench test

Goal: confirm `jfox-fcu-flight` (the binary this plan's Phases 0-2 built)
behaves correctly on real silicon, matching what SITL predicted.

1. Flash: `cargo flash --chip STM32F427VITx --release --bin jfox-fcu-flight`
   (or `probe-rs run` for live logging).
2. Confirm boot log sequence matches `firmware/src/main.rs::init()`: clock
   config, PWM/SPI init, MPU-6000 init (WHO_AM_I check), stabilizer/mixer/MPC/
   L1/param-estimator/path-selector init, then the `====` banner.
3. **IMU sanity**: with the board level and stationary, confirm the ~1Hz
   attitude log (`imu_task`) reports roll/pitch near 0° and a stable
   temperature reading. Tilt the board by hand and confirm the sign and
   magnitude of roll/pitch tracks physical tilt correctly (this is the first
   real-hardware exercise of `MadgwickFilter`, previously only validated in
   SITL/host tests against synthetic IMU data).
4. **PWM sanity** (scope on FMU-CH1..CH4 / PE14,13,11,9 per the corrected
   `bsp::pins` mapping): confirm 400Hz refresh and that duty cycle tracks
   `hal::pwm::Pwm::set_channel_duty` calls. The vehicle cannot arm yet (no
   command link), so this specifically means confirming `motor_task` writes
   the expected **0% duty while disarmed** — verify this before anything
   else, since it's the actual safety property this whole arming/mixer chain
   exists to guarantee.
5. **Control-loop timing** (this is the actual point of `hal::dwt::Dwt`,
   added in Phase 2 specifically because it couldn't be measured without real
   hardware): watch the `control_task: {cycles} cycles ({us}us @ 180MHz)`
   log line (~1Hz). Record the steady-state value.
   - If headroom relative to the 2ms budget is small, reduce
     `MPC_ADMM_MAX_ITERS` in `firmware/src/main.rs` before proceeding — the
     value there (10) was never validated against real timing, only assumed
     reasonable from the ADMM iteration cost being a handful of 3x3
     matrix-vector products.
   - This is also the point to decide whether `MPC_RICCATI_ITERS_UPDATE` (20,
     runs at the decimated ~50Hz parameter-estimator rate) needs lowering, or
     whether warm-starting the Riccati solve from the previous `P` (not
     currently implemented - `riccati::solve_riccati` always starts fresh
     from `Q`) is worth adding to cut that recurring cost.
6. Only once 1-5 are solid: with an RC or bench-test command path wired in
   (still a `TODO` in this codebase - see `flight::arming` docs), confirm the
   arming FSM requires the full debounced hold, refuses arming on a bad
   pre-arm check, and disarms instantly (no debounce) on a forced fault.
   Props still off for this step - confirm motor duty cycle response with the
   scope, not by spinning anything.

**Do not proceed to Stage 2 until Stage 1's control-loop timing is measured
and the ADMM/Riccati iteration counts are confirmed (or adjusted) against
real numbers**, per the Phase 2 plan's explicit instruction not to size that
iteration cap on assumption.

## Stage 2 — 2-board CAN bring-up

Goal: validate `hal::can` and `common::can_frames` in isolation, then across
a real bus, before trusting them as part of a voting quorum.

1. **Single-board CAN loopback** (do this before involving a second board):
   wire CAN1 TX (PD1) to CAN1 RX (PD0) through a transceiver in loopback, or
   use a bench CAN analyzer. Confirm `Can::<1>::init()` succeeds (returns
   `Ok`, not `CanError::InitTimeout`/`BitrateNotAchievable`), and that a
   transmitted `CanFrame` is received back with the same ID/DLC/data. This
   validates the bit-timing math in `hal::can` (9 time-quanta per bit,
   computed from the 45MHz APB1 clock) against a real bus for the first time
   - it was only checked by inspection, never against an oscilloscope or a
     second node.
2. **2-board exchange**: connect two boards' CAN1 (with proper termination -
   120 ohm at each physical bus end, not per-node) over CAN_H/CAN_L. Each
   board transmits a `common::can_frames::CommandVoteFrame` with its own
   `board_id` at the control rate; confirm each board receives the other's
   frame and `common::can_frames::CommandVoteFrame::from_can_bytes` decodes
   it correctly (cross-check against what the transmitting board logged
   sending).
3. **Fault injection**: unplug one board's CAN connection mid-run and confirm
   the receiving board correctly reports `flight::redundancy::TmrVoter::
   vote_command` returning `VoteResult::InsufficientData` (only 1 board
   present) rather than hanging or misinterpreting stale data. Reconnect and
   confirm recovery. Separately, send a frame with a deliberately corrupted
   payload (flip a data byte) from a bench tool and confirm the receiving
   board's 2-of-3 (or with only 2 boards, pairwise-agreement) logic in
   `TmrVoter::vote` correctly flags the mismatch (`NoConsensus` with 2 boards
   present and disagreeing) rather than averaging in bad data.
4. **Bus timing under load**: this is the open question flagged in the Phase
   3 plan and never resolved with real numbers - measure actual bus loading
   with both command-vote (full control rate) and sensor-cross-check traffic
   running, and confirm the recommended decimation of sensor-cross-check to
   ~100-250Hz (versus full rate for command-vote) actually leaves headroom
   within the 2ms control period. Use a CAN bus analyzer or the `Dwt` cycle
   counter around the CAN TX/RX calls if a dedicated analyzer isn't
   available.

**None of Stage 2's `hal::can`/`TmrVoter` wiring into `firmware/main.rs`'s
`control_task` exists yet** - this stage is about validating the driver and
voter logic stand-alone/pairwise first. Wiring 3-board voting into the actual
control loop is new firmware work that should happen after Stage 2 passes,
not before.

## Stage 3 — 3-board full TMR bring-up

Goal: the actual triple-modular-redundant configuration, only attempted once
Stage 2 is solid on 2 boards.

1. Bring up the third board identically to Stage 1 (single-board checks
   pass independently on all three boards before connecting them).
2. Connect all three CAN1 buses together (proper multi-drop termination -
   120 ohm at the two physical ends of the bus, none at the middle node).
3. Confirm all three boards' `TmrVoter::vote_command` reach `VoteResult::
   Agreed` under normal operation (all three command outputs within
   tolerance of each other, since all three should be running the same
   control law against very similar sensor data).
4. Fault injection with 3 boards present: disconnect one board's CAN and
   confirm the remaining two correctly fall back to pairwise agreement
   (`Agreed` if they still match, `NoConsensus` if not) rather than treating
   the missing board's last-known value as still valid. Reconnect and confirm
   the returning board is reintegrated (starts contributing to voting again)
   without requiring a reset of the other two.
5. Simulate one board reporting a bad command (e.g. a bench/debug build that
   deliberately transmits an out-of-tolerance value) and confirm the other
   two correctly identify it as the outlier via `VoteResult::Majority{
   outlier_board, .. }`, and that whatever consumes this result (still `TODO`
   - `TmrVoter` is not yet wired into `motor_task`'s final output gate)
   is designed to exclude the outlier's contribution to the actual motor
   command, not just log it.
6. Only after 1-5 pass: sustain full-rate command-vote traffic across all
   three boards simultaneously and confirm no missed control-period
   deadlines using `Dwt`-based timing measurement on all three boards, not
   assumed from the 2-board numbers in Stage 2.

## What's still open after Stage 3

Wiring `TmrVoter`'s output into `motor_task` as the actual final gate before
PWM (currently `motor_task` only reads a single board's own `motor_outputs`
`Shared` resource - there is no cross-board arbitration in the control loop
at all yet) is real firmware work that should be scoped and planned
separately once Stage 3's bench data exists to design against, rather than
guessed at now.
