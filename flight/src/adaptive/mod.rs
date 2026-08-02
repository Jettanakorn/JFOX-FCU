//! Online adaptation layer: `mrac` (slow control-effectiveness estimation
//! feeding the MPC model) and `l1` (fast, filtered disturbance rejection
//! between the MPC's output and the mixer). See each module's doc comment for
//! the full derivation of its piece of the architecture.

pub mod mrac;
pub mod l1;
