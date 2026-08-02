# JFOX-FCU Coding Standard

Aligned with DO-178C's Software Coding Standards (SCS) objective. This
documents conventions the `flight`/`math`/`common` crates already follow as
of this writing (verified by direct inspection, not assumed - see the
verification note per rule) plus explicit restrictions motivated by DAL A's
higher rigor. Scope: `flight`, `math`, `common` (portable, host-testable
logic). `hal`/`bsp`/`drivers`/`firmware` (embedded-only register access and
task orchestration) follow a related but distinct convention noted in
§7 - they are not held to the "no `unsafe`" rule since register access is
inherently unsafe.

## 1. No dynamic memory allocation

`#![no_std]` throughout, with no `extern crate alloc` and no heap allocator
configured anywhere in the workspace. All data structures are fixed-size
(const-generic arrays, not `Vec`/`Box`). **Verified**: no crate in this
workspace depends on `alloc`.

## 2. No dynamic dispatch

No `dyn Trait` anywhere in `flight`, `math`, `common`, `hal`, `drivers`, or
`firmware`. **Verified**: `grep -rn "dyn " --include="*.rs"` across the whole
workspace returns zero matches. Generic (monomorphized, static-dispatch)
parameters are used instead (e.g. `Mpu6000<SPI, CS>`, `Mixer` is a concrete
type, not a trait object) - call targets are fully determined at compile
time, which both DAL A's determinism expectations and MC/DC's
decision-enumeration requirements depend on.

## 3. No unbounded recursion

No function in `flight`/`math`/`common` calls itself, directly or
indirectly. Iteration is used throughout, always over a fixed or
explicitly-bounded count (e.g. `mpc::admm::solve`'s `max_iters` parameter,
`mpc::riccati::solve_riccati`'s `iterations` parameter,
`calibration::gyro_bias::GyroBiasEstimator`'s `samples_needed`). Stack depth
is therefore statically boundable - required for DAL A's worst-case
stack-usage analysis, which is meaningless in the presence of unbounded or
data-dependent recursion.

## 4. No unbounded loops in reachable business logic

Every `for`/`while` loop in `flight`/`math`/`common` iterates a fixed or
externally-bounded count. The one exception to "bounded" by design, not by
oversight: RTIC task bodies in `firmware/src/main.rs` (`imu_task`,
`control_task`, `motor_task`, `heartbeat_task`) are `loop { ...; delay().await
}` - infinite by construction, because that is the correct shape for a
periodic real-time task under an RTOS scheduler, not a violation of this
rule. Each such loop's *body* (the work done per iteration, before yielding
back to the scheduler via `.await`) is itself non-looping/bounded.

## 5. `unsafe` is confined to hardware access, never business logic

Zero `unsafe` blocks in `flight`, `math`, or `common` (verified by direct
grep, not assumed). All `unsafe` in this workspace is register-level access
in `hal`/`bsp`/`drivers`, or pin/peripheral configuration in
`firmware::init()`. This split is structural, not just conventional: control
laws, arming logic, mixing, calibration math, and voting logic cannot reach
hardware except through the narrow, audited interface the lower layers
expose.

## 6. Every `unwrap()`/`expect()` in production code carries a justification
   comment proving it cannot panic on any reachable input

Not "should be rare" - as of this writing, exactly two call sites in
`flight`'s non-test code use `unwrap()`, and both now carry an `INVARIANT:`
comment immediately above them explaining why the input is provably valid at
that point (`calibration/storage.rs`'s `read_f32` closure - fixed in-bounds
offsets into a fixed-size array; `redundancy/voter.rs`'s 3-sample unwrap -
only reached after the code above has already established all three samples
are present). A DO-178C-aligned review should treat any *new* `unwrap()`
without such a comment as a defect, not a style nit: an uncaught panic in
flight-critical code has the same effect as any other uncontrolled
termination.

`.expect(...)` calls inside `#[cfg(test)]` modules, and the one-time
`.expect(...)` in `firmware::default_mpc_controller()` (called once at boot,
before any task is spawned - a panic there prevents boot rather than failing
mid-flight, which is the accepted DO-178C-aligned distinction between
init-time and run-time failure handling) are exempted from this rule by
design, not by oversight.

## 7. Register access style (`hal`/`bsp`/`drivers` only)

Raw-pointer `read_volatile`/`write_volatile` through named base-address
constants (`bsp::memory_map`), never through an external peripheral-access
crate abstraction - a deliberate, consistent choice across this workspace
(see `math::matrix`'s and `hal::can`'s module docs for the same rationale
applied elsewhere). `unsafe fn`/`unsafe` blocks here must document, in a
`# Safety` doc comment or an inline `SAFETY:` comment, the specific
precondition the caller must uphold (typically "exclusive access to this
peripheral" or "called before any task claims this resource").

## 8. Integer overflow behavior - known open gap, not yet resolved

The workspace has no `[profile.release]` override in the root `Cargo.toml`,
so `overflow-checks` defaults to `false` in release builds: an integer
overflow silently wraps rather than panicking, in the actual flashed binary.
This was flagged in an earlier review of this repository and has not been
addressed. **A DAL A-aligned coding standard cannot leave this open** -
either enable `overflow-checks = true` in `[profile.release]` (accepting the
panic-on-overflow behavior, and therefore needing every arithmetic operation
in a panic-intolerant path to be justified against rule 6's spirit) or
replace every safety-relevant arithmetic operation with explicit
`checked_*`/`saturating_*`/`wrapping_*` operations and document which was
chosen and why. Tracked as an open item, not silently resolved by this
document.

## 9. `defmt::Format` derive placement

Unrelated to safety directly, but a real, previously-hit build hazard worth
standardizing: deriving `defmt::Format` on a type - even if never logged -
pulls in `defmt`'s runtime logger symbols and breaks linking for host
(`--features std`) builds. Every type in `flight`/`math` that needs
`defmt::Format` for embedded logging gates the derive behind
`#[cfg_attr(not(feature = "std"), derive(defmt::Format))]` (see `MpcError`,
`BitTestId`). Do not derive `defmt::Format` unconditionally on any type in a
crate that supports the `std` feature.
