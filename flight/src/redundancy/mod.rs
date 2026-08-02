//! Control-path arbitration: chooses between the adaptive-MPC path and the
//! certifiable PID fallback each control tick. Phase 3 (CAN-based TMR across
//! 3 boards) extends this module with `TmrVoter`, the 2-of-3 sensor/command
//! voting logic - kept in the same module since both are ultimately about
//! "what actually drives the mixer this tick."

#![allow(dead_code)]

pub mod voter;
pub use voter::{TmrVoter, VoteResult};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlPath {
    AdaptiveMpc,
    PidFallback,
}

/// Selects `AdaptiveMpc` when the MPC path is currently valid, otherwise
/// `PidFallback`. Tracks consecutive failures for observability/telemetry;
/// selection itself only depends on the current tick's validity (an MPC
/// failure is never "sticky" beyond the tick it occurs on - the moment
/// `mpc_valid` is true again, that tick uses it), since the PID fallback is
/// computed unconditionally every tick and is always ready to hand back to.
pub struct PathSelector {
    consecutive_mpc_failures: u32,
}

impl PathSelector {
    pub fn new() -> Self {
        Self { consecutive_mpc_failures: 0 }
    }

    pub fn select(&mut self, mpc_valid: bool) -> ControlPath {
        if mpc_valid {
            self.consecutive_mpc_failures = 0;
            ControlPath::AdaptiveMpc
        } else {
            self.consecutive_mpc_failures = self.consecutive_mpc_failures.saturating_add(1);
            ControlPath::PidFallback
        }
    }

    pub fn consecutive_mpc_failures(&self) -> u32 {
        self.consecutive_mpc_failures
    }
}

impl Default for PathSelector {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_matches_new() {
        let sel = PathSelector::default();
        assert_eq!(sel.consecutive_mpc_failures(), 0);
    }

    #[test]
    fn valid_mpc_selects_adaptive_path() {
        let mut sel = PathSelector::new();
        assert_eq!(sel.select(true), ControlPath::AdaptiveMpc);
        assert_eq!(sel.consecutive_mpc_failures(), 0);
    }

    #[test]
    fn invalid_mpc_selects_fallback_and_counts_failures() {
        let mut sel = PathSelector::new();
        assert_eq!(sel.select(false), ControlPath::PidFallback);
        assert_eq!(sel.select(false), ControlPath::PidFallback);
        assert_eq!(sel.consecutive_mpc_failures(), 2);
    }

    #[test]
    fn recovery_is_immediate_not_sticky() {
        let mut sel = PathSelector::new();
        sel.select(false);
        sel.select(false);
        assert_eq!(sel.select(true), ControlPath::AdaptiveMpc);
        assert_eq!(sel.consecutive_mpc_failures(), 0);
    }
}
