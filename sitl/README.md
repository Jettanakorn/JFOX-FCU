# SITL — Software-in-the-Loop simulator

Drives the real `flight::` control chain (`StabilizeController`, `MpcController`,
`ParamEstimator`, `L1Filter`, `PathSelector`, `Mixer`, `MadgwickFilter`) and
several other real `flight::` subsystems (`ArmingFsm`, `GyroBiasEstimator`,
`TmrVoter`) — the actual production code, not a reimplementation — against
independent physics/noise models, entirely on the host. No target hardware
needed.

For the test *plan* — what each scenario checks, its pass criteria, current
status, and what this has already found — see
`docs/do178c/SIL_TEST_PROGRAM.md`. This file is the practical how-to-run
reference.

## Why this is a separate, non-workspace crate

The parent `JFOX-FCU` workspace's `.cargo/config.toml` pins the default build
target to `thumbv7em-none-eabihf` (the embedded target). `sitl` is a normal
`std` host binary (it writes CSV files to disk), so it can't be a member of
that workspace without breaking `cargo build --workspace` for everyone else.
It's a standalone crate (its own `[workspace]` in `sitl/Cargo.toml`) that
pulls in `math`/`flight`/`common` as ordinary path dependencies with their
`std` feature enabled.

## Running it

From this directory, targeting your host triple explicitly (the workspace
config default is the embedded target, so you must override it):

```bash
# The actual automated test program - exit code reflects pass/fail.
cargo test --release --target x86_64-pc-windows-msvc

# Same scenarios, plus a CSV per scenario for offline plotting and a
# human-readable summary. Useful when investigating a failure.
cargo run --release --target x86_64-pc-windows-msvc
```

(Substitute your host triple - `x86_64-unknown-linux-gnu`,
`aarch64-apple-darwin`, etc. Check with `rustc -vV | grep host`.)

Both entry points run the same scenario functions from `src/scenarios.rs`;
`src/main.rs` is a thin CLI wrapper, `#[cfg(test)] mod tests` at the bottom
of `scenarios.rs` is what `cargo test` runs.

**Current status: 5 of 7 scenarios pass.** `disturbance_rejection` and
`mpc_failover` fail with a known, documented, not-yet-resolved control-loop
oscillation after a transient event - see
`docs/do178c/SIL_TEST_PROGRAM.md`'s "Open" section before spending time
re-diagnosing this from scratch.

CSV columns: `time_s, roll_est, pitch_est, yaw_est` (Madgwick-estimated
attitude, radians), `roll_rate_true, pitch_rate_true, yaw_rate_true` (plant's
true body rates, rad/s), `roll_rate_sp, pitch_rate_sp, yaw_rate_sp` (outer
loop's rate setpoint), `roll_sp, pitch_sp, yaw_sp` (commanded attitude
setpoint), `m1..m4` (mixer motor outputs, 0.0-1.0), `path` (0=AdaptiveMpc,
1=PidFallback). Only the five scenarios that drive the full control chain
through `run_scenario` write a CSV; `tmr_voter_fault_detection` and
`boot_sequence` are structurally different (see below) and don't produce one.

## Scenarios

See `docs/do178c/SIL_TEST_PROGRAM.md` for the full table with pass criteria.
Briefly: `step_response`, `disturbance_rejection`, `mpc_failover`, and
`combined_maneuver` all drive the full control chain via `run_scenario` in
`scenarios.rs` against varying setpoints/disturbances/faults.
`sensor_noise_robustness` does the same with continuous injected gyro/accel
noise. `tmr_voter_fault_detection` and `boot_sequence` are structurally
different: the former drives three independent `MadgwickFilter` instances
(one shared true trajectory, per-board noise, one faulted board) through the
real `TmrVoter`, and the latter drives a real `GyroBiasEstimator` into a real
`ArmingFsm` — neither needs the `Plant`/full control chain, since they're
testing different subsystems than the rate/attitude loop.

## Known simplifications

Stated once here rather than scattered through comments:

- **No sensor noise**, except in `sensor_noise_robustness` and
  `tmr_voter_fault_detection` specifically. The other scenarios validate
  nominal control-chain behavior, not noise robustness, by design.
- **Fixed 500Hz/1kHz control/IMU rates with a simple substep loop**, not
  real RTIC task-scheduling jitter or preemption timing.
- **The plant model is a stated simplification** (see `src/plant.rs`'s doc
  comment) — full nonlinear rigid-body rotational dynamics and motor lag are
  modeled, but rotor thrust/drag curves and frame geometry are not; it exists
  to create genuine, independent model mismatch for the adaptive layer to
  handle, not to be aerodynamically accurate.
- **Only the rate/attitude control chain is simulated** — no position/velocity
  control exists in this codebase to simulate in the first place.
- **The noise injection PRNG (`Xorshift32` in `scenarios.rs`) is a
  hand-rolled, deterministic, non-cryptographic generator** chosen to match
  this codebase's no-external-dependency convention (see `math::matrix`'s
  doc comment for the same rationale elsewhere) - it is reproducible run to
  run, not a claim of statistically rigorous randomness.

## Keeping this in sync

`src/control_chain.rs` hand-mirrors `firmware/src/main.rs`'s `control_task`
logic (minus the RTIC scheduling and register access, which can't run on a
host). If `control_task` changes, update `control_chain.rs` to match — there
is currently no automated check that they've stayed in sync. This includes
tuning constants: `control_chain.rs`'s `L1Filter::new` call must match
`firmware/src/main.rs`'s (both are currently `adaptation_gain=5.0` - see
`docs/do178c/SIL_TEST_PROGRAM.md` for why that number and not the
originally-shipped `30.0`).
