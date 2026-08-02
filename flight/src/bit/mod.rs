//! Built-In Test (BIT): a sequenced set of startup diagnostics plus an
//! aggregate pass/fail, following standard avionics terminology -
//! **PBIT** (Power-on BIT) runs automatically, once, at boot, with exclusive
//! access to the hardware before any task is spawned; **IBIT** (Initiated
//! BIT) is triggerable on demand later (e.g. by a technician) and reports
//! against already-tracked health state rather than re-running invasive
//! hardware transactions concurrently with tasks that are actively using the
//! same peripherals (`imu_task` owns the IMU continuously, for example - see
//! `firmware/src/main.rs`'s `bit_task` for exactly what IBIT does and does
//! not re-check, and why).
//!
//! This module holds only the pure aggregation type (`BitReport`) - actually
//! *running* the hardware tests requires SPI/FRAM access, which lives in
//! `firmware` (matching this codebase's established layering: `flight` stays
//! hardware-agnostic, `firmware` orchestrates real peripherals).

#![allow(dead_code)]

pub const MAX_BIT_TESTS: usize = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[cfg_attr(not(feature = "std"), derive(defmt::Format))]
pub enum BitTestId {
    ImuCommunication,
    GyroCalibration,
    FramSelfTest,
    CcmMemory,
    ArmingFsmInitialState,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BitTestResult {
    pub id: BitTestId,
    pub passed: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct BitReport {
    results: [Option<BitTestResult>; MAX_BIT_TESTS],
    count: usize,
}

impl BitReport {
    pub const fn new() -> Self {
        Self { results: [None; MAX_BIT_TESTS], count: 0 }
    }

    /// Record one test's outcome. Silently drops the result if `MAX_BIT_TESTS`
    /// is exceeded (a programming error, not a runtime condition) rather than
    /// panicking during a boot sequence.
    pub fn record(&mut self, id: BitTestId, passed: bool) {
        if self.count < MAX_BIT_TESTS {
            self.results[self.count] = Some(BitTestResult { id, passed });
            self.count += 1;
        }
    }

    /// True only if at least one test was recorded and every recorded test
    /// passed - an empty report is not vacuously "all passed."
    pub fn all_passed(&self) -> bool {
        self.count > 0 && self.results[..self.count].iter().all(|r| r.map(|res| res.passed).unwrap_or(false))
    }

    pub fn results(&self) -> impl Iterator<Item = BitTestResult> + '_ {
        self.results[..self.count].iter().filter_map(|r| *r)
    }

    pub fn failed_tests(&self) -> impl Iterator<Item = BitTestId> + '_ {
        self.results().filter(|r| !r.passed).map(|r| r.id)
    }
}

impl Default for BitReport {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_report_is_not_all_passed() {
        let report = BitReport::new();
        assert!(!report.all_passed());
    }

    #[test]
    fn default_matches_new() {
        let report = BitReport::default();
        assert!(!report.all_passed());
        assert_eq!(report.results().count(), 0);
    }

    #[test]
    fn all_tests_passing_gives_all_passed() {
        let mut report = BitReport::new();
        report.record(BitTestId::ImuCommunication, true);
        report.record(BitTestId::GyroCalibration, true);
        assert!(report.all_passed());
        assert_eq!(report.failed_tests().count(), 0);
    }

    #[test]
    fn one_failure_fails_the_whole_report_and_is_identified() {
        let mut report = BitReport::new();
        report.record(BitTestId::ImuCommunication, true);
        report.record(BitTestId::FramSelfTest, false);
        report.record(BitTestId::CcmMemory, true);
        assert!(!report.all_passed());

        let mut failed_iter = report.failed_tests();
        assert_eq!(failed_iter.next(), Some(BitTestId::FramSelfTest));
        assert_eq!(failed_iter.next(), None);
    }

    #[test]
    fn recording_past_max_bit_tests_is_silently_dropped_not_a_panic() {
        let mut report = BitReport::new();
        for _ in 0..MAX_BIT_TESTS {
            report.record(BitTestId::ImuCommunication, true);
        }
        // One more than capacity: must not panic, and must not be recorded.
        report.record(BitTestId::GyroCalibration, false);
        assert_eq!(report.results().count(), MAX_BIT_TESTS);
        assert!(report.all_passed(), "the dropped failing result must not affect the aggregate");
    }

    #[test]
    fn results_preserves_insertion_order() {
        let mut report = BitReport::new();
        report.record(BitTestId::CcmMemory, true);
        report.record(BitTestId::ImuCommunication, false);

        let mut ids = report.results().map(|r| r.id);
        assert_eq!(ids.next(), Some(BitTestId::CcmMemory));
        assert_eq!(ids.next(), Some(BitTestId::ImuCommunication));
        assert_eq!(ids.next(), None);
    }
}
