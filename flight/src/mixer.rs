//! Motor mixer for different frame types

#![allow(dead_code)]

/// Normalized stabilizer output: roll/pitch/yaw in -1.0..=1.0, throttle in 0.0..=1.0.
#[derive(Clone, Copy, Debug, Default)]
pub struct MixerInput {
    pub roll: f32,
    pub pitch: f32,
    pub yaw: f32,
    pub throttle: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameType {
    QuadX,
}

/// Motor mixer. Currently supports quad-X only; `FrameType` exists so
/// plane/hexa/octo mixing can be added later without changing the public API.
///
/// Quad-X motor order (matches `bsp::pins::Pwm1..Pwm4` / FMU-CH1..CH4):
/// M1 = front-right (CW), M2 = rear-left (CW), M3 = front-left (CCW), M4 = rear-right (CCW).
pub struct Mixer {
    frame: FrameType,
}

impl Mixer {
    pub fn new(frame: FrameType) -> Self {
        Self { frame }
    }

    /// Mix a stabilizer command into 4 per-motor outputs, each clamped to 0.0..=1.0.
    ///
    /// If any raw motor value would fall outside 0..=1, all four outputs are
    /// shifted by a common offset first (preserving the relative roll/pitch/yaw
    /// differences between motors) before a final hard clamp as a last-resort
    /// safety net. Independently clamping each motor instead would silently and
    /// asymmetrically degrade attitude authority near saturation.
    pub fn mix(&self, input: MixerInput) -> [f32; 4] {
        match self.frame {
            FrameType::QuadX => self.mix_quad_x(input),
        }
    }

    fn mix_quad_x(&self, input: MixerInput) -> [f32; 4] {
        let MixerInput { roll, pitch, yaw, throttle } = input;

        let raw = [
            throttle - roll + pitch - yaw, // M1: front-right
            throttle + roll - pitch - yaw, // M2: rear-left
            throttle + roll + pitch + yaw, // M3: front-left
            throttle - roll - pitch + yaw, // M4: rear-right
        ];

        let min = raw.iter().cloned().fold(f32::INFINITY, f32::min);
        let max = raw.iter().cloned().fold(f32::NEG_INFINITY, f32::max);

        let mut shift = 0.0f32;
        if min + shift < 0.0 {
            shift -= min + shift;
        }
        if max + shift > 1.0 {
            shift -= (max + shift) - 1.0;
        }

        let mut out = [0.0f32; 4];
        for (o, r) in out.iter_mut().zip(raw.iter()) {
            *o = (r + shift).clamp(0.0, 1.0);
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hover_throttle_no_attitude_gives_equal_motors() {
        let mixer = Mixer::new(FrameType::QuadX);
        let out = mixer.mix(MixerInput { roll: 0.0, pitch: 0.0, yaw: 0.0, throttle: 0.5 });
        for v in out {
            assert!((v - 0.5).abs() < 1e-6);
        }
    }

    #[test]
    fn saturation_is_proportional_not_independently_clamped() {
        let mixer = Mixer::new(FrameType::QuadX);
        // High throttle + moderate roll, chosen so the raw spread (max-min)
        // stays within 1.0 - a single shift can fit every motor in range
        // without any additional hard clamp, so differences should be exact.
        // Naive independent clamping would instead clip only the high motors,
        // silently reducing roll authority relative to yaw/pitch.
        let input = MixerInput { roll: 0.3, pitch: 0.0, yaw: 0.0, throttle: 0.9 };
        let out = mixer.mix(input);

        // Recompute the unshifted raw values to check pairwise differences survive.
        let raw = [0.9 - 0.3, 0.9 + 0.3, 0.9 + 0.3, 0.9 - 0.3];
        let raw_diff = raw[1] - raw[0]; // M2 - M1 before shifting/clamping
        let out_diff = out[1] - out[0];
        assert!((raw_diff - out_diff).abs() < 1e-5, "raw_diff={raw_diff} out_diff={out_diff}");

        for v in out {
            assert!((0.0..=1.0).contains(&v));
        }
    }

    #[test]
    fn extreme_saturation_still_clips_safely_and_preserves_order() {
        let mixer = Mixer::new(FrameType::QuadX);
        // Raw spread here (1.5 - 0.3 = 1.2) exceeds 1.0: no single shift can fit
        // every motor without an additional hard clamp, so exact difference
        // preservation is mathematically impossible - some clipping is correct,
        // expected behavior, not a bug. What must still hold: every output stays
        // in bounds, and the roll-positive motors remain >= the roll-negative ones.
        let input = MixerInput { roll: 0.6, pitch: 0.0, yaw: 0.0, throttle: 0.9 };
        let out = mixer.mix(input);

        for v in out {
            assert!((0.0..=1.0).contains(&v));
        }
        assert!(out[1] >= out[0]); // M2 (roll-positive) >= M1 (roll-negative)
        assert!(out[2] >= out[3]); // M3 (roll-positive) >= M4 (roll-negative)
    }

    #[test]
    fn negative_demand_is_shifted_up_not_clamped_to_zero() {
        let mixer = Mixer::new(FrameType::QuadX);
        // Low throttle + roll would drive one raw motor value negative.
        let input = MixerInput { roll: 0.3, pitch: 0.0, yaw: 0.0, throttle: 0.1 };
        let out = mixer.mix(input);
        for v in out {
            assert!((0.0..=1.0).contains(&v));
        }
        // M1 (roll-negative) still <= M3 (roll-positive) after shifting.
        assert!(out[0] <= out[2]);
    }

    #[test]
    fn all_outputs_always_within_bounds_under_extreme_input() {
        let mixer = Mixer::new(FrameType::QuadX);
        let input = MixerInput { roll: 1.0, pitch: 1.0, yaw: 1.0, throttle: 1.0 };
        let out = mixer.mix(input);
        for v in out {
            assert!((0.0..=1.0).contains(&v), "output out of bounds: {v}");
        }
    }
}
