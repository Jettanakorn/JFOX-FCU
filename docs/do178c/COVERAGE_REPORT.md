# JFOX-FCU Structural Coverage Report

Aligned with DO-178C's structural coverage analysis objective. Generated
with `cargo-llvm-cov` against `flight`, `math`, and `common` (the
host-testable crates) on `x86_64-pc-windows-msvc`, `--features std`.
Reproduce with:

```bash
cargo llvm-cov -p flight -p math -p common --features std --target x86_64-pc-windows-msvc --branch
```

## What this measures, and what it doesn't

This is **statement/region and branch coverage**, not MC/DC. That gap
matters and isn't cosmetic:

- **Statement/branch coverage** (what's below) asks "did every line run" and
  "did every branch go both ways at least once." DAL C requires this.
- **MC/DC** (Modified Condition/Decision Coverage), required for DAL A - the
  target this project has stated - additionally requires that *each
  individual condition within a multi-condition decision* be shown to
  independently affect that decision's outcome. `cargo-llvm-cov` (like most
  off-the-shelf coverage tools) does not produce this; it would need either
  a dedicated MC/DC tool or manual truth-table analysis of every
  multi-condition boolean expression in the codebase. **This report does not
  close the DAL A coverage gap - it establishes the statement/branch
  baseline that any future MC/DC effort would build on.**
- `hal`, `bsp`, `drivers`, `firmware` are excluded: they're embedded-only
  (register access, RTIC tasks) and don't run on a host, so no coverage tool
  can measure them without hardware-in-the-loop instrumentation, which
  doesn't exist yet (see `HARDWARE_BRINGUP.md`).

## Results (current)

| Metric | Coverage | Previous report | First report |
|---|---|---|---|
| Regions | 99.33% (31/4651 missed) | 97.56% | 86.21% |
| Functions | 100.00% (0/324 missed) | 94.72% | 83.95% |
| Lines | 99.79% (5/2377 missed) | 96.68% | 85.22% |
| Branches | 81.44% (36/194 missed) | 76.34% | 82.46% |

Every file now has 100% line coverage except `voter.rs` (97.28%) and
`matrix.rs` (99.55%) - see "What's left, and why it's left" below for
exactly what those residual misses are and why they're not being chased
further.

Per-file:

| File | Line coverage | Branch coverage |
|---|---|---|
| `flight/src/redundancy/voter.rs` | 97.28% | 100.00% |
| `math/src/matrix.rs` | 99.55% | 100.00% |
| `common/src/can_frames.rs` | 100.00% | 100.00% |
| `flight/src/adaptive/l1.rs` | 100.00% | 100.00% |
| `flight/src/adaptive/mrac.rs` | 100.00% | 100.00% |
| `flight/src/arming.rs` | 100.00% | 100.00% |
| `flight/src/bit/mod.rs` | 100.00% | 100.00% |
| `flight/src/calibration/accel_cal.rs` | 100.00% | - |
| `flight/src/calibration/gyro_bias.rs` | 100.00% | 100.00% |
| `flight/src/calibration/storage.rs` | 100.00% | 100.00% |
| `flight/src/mixer.rs` | 100.00% | 100.00% |
| `flight/src/mpc/admm.rs` | 100.00% | - |
| `flight/src/mpc/mod.rs` | 100.00% | 50.00% |
| `flight/src/mpc/model.rs` | 100.00% | - |
| `flight/src/mpc/riccati.rs` | 100.00% | 100.00% |
| `flight/src/redundancy/mod.rs` | 100.00% | 100.00% |
| `flight/src/sensor_fusion.rs` | 100.00% | 81.25% |
| `flight/src/stabilize.rs` | 100.00% | 100.00% |
| `math/src/filters.rs` | 100.00% | 66.67% |
| `math/src/pid.rs` | 100.00% | - |
| `math/src/quaternion.rs` | 100.00% | 57.89% |
| `math/src/vector.rs` | 100.00% | 53.85% |

## What's left, and why it's left

Every remaining miss was individually inspected (not just left as a
percentage) to confirm it isn't hiding a real gap:

- **`voter.rs`'s 4 missed lines** are `other => panic!(...)` arms inside
  `#[test]` functions' own `match` assertions - reachable only if that test
  is already failing. Forcing them "covered" would mean making a passing
  test fail on purpose, which is not a meaningful improvement.
- **`quaternion.rs`, `vector.rs`, `filters.rs`, `sensor_fusion.rs`, and
  `mpc/mod.rs`'s branch misses** are, on inspection, all inside compound
  `assert!(a && b && c, ...)` expressions in test bodies: every sub-condition
  must be true for the assertion (and thus the test) to pass, so the
  "some sub-condition was false" branch outcome is structurally unreachable
  in a green test suite. This is a test-authoring-style artifact of
  `llvm-cov`'s branch instrumentation, not untested production logic - the
  production `if`/`match` branches these tests are checking are separately,
  fully covered (confirmed by their 100% *line* coverage).
- **`matrix.rs`, `admm.rs`, `riccati.rs`, `can_frames.rs`, `storage.rs`'s
  small region/branch residuals** did not resolve to any `BRDA` (branch)
  entry at all when inspected directly - they're sub-line region-splitting
  in LLVM's coverage model (e.g. a multi-step expression counted as more
  than one region) rather than a missed line or a missed two-way branch.

None of the above represents a code path this report can point to and say
"this behavior is unverified." Genuine gaps found during this pass (not
artifacts) were fixed with real new test cases, not by reformatting:
`flight/src/arming.rs` had no test for staying idle while `Disarmed`, and no
test for a check failure occurring *while still requesting Arm* (only
"request released" was covered) - both are now covered.
`flight/src/calibration/gyro_bias.rs`'s three-axis stationarity check
(`x && y && z`) had only ever been tested with all three axes failing
together, so the case of exactly one axis (pitch, then yaw) tripping the
check while the others pass was unverified - both are now covered.
`flight/src/redundancy/voter.rs`'s non-transitive-tolerance case (a~b and
b~c both hold but a~c does not) was untested - added. `flight/src/bit/mod.rs`
never verified the array-full guard actually drops silently instead of
panicking - added.

## What changed since the last report, and what it found

The previous report's #1 priority - writing `MadgwickFilter` unit tests -
**found a real bug in production code**, not just a coverage gap.

**`flight/src/sensor_fusion.rs`'s gradient-descent step (`s0`..`s3` in
`MadgwickFilter::update`) used the wrong Jacobian-transpose formula.**
Deriving the Jacobian of the accel-residual objective by hand and comparing
against the code (the variable names `j11_24`, `j12_23`, etc. suggest an
index mix-up during transcription) showed the `s0`-`s3` expressions paired
the wrong residual terms (`f1`/`f2`/`f3`) with the wrong quaternion
components. Concretely, a pure-roll accelerometer disagreement fed almost
all of its correction into the **pitch** component instead of roll.

This wasn't a theoretical concern - it was caught because the first version
of the new tests failed in a way that didn't match a simple off-by-tolerance
bug: `MadgwickFilter` run with zero gyro input against a static tilted-accel
reading did not converge to the indicated attitude at all. It either sat at
a degenerate fixed point (exact identity start) or, worse, ran away into an
unrelated large pitch angle while barely correcting roll, with the
*objective function itself* (not just the Euler-angle readout) provably
increasing over time - ruled out as a test-tolerance issue by directly
instrumenting the internal `f1,f2,f3` residual and watching it diverge.
Fixed by replacing the gradient computation with the textbook
Jacobian-transpose (matches the widely-used x-io Technologies reference
implementation of this algorithm). Post-fix, the same scenario converges
cleanly (roll settles within ~0.002 rad of the true 0.3 rad tilt, pitch
stays at exactly 0) from a cold start, with no seeding workaround needed.

**Impact**: `MadgwickFilter` is the attitude estimator every control law in
this codebase depends on (`imu_task` feeds it every IMU sample;
`control_task`'s outer loop, the MPC path, and the PID fallback all consume
its output). Before this fix, static accelerometer-only tilt correction was
broken in a way that would have misestimated attitude on real hardware -
this is exactly the kind of defect the previous report's coverage numbers
warned was possible ("unverified by anything but visual inspection") and is
the clearest evidence in this project that writing the tests was worth
doing, independent of the DAL A/C coverage-percentage discussion.

`sensor_fusion.rs`, `quaternion.rs`, and `vector.rs` - the three worst files
in the first report (0%, 28%, 56% line coverage) - are now all at 100%
line coverage. Every file in the three host-testable crates (`flight`,
`math`, `common`) now has 100% line coverage or is documented above as to
exactly why the residual isn't one.

## Recommended next steps, in priority order

Statement/branch coverage in the host-testable crates is now effectively
closed (99.79% lines, 100% functions, every remaining miss individually
accounted for above). What's left is qualitatively different work:

1. **`hal`, `bsp`, `drivers`, `firmware` have no coverage measurement at
   all** - not low coverage, *no tooling*, because they're embedded-only and
   don't run on a host. This is the largest remaining blind spot in this
   report's scope, not any single file's percentage. Closing it needs
   hardware-in-the-loop instrumentation (see `HARDWARE_BRINGUP.md`), not
   more host-side unit tests.
2. **True MC/DC** for the highest-criticality decision points - arming's
   pre-arm check logic, `TmrVoter`'s branching, the mixer's
   saturation-shift conditionals are reasonable starting candidates given
   they're already control-flow-dense and safety-relevant - is the
   remaining, larger piece of the stated DAL A target that statement/branch
   coverage alone does not close, regardless of what percentage this report
   shows.
3. Keep applying the lesson from `sensor_fusion.rs`: a coverage gap found in
   safety-critical estimation/control code is a bug-hunt opportunity, not
   just a paperwork exercise. Don't assume newly-covered code is merely
   *untested* rather than *wrong* until it's been run against a scenario
   with a known-correct answer, the way the Madgwick fix above was.
