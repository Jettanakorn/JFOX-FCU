//! DWT (Data Watchpoint and Trace) cycle counter, for measuring actual
//! `control_task` execution time on real hardware rather than assuming a
//! budget. See `firmware/src/main.rs::control_task` - the ADMM iteration cap
//! must be sized from a real measurement of headroom after `imu_task`
//! preemption, not guessed.

#![allow(dead_code)]

const DEMCR: u32 = 0xE000_EDFC;
const DWT_CTRL: u32 = 0xE000_1000;
const DWT_CYCCNT: u32 = 0xE000_1004;

const TRCENA: u32 = 1 << 24;
const CYCCNTENA: u32 = 1 << 0;

pub struct Dwt;

impl Dwt {
    /// Enable the free-running cycle counter. Idempotent - safe to call more
    /// than once.
    ///
    /// # Safety
    ///
    /// Caller must ensure this runs on a Cortex-M target with DWT present
    /// (true for the Cortex-M4F this firmware targets).
    pub unsafe fn enable() {
        let demcr = DEMCR as *mut u32;
        demcr.write_volatile(demcr.read_volatile() | TRCENA);

        let ctrl = DWT_CTRL as *mut u32;
        ctrl.write_volatile(ctrl.read_volatile() | CYCCNTENA);
    }

    /// Current cycle count. Wraps every ~2^32 cycles (~23.9s at 180MHz).
    pub fn cycle_count() -> u32 {
        unsafe { (DWT_CYCCNT as *const u32).read_volatile() }
    }

    /// Elapsed cycles since `start`. Correctly handles a single wraparound;
    /// two or more wraps between measurements are indistinguishable from one
    /// and will under-report - not a concern for the sub-millisecond,
    /// single-control-tick measurements this exists for.
    pub fn elapsed_since(start: u32) -> u32 {
        Self::cycle_count().wrapping_sub(start)
    }
}
