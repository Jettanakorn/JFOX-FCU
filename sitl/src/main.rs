//! SITL: drives the real `flight::` control chain (and, for two scenarios,
//! other real `flight::` subsystems - see `scenarios.rs`) against independent
//! physics/noise models, entirely on the host - no target hardware needed.
//! This is where MPC/L1/MRAC tuning risk gets shaken out before anything
//! touches a real board (see the Phase 4 plan).
//!
//! This binary is a thin CLI wrapper: it runs every scenario in
//! `scenarios::all_scenarios()`, prints PASS/FAIL with a one-line reason, and
//! writes a CSV per scenario for offline plotting. The same scenario
//! functions are also wired into `cargo test` (see `scenarios.rs`'s
//! `#[cfg(test)] mod tests`) - that is the actual automated "SIL test
//! program"; this binary is a convenience for humans who want the CSVs.
//!
//! Run from this directory: `cargo run --release --target <host-triple>`
//! (e.g. `x86_64-pc-windows-msvc` on this machine) - see sitl/README.md.
//!
//! Known simplifications (stated once here rather than scattered):
//! - Control and IMU run at fixed 500Hz/1kHz with a simple substep loop, not
//!   exact RTIC task-timing/jitter.
//! - The plant model (see `plant.rs`) is a stated simplification, not a
//!   claim of aerodynamic accuracy - see that module's doc comment.
//! - Sensor noise is only modeled in `scenario_sensor_noise_robustness` and
//!   `scenario_tmr_voter_fault_detection`; the other scenarios are
//!   noiseless by design (they validate nominal control-chain behavior in
//!   isolation from noise robustness).

mod plant;
mod control_chain;
mod scenarios;

fn main() {
    let results = scenarios::all_scenarios();

    println!();
    println!("=== SITL scenario results ===");
    let mut any_failed = false;
    for r in &results {
        let status = if r.passed { "PASS" } else { "FAIL" };
        println!("[{status}] {}: {}", r.name, r.detail);
        if !r.passed {
            any_failed = true;
        }
    }

    if any_failed {
        std::process::exit(1);
    }
}
