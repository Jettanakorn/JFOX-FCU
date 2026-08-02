//! 2-of-3 majority voting over the TMR bus, for both the diagnostic
//! sensor-cross-check layer and the safety-critical command-vote layer (the
//! final gate before `motor_task` once 3-board CAN bring-up exists). Pure,
//! hardware-independent logic - host-testable, no dependency on `hal::can` or
//! `common::can_frames`.
//!
//! Voting on floats means "majority" is "agrees within `tolerance`," not
//! exact equality. With 3 candidates there are 4 possible outcomes: all three
//! agree (`Agreed`, strongest case - use the 3-way average), exactly one pair
//! agrees (`Majority` - use that pair's average, flag the third board as the
//! outlier), no pair agrees (`NoConsensus` - the caller must not trust any of
//! these values for control and should fall back to local-only sensing/the
//! PID path), or fewer than 2 boards reported in this cycle (`InsufficientData`).

#![allow(dead_code)]

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum VoteResult<const N: usize> {
    Agreed([f32; N]),
    Majority { value: [f32; N], outlier_board: u8 },
    NoConsensus,
    InsufficientData,
}

fn within_tolerance<const N: usize>(a: &[f32; N], b: &[f32; N], tolerance: f32) -> bool {
    for i in 0..N {
        if (a[i] - b[i]).abs() > tolerance {
            return false;
        }
    }
    true
}

fn average2<const N: usize>(a: &[f32; N], b: &[f32; N]) -> [f32; N] {
    let mut out = [0.0f32; N];
    for i in 0..N {
        out[i] = (a[i] + b[i]) * 0.5;
    }
    out
}

fn average3<const N: usize>(a: &[f32; N], b: &[f32; N], c: &[f32; N]) -> [f32; N] {
    let mut out = [0.0f32; N];
    for i in 0..N {
        out[i] = (a[i] + b[i] + c[i]) / 3.0;
    }
    out
}

pub struct TmrVoter;

impl TmrVoter {
    /// Core voting logic, generic over the sample width. `samples` is indexed
    /// by board ID (0, 1, 2); `None` means that board didn't report this
    /// cycle (frame lost, timeout, or not yet received).
    pub fn vote<const N: usize>(samples: [Option<[f32; N]>; 3], tolerance: f32) -> VoteResult<N> {
        let present_count = samples.iter().filter(|s| s.is_some()).count();

        if present_count < 2 {
            return VoteResult::InsufficientData;
        }

        if present_count == 2 {
            let mut found: [(u8, [f32; N]); 2] = [(0, [0.0; N]); 2];
            let mut k = 0;
            for (i, s) in samples.iter().enumerate() {
                if let Some(v) = s {
                    found[k] = (i as u8, *v);
                    k += 1;
                }
            }
            let (_, a) = found[0];
            let (_, b) = found[1];
            return if within_tolerance(&a, &b, tolerance) {
                VoteResult::Agreed(average2(&a, &b))
            } else {
                // Only two data points and they disagree: no way to determine
                // which is correct, so this must not be trusted for control.
                VoteResult::NoConsensus
            };
        }

        // present_count == 3
        // INVARIANT: reaching this point means the `present_count < 2` and
        // `present_count == 2` branches above both returned early, so all
        // three of `samples` are `Some` here - these unwraps do not panic.
        let a = samples[0].unwrap();
        let b = samples[1].unwrap();
        let c = samples[2].unwrap();
        let ab = within_tolerance(&a, &b, tolerance);
        let bc = within_tolerance(&b, &c, tolerance);
        let ac = within_tolerance(&a, &c, tolerance);

        if ab && bc && ac {
            return VoteResult::Agreed(average3(&a, &b, &c));
        }
        if ab {
            return VoteResult::Majority { value: average2(&a, &b), outlier_board: 2 };
        }
        if bc {
            return VoteResult::Majority { value: average2(&b, &c), outlier_board: 0 };
        }
        if ac {
            return VoteResult::Majority { value: average2(&a, &c), outlier_board: 1 };
        }
        VoteResult::NoConsensus
    }

    /// Diagnostic cross-check on attitude quaternions (w, x, y, z) - not fed
    /// back into control, only used for fault flagging/telemetry.
    pub fn vote_sensor(samples: [Option<[f32; 4]>; 3], tolerance: f32) -> VoteResult<4> {
        Self::vote(samples, tolerance)
    }

    /// Final motor-command gate: 2-of-3 majority on the mixer output each
    /// board computed independently this tick.
    pub fn vote_command(samples: [Option<[f32; 4]>; 3], tolerance: f32) -> VoteResult<4> {
        Self::vote(samples, tolerance)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_three_agree_averages_all_three() {
        let a = [1.0, 1.0, 1.0, 1.0];
        let b = [1.02, 1.02, 1.02, 1.02];
        let c = [0.98, 0.98, 0.98, 0.98];
        let result = TmrVoter::vote_command([Some(a), Some(b), Some(c)], 0.05);
        match result {
            VoteResult::Agreed(v) => {
                for x in v {
                    assert!((x - 1.0).abs() < 1e-3, "expected ~1.0, got {x}");
                }
            }
            other => panic!("expected Agreed, got {other:?}"),
        }
    }

    #[test]
    fn one_outlier_produces_majority_and_flags_correct_board() {
        let good_a = [0.5, 0.5, 0.5, 0.5];
        let good_b = [0.51, 0.51, 0.51, 0.51];
        let bad_c = [0.9, 0.9, 0.9, 0.9]; // board 2 is the outlier
        let result = TmrVoter::vote_command([Some(good_a), Some(good_b), Some(bad_c)], 0.05);
        match result {
            VoteResult::Majority { value, outlier_board } => {
                assert_eq!(outlier_board, 2);
                for x in value {
                    assert!((x - 0.505).abs() < 1e-2, "expected ~0.505, got {x}");
                }
            }
            other => panic!("expected Majority, got {other:?}"),
        }
    }

    #[test]
    fn non_transitive_pairwise_agreement_resolves_to_the_a_b_pair() {
        // Tolerance agreement is not transitive: a~b and b~c can both hold
        // while a~c does not (a "chain" straddling the tolerance boundary).
        // This must resolve as a 2-of-3 majority on the (a,b) pair, not be
        // mistaken for full 3-way agreement.
        let a = [0.0, 0.0, 0.0, 0.0];
        let b = [0.05, 0.0, 0.0, 0.0]; // |a-b| = 0.05 <= tolerance
        let c = [0.099, 0.0, 0.0, 0.0]; // |b-c| = 0.049 <= tolerance, but |a-c| = 0.099 > tolerance
        let result = TmrVoter::vote_command([Some(a), Some(b), Some(c)], 0.05);
        match result {
            VoteResult::Majority { value, outlier_board } => {
                assert_eq!(outlier_board, 2);
                assert!((value[0] - 0.025).abs() < 1e-3, "expected ~0.025, got {}", value[0]);
            }
            other => panic!("expected Majority on (a,b), got {other:?}"),
        }
    }

    #[test]
    fn outlier_flagging_identifies_board_zero() {
        let bad_a = [0.9, 0.0, 0.0, 0.0];
        let good_b = [0.5, 0.0, 0.0, 0.0];
        let good_c = [0.51, 0.0, 0.0, 0.0];
        let result = TmrVoter::vote_command([Some(bad_a), Some(good_b), Some(good_c)], 0.05);
        assert_eq!(result, VoteResult::Majority { value: [0.505, 0.0, 0.0, 0.0], outlier_board: 0 });
    }

    #[test]
    fn outlier_flagging_identifies_board_one() {
        let good_a = [0.5, 0.0, 0.0, 0.0];
        let bad_b = [0.9, 0.0, 0.0, 0.0];
        let good_c = [0.51, 0.0, 0.0, 0.0];
        let result = TmrVoter::vote_command([Some(good_a), Some(bad_b), Some(good_c)], 0.05);
        assert_eq!(result, VoteResult::Majority { value: [0.505, 0.0, 0.0, 0.0], outlier_board: 1 });
    }

    #[test]
    fn all_three_disagree_gives_no_consensus() {
        let a = [0.1, 0.0, 0.0, 0.0];
        let b = [0.5, 0.0, 0.0, 0.0];
        let c = [0.9, 0.0, 0.0, 0.0];
        let result = TmrVoter::vote_command([Some(a), Some(b), Some(c)], 0.05);
        assert_eq!(result, VoteResult::NoConsensus);
    }

    #[test]
    fn one_missing_board_falls_back_to_two_board_agreement() {
        let a = [0.5, 0.0, 0.0, 0.0];
        let b = [0.51, 0.0, 0.0, 0.0];
        let result = TmrVoter::vote_command([Some(a), Some(b), None], 0.05);
        match result {
            VoteResult::Agreed(v) => assert!((v[0] - 0.505).abs() < 1e-3),
            other => panic!("expected Agreed, got {other:?}"),
        }
    }

    #[test]
    fn two_present_but_disagreeing_gives_no_consensus_not_a_guess() {
        let a = [0.1, 0.0, 0.0, 0.0];
        let b = [0.9, 0.0, 0.0, 0.0];
        let result = TmrVoter::vote_command([Some(a), None, Some(b)], 0.05);
        assert_eq!(result, VoteResult::NoConsensus);
    }

    #[test]
    fn fewer_than_two_boards_present_is_insufficient_data() {
        let a = [0.5, 0.0, 0.0, 0.0];
        assert_eq!(TmrVoter::vote_command([Some(a), None, None], 0.05), VoteResult::InsufficientData);
        assert_eq!(TmrVoter::vote_command([None, None, None], 0.05), VoteResult::InsufficientData);
    }

    #[test]
    fn vote_sensor_uses_the_same_logic_as_vote_command() {
        let a = [1.0, 0.0, 0.0, 0.0];
        let b = [1.0, 0.0, 0.0, 0.0];
        let c = [1.0, 0.0, 0.0, 0.0];
        assert_eq!(TmrVoter::vote_sensor([Some(a), Some(b), Some(c)], 0.01), VoteResult::Agreed(a));
    }
}
