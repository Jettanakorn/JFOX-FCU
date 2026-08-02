# JFOX-FCU Software-in-the-Loop (SIL) Test Program

Aligned with DO-178C's software verification objectives, at the level this
project has stated it's actually pursuing (see `README.md` for the honest
scope statement - this is not a certified test program). Implemented in the
standalone `sitl/` crate (see `sitl/README.md` for build/run instructions);
this document is the test *plan* - what each scenario verifies, its pass
criteria, and its current status - not a duplicate of the how-to-run
instructions.

## Purpose and scope

`sitl/` drives the real, unmodified `flight::` control chain and several
other real `flight::` subsystems (arming, calibration, redundancy) against
independent physics/noise models, entirely on the host. It exists to catch
integration-level and closed-loop defects that per-module unit tests
structurally cannot: a unit test exercises one function against
hand-constructed inputs; these scenarios exercise the *whole* control chain,
running for seconds of simulated flight time, against a physics model that
is deliberately different from what the controller assumes internally (see
`sitl/src/plant.rs`'s doc comment) - closed-loop, cumulative, and nonlinear
effects only show up this way.

**What this scope does not cover**: `hal`, `bsp`, `drivers`, `firmware`'s
RTIC scheduling, and anything requiring real hardware timing/register access
are out of scope for a host-run simulation - see `HARDWARE_BRINGUP.md` for
the staged hardware bring-up plan that picks up where this leaves off.

## How to run

See `sitl/README.md`. Two entry points, same underlying scenario functions:

- `cargo test --release --target <host-triple>` (from `sitl/`) - the actual
  automated test program. Exit code reflects pass/fail; this is what a CI
  step or pre-commit check should run.
- `cargo run --release --target <host-triple>` (from `sitl/`) - the same
  scenarios, plus a CSV per scenario for offline plotting, plus a
  human-readable summary. Useful when investigating a failure, not needed to
  just get a pass/fail answer.

## Scenarios

| Scenario | Verifies | Pass criteria |
|---|---|---|
| `step_response` | Attitude converges to a step setpoint change and stays converged | Settled attitude error (windowed, last 0.5s) < 0.05 rad; motor commands smooth (no full-scale chatter) in that window; nothing NaN/infinite |
| `disturbance_rejection` | Recovery from an injected external torque (simulated gust) | Settled attitude error < 0.05 rad, settled body rate < 0.05 rad/s, motor commands smooth, in the windowed tail after the gust |
| `mpc_failover` | `PathSelector` switches to the PID fallback exactly when forced invalid, and recovers cleanly on failback | Correct path selected at every tick relative to the forced-invalid window; nothing NaN/infinite at any point; settled attitude error and motor smoothness in the windowed tail after failback |
| `combined_maneuver` | Simultaneous multi-axis commands, including a setpoint changing mid-flight (a yaw reversal partway through) | Settled attitude error and motor smoothness after the reversal, windowed |
| `sensor_noise_robustness` | Continuous gyro/accel noise doesn't destabilize the chain | Mean (not max - see rationale in `sitl/src/scenarios.rs`) settled attitude error under noise < 0.1 rad; nothing NaN/infinite |
| `tmr_voter_fault_detection` | `flight::redundancy::voter::TmrVoter` against synthetic 3-board sensor streams (not `voter.rs`'s own hand-crafted unit-test numbers) - correctly flags an injected stuck-gyro fault on one board without corrupting the 2-of-3 majority value | Board 2's fault is flagged (correct `outlier_board`) once it's had time to diverge past tolerance; no false-positive fault flag before the injected fault; the majority value stays close to true attitude throughout |
| `boot_sequence` | Gyro bias auto-calibration must complete before `ArmingFsm` will accept an arm request - the two are unit-tested in isolation but were never previously driven together against a timeline, mirroring `firmware/src/main.rs::init()`'s PBIT sequence | Calibration succeeds; arming is never granted before the debounce hold completes; arming is eventually granted once checks pass and the hold completes |

**Windowed, not single-sample.** Every "has it settled" check looks at a
trailing window (0.5s / 250 ticks at the 500Hz control rate), not the final
tick alone. An earlier version of this file checked only the last sample,
which let a real defect (below) through undetected because the system was
still oscillating - the final sample just happened to land on a
near-zero phase of that oscillation. See `sitl/src/scenarios.rs`'s doc
comment for the specifics.

## Current status: 5 of 7 passing

This is reported honestly, not rounded up. Run `cargo test` from `sitl/` to
reproduce.

### What this test program has already found and fixed

**`flight::adaptive::l1::L1Filter`'s adaptation gain was set too high for
its low-pass cutoff, causing full-scale motor chatter.** At the
originally-shipped `adaptation_gain=30.0` (both in `sitl/src/control_chain.rs`
and in production `firmware/src/main.rs`), `step_response` and
`disturbance_rejection` showed motor commands swinging between 0.0 and 1.0
almost every single control tick, even at a fully converged, undisturbed
hover - a near-Nyquist limit cycle. The attitude *estimate* looked converged
throughout (the oscillation averages out in position, not in the actuator
commands), which is exactly why a check that only looked at attitude, not
motor output, missed it. Root cause and fix are documented in
`firmware/src/main.rs`'s `L1Filter::new` call site; `adaptation_gain=5.0` -
empirically the first value with clean, settled motor output across every
scenario tried, with margin below the found instability threshold (still
chattering at `10.0`) - is now used in both places.

**`flight::adaptive::mrac::ScalarRls` was vulnerable to estimator windup
during low-excitation periods, letting its parameter estimate flip sign.**
With the RLS forgetting factor `lambda` close to 1 (the only realistic
range), the existing `denom.abs() < 1e-12` guard never actually triggers for
near-zero excitation - it only guards the degenerate `lambda≈0` case. During
quiet flight (near-setpoint, near-zero commanded rate change), the
regressor sits near zero for many consecutive updates; with nothing to stop
it, `covariance` grows every update it's not gated, and once wound up, a
single small-but-nonzero regressor combined with a wound-up covariance can
swing the estimated control-effectiveness through zero into the wrong sign -
observed directly in SITL as `flight::mpc::model::RateModel::bd`'s diagonal
going negative mid-flight, after which the controller's own commands were
provably wrong-signed and rate diverged to several rad/s.  Fixed with a
standard adaptive-control dead-zone: skip the update entirely below a real
excitation threshold (`EXCITATION_DEADZONE = 0.01`), so covariance simply
cannot wind up during a quiet period in the first place. See
`flight::adaptive::mrac::ScalarRls::update`'s doc comment for the full
mechanism and `flight/src/adaptive/mrac.rs`'s
`scalar_rls_dead_zone_prevents_covariance_windup_during_a_quiet_period` test.

### Open: `disturbance_rejection` and `mpc_failover` still fail

Both scenarios share a pattern: a transient event (a gust; a forced
failover-then-failback) is followed by a residual oscillation that either
takes longer than the 0.5s tail window to fully settle
(`disturbance_rejection`: rate up to ~0.23 rad/s in the window, attitude
itself is fine at ~0.004 rad) or doesn't cleanly settle within the
scenario's remaining duration at all (`mpc_failover`: motor commands still
show full-scale steps in the tail window). The estimator-windup fix above
measurably improved `mpc_failover` (previously an outright divergence to
several rad/s; now a bounded but real oscillation) without fully resolving
it, which means there is a second, distinct contributing cause not yet
isolated.

**One hypothesis was tried and rejected, on the record so it isn't
re-attempted without new evidence**: gating `ParamEstimator` updates while
the corresponding axis' command is saturated (the reasoning being that a
finite-difference "measurement" formed while an actuator is pinned at its
rail is dominated by motor-lag/nonlinear rail dynamics, not the linear
effectiveness being identified). Implemented and tested in SITL: this made
every scenario dramatically worse (`disturbance_rejection`'s peak rate went
from ~0.23 to ~70 rad/s), including two that had been passing cleanly. It
was reverted immediately. The likely reason: this system spends real,
non-transient time near saturation as a normal part of aggressive
maneuvering (not just brief transient spikes), and refusing to ever learn
during that time starves the estimator of exactly the informative data it
needs, leaving it stuck on a stale/wrong estimate that causes problems
elsewhere. Whatever the real second cause is, it is not "just gate on
saturation."

**Recommended next steps** for whoever picks this up:
1. Trace `flight::mpc::model::RateModel::bd`'s diagonal and
   `flight::adaptive::l1::L1Filter`'s internal `sigma_hat` through
   `mpc_failover`'s tail window specifically (a temporary env-var-gated
   `eprintln!` in `control_chain.rs::control_tick`, removed before landing,
   was how the estimator-windup cause above was originally isolated - the
   same technique would work here) to see which subsystem's state is
   actually oscillating, rather than guessing at the mechanism the way the
   rejected saturation-gate hypothesis did.
2. Consider whether `L1Filter`'s one-step-ahead prediction
   (`model.predict(...)` using the model's *current, adaptively-updated*
   `Ad`/`Bd`) creates a feedback path between the two adaptive layers
   (MRAC's model updates changing what L1 predicts, changing L1's
   correction, changing what MRAC subsequently identifies) that neither
   layer's own unit tests can see, since each is tested in isolation.
3. Do not weaken this document's or `scenarios.rs`'s pass thresholds to make
   these two scenarios pass without addressing the underlying oscillation -
   that would defeat the entire purpose of building this test program, which
   is specifically to keep catching real defects like the two already found.
