//! Wire format for the inter-board TMR voting bus, carried over `hal::can`.
//! Pure encode/decode logic - deliberately has no dependency on `hal` (see
//! this module's role in the Phase 3 plan: shared by `hal`-adjacent firmware
//! code and `flight::redundancy` without creating a `common -> hal`
//! dependency). Firmware glue converts between these domain types and
//! `hal::can::CanFrame`.
//!
//! **Command-vote frame**: the final motor mixer output, one frame per board
//! per control tick, safety-critical - fits one classic-CAN frame with no
//! fragmentation.
//!
//! **Sensor cross-check frame**: attitude quaternion only (not raw
//! gyro/accel) - diagnostic, not control-critical. A quaternion (4 x i16)
//! also fits in exactly one 8-byte frame, so no fragmentation is needed here
//! either; the multi-frame reassembly complexity flagged as a risk in the
//! Phase 3 plan is avoided entirely by this scoping choice rather than
//! implemented.
//!
//! Board ID (0-2) and frame type are packed into the 11-bit arbitration ID,
//! not the payload, so a receiver can filter/route without touching data
//! bytes.

#![allow(dead_code)]

/// Fixed base within the 11-bit standard-ID space (0x000-0x7FF) that
/// identifies TMR-bus traffic; arbitrary but must not collide with any other
/// CAN traffic sharing this bus. Low 4 bits are reserved for board_id (2
/// bits) + frame_type (2 bits), so this must be a multiple of 16.
pub const TMR_BASE_ID: u16 = 0x100;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FrameType {
    CommandVote,
    SensorCrossCheck,
}

impl FrameType {
    const fn to_bits(self) -> u16 {
        match self {
            FrameType::CommandVote => 0,
            FrameType::SensorCrossCheck => 1,
        }
    }

    const fn from_bits(bits: u16) -> Option<Self> {
        match bits {
            0 => Some(FrameType::CommandVote),
            1 => Some(FrameType::SensorCrossCheck),
            _ => None,
        }
    }
}

pub fn arbitration_id(board_id: u8, frame_type: FrameType) -> u16 {
    TMR_BASE_ID | ((board_id as u16 & 0x3) << 2) | frame_type.to_bits()
}

pub fn parse_arbitration_id(id: u16) -> Option<(u8, FrameType)> {
    if (id & !0xF) != TMR_BASE_ID {
        return None;
    }
    let board_id = ((id >> 2) & 0x3) as u8;
    let frame_type = FrameType::from_bits(id & 0x3)?;
    Some((board_id, frame_type))
}

const COMMAND_SCALE: f32 = 10000.0; // 0.0001 resolution over the 0.0..=1.0 motor-duty range
const QUAT_SCALE: f32 = 32767.0; // near-full i16 resolution over the -1.0..=1.0 quaternion-component range

fn quantize(value: f32, scale: f32, clamp_lo: f32, clamp_hi: f32) -> i16 {
    libm::roundf(value.clamp(clamp_lo, clamp_hi) * scale) as i16
}

fn dequantize(raw: i16, scale: f32) -> f32 {
    raw as f32 / scale
}

fn pack_4x_i16(values: [i16; 4]) -> [u8; 8] {
    let mut data = [0u8; 8];
    for (i, v) in values.iter().enumerate() {
        let b = v.to_le_bytes();
        data[i * 2] = b[0];
        data[i * 2 + 1] = b[1];
    }
    data
}

fn unpack_4x_i16(data: &[u8; 8]) -> [i16; 4] {
    let mut out = [0i16; 4];
    for i in 0..4 {
        out[i] = i16::from_le_bytes([data[i * 2], data[i * 2 + 1]]);
    }
    out
}

/// Final mixer output, one frame per board per control tick.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CommandVoteFrame {
    pub board_id: u8,
    /// Per-motor duty cycle, 0.0..=1.0 (matches `flight::mixer::Mixer::mix`'s output).
    pub motor_commands: [f32; 4],
}

impl CommandVoteFrame {
    pub fn to_can_bytes(&self) -> (u16, [u8; 8]) {
        let id = arbitration_id(self.board_id, FrameType::CommandVote);
        let quantized = self.motor_commands.map(|v| quantize(v, COMMAND_SCALE, 0.0, 1.0));
        (id, pack_4x_i16(quantized))
    }

    pub fn from_can_bytes(id: u16, data: &[u8; 8]) -> Option<Self> {
        let (board_id, frame_type) = parse_arbitration_id(id)?;
        if frame_type != FrameType::CommandVote {
            return None;
        }
        let raw = unpack_4x_i16(data);
        let motor_commands = raw.map(|v| dequantize(v, COMMAND_SCALE));
        Some(Self { board_id, motor_commands })
    }
}

/// Attitude quaternion (w, x, y, z) for diagnostic cross-checking - not fed
/// back into control, only used for `TmrVoter::vote_sensor`-style fault
/// detection.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SensorCrossCheckFrame {
    pub board_id: u8,
    pub quaternion: [f32; 4],
}

impl SensorCrossCheckFrame {
    pub fn to_can_bytes(&self) -> (u16, [u8; 8]) {
        let id = arbitration_id(self.board_id, FrameType::SensorCrossCheck);
        let quantized = self.quaternion.map(|v| quantize(v, QUAT_SCALE, -1.0, 1.0));
        (id, pack_4x_i16(quantized))
    }

    pub fn from_can_bytes(id: u16, data: &[u8; 8]) -> Option<Self> {
        let (board_id, frame_type) = parse_arbitration_id(id)?;
        if frame_type != FrameType::SensorCrossCheck {
            return None;
        }
        let raw = unpack_4x_i16(data);
        let quaternion = raw.map(|v| dequantize(v, QUAT_SCALE));
        Some(Self { board_id, quaternion })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arbitration_id_roundtrips_for_every_board_and_type() {
        for board_id in 0u8..3 {
            for frame_type in [FrameType::CommandVote, FrameType::SensorCrossCheck] {
                let id = arbitration_id(board_id, frame_type);
                let (decoded_board, decoded_type) = parse_arbitration_id(id).expect("valid TMR id must parse");
                assert_eq!(decoded_board, board_id);
                assert_eq!(decoded_type, frame_type);
            }
        }
    }

    #[test]
    fn parse_arbitration_id_rejects_foreign_ids() {
        // Same low 4 bits, different base - must not be mistaken for TMR traffic.
        assert!(parse_arbitration_id(0x200).is_none());
        assert!(parse_arbitration_id(0x000).is_none());
    }

    #[test]
    fn parse_arbitration_id_rejects_a_reserved_frame_type_value() {
        // FrameType only defines bit patterns 0 and 1; the low 2 bits of the
        // id can also be 2 or 3 (a foreign/corrupted frame on this base ID),
        // which must be rejected rather than silently decoded as one of the
        // two known types.
        let id_with_reserved_type = TMR_BASE_ID | 0b10; // board_id=0, frame_type bits=2
        assert!(parse_arbitration_id(id_with_reserved_type).is_none());
    }

    #[test]
    fn command_vote_frame_roundtrips_within_quantization_error() {
        let original = CommandVoteFrame { board_id: 1, motor_commands: [0.0, 0.25, 0.5, 1.0] };
        let (id, data) = original.to_can_bytes();
        let decoded = CommandVoteFrame::from_can_bytes(id, &data).expect("valid frame must decode");
        assert_eq!(decoded.board_id, 1);
        for i in 0..4 {
            assert!((decoded.motor_commands[i] - original.motor_commands[i]).abs() < 1e-3);
        }
    }

    #[test]
    fn command_vote_frame_clamps_out_of_range_input() {
        let original = CommandVoteFrame { board_id: 0, motor_commands: [-0.5, 1.5, 0.0, 1.0] };
        let (id, data) = original.to_can_bytes();
        let decoded = CommandVoteFrame::from_can_bytes(id, &data).unwrap();
        assert!((decoded.motor_commands[0] - 0.0).abs() < 1e-3);
        assert!((decoded.motor_commands[1] - 1.0).abs() < 1e-3);
    }

    #[test]
    fn command_vote_decode_rejects_sensor_frame_bytes() {
        let sensor = SensorCrossCheckFrame { board_id: 2, quaternion: [1.0, 0.0, 0.0, 0.0] };
        let (id, data) = sensor.to_can_bytes();
        assert!(CommandVoteFrame::from_can_bytes(id, &data).is_none());
    }

    #[test]
    fn sensor_cross_check_frame_roundtrips_within_quantization_error() {
        let original = SensorCrossCheckFrame { board_id: 2, quaternion: [0.707, 0.0, 0.707, 0.0] };
        let (id, data) = original.to_can_bytes();
        let decoded = SensorCrossCheckFrame::from_can_bytes(id, &data).expect("valid frame must decode");
        assert_eq!(decoded.board_id, 2);
        for i in 0..4 {
            assert!((decoded.quaternion[i] - original.quaternion[i]).abs() < 1e-3);
        }
    }

    #[test]
    fn sensor_frame_decode_rejects_command_frame_bytes() {
        let cmd = CommandVoteFrame { board_id: 0, motor_commands: [0.1, 0.2, 0.3, 0.4] };
        let (id, data) = cmd.to_can_bytes();
        assert!(SensorCrossCheckFrame::from_can_bytes(id, &data).is_none());
    }
}
