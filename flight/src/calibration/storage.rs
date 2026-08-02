//! On-FRAM layout for persisted calibration data. Pure encode/decode logic -
//! no dependency on `drivers::Fm25v01` or any hardware type (matching the
//! same separation-of-concerns rationale as `common::can_frames`: firmware
//! glue reads/writes raw bytes via the driver, this module only knows how to
//! interpret them).
//!
//! Layout (36 bytes): magic(4) + version(2) + reserved(2) + accel bias
//! (3xf32=12) + accel scale (3xf32=12) + FNV-1a checksum(4) over everything
//! before it. Blank FRAM (erased/never-written, reads as `0xFF` or `0x00`
//! repeating) fails the magic check immediately; any bit-flip corruption
//! within a plausible-looking record still fails the checksum. Either way,
//! `from_bytes` returns `None` and the caller falls back to
//! `AccelCalibration::identity()` - a missing or corrupt calibration must
//! never be mistaken for a valid one.

use math::Vec3;
use super::accel_cal::AccelCalibration;

const MAGIC: u32 = 0x4A46_4F58; // "JFOX"
const VERSION: u16 = 1;
pub const RECORD_SIZE: usize = 36;

/// Reserved FRAM address for the calibration record.
pub const CALIBRATION_RECORD_ADDR: u16 = 0x0000;
/// Reserved scratch address for `Fm25v01::self_test` - far from the
/// calibration record so a self-test can never corrupt real stored data.
pub const FRAM_SELFTEST_SCRATCH_ADDR: u16 = 0x1000;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CalibrationRecord {
    pub accel: AccelCalibration,
}

fn fnv1a(data: &[u8]) -> u32 {
    const OFFSET: u32 = 0x811c_9dc5;
    const PRIME: u32 = 0x0100_0193;
    let mut hash = OFFSET;
    for &b in data {
        hash ^= b as u32;
        hash = hash.wrapping_mul(PRIME);
    }
    hash
}

impl CalibrationRecord {
    pub fn to_bytes(&self) -> [u8; RECORD_SIZE] {
        let mut buf = [0u8; RECORD_SIZE];
        buf[0..4].copy_from_slice(&MAGIC.to_le_bytes());
        buf[4..6].copy_from_slice(&VERSION.to_le_bytes());
        buf[6..8].copy_from_slice(&0u16.to_le_bytes()); // reserved

        let fields = [
            self.accel.bias.x, self.accel.bias.y, self.accel.bias.z,
            self.accel.scale.x, self.accel.scale.y, self.accel.scale.z,
        ];
        for (i, v) in fields.iter().enumerate() {
            let off = 8 + i * 4;
            buf[off..off + 4].copy_from_slice(&v.to_le_bytes());
        }

        let checksum = fnv1a(&buf[0..32]);
        buf[32..36].copy_from_slice(&checksum.to_le_bytes());
        buf
    }

    pub fn from_bytes(data: &[u8; RECORD_SIZE]) -> Option<Self> {
        let magic = u32::from_le_bytes(data[0..4].try_into().ok()?);
        if magic != MAGIC {
            return None;
        }
        let version = u16::from_le_bytes(data[4..6].try_into().ok()?);
        if version != VERSION {
            return None;
        }
        let stored_checksum = u32::from_le_bytes(data[32..36].try_into().ok()?);
        if fnv1a(&data[0..32]) != stored_checksum {
            return None;
        }

        // INVARIANT: `off+4` is always in bounds for the fixed-size `data`
        // array at every call site below (offsets 8,12,16,20,24,28 against a
        // 36-byte array), so this slice-to-[u8;4] conversion cannot fail;
        // `unwrap()` here does not panic on any reachable input.
        let read_f32 = |off: usize| -> f32 { f32::from_le_bytes(data[off..off + 4].try_into().unwrap()) };
        let bias = Vec3::new(read_f32(8), read_f32(12), read_f32(16));
        let scale = Vec3::new(read_f32(20), read_f32(24), read_f32(28));
        Some(Self { accel: AccelCalibration { bias, scale } })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_record() -> CalibrationRecord {
        CalibrationRecord {
            accel: AccelCalibration { bias: Vec3::new(0.1, -0.2, 0.05), scale: Vec3::new(1.01, 0.99, 1.002) },
        }
    }

    #[test]
    fn roundtrips_through_bytes() {
        let record = sample_record();
        let bytes = record.to_bytes();
        let decoded = CalibrationRecord::from_bytes(&bytes).expect("valid record must decode");
        assert!((decoded.accel.bias.x - record.accel.bias.x).abs() < 1e-6);
        assert!((decoded.accel.bias.y - record.accel.bias.y).abs() < 1e-6);
        assert!((decoded.accel.bias.z - record.accel.bias.z).abs() < 1e-6);
        assert!((decoded.accel.scale.x - record.accel.scale.x).abs() < 1e-6);
        assert!((decoded.accel.scale.y - record.accel.scale.y).abs() < 1e-6);
        assert!((decoded.accel.scale.z - record.accel.scale.z).abs() < 1e-6);
    }

    #[test]
    fn blank_erased_fram_is_rejected() {
        let blank_ff = [0xFFu8; RECORD_SIZE];
        assert!(CalibrationRecord::from_bytes(&blank_ff).is_none());
        let blank_00 = [0x00u8; RECORD_SIZE];
        assert!(CalibrationRecord::from_bytes(&blank_00).is_none());
    }

    #[test]
    fn corrupted_payload_fails_checksum() {
        let record = sample_record();
        let mut bytes = record.to_bytes();
        bytes[10] ^= 0xFF; // flip bits inside the accel-bias field
        assert!(CalibrationRecord::from_bytes(&bytes).is_none());
    }

    #[test]
    fn wrong_version_is_rejected() {
        let record = sample_record();
        let mut bytes = record.to_bytes();
        bytes[4..6].copy_from_slice(&99u16.to_le_bytes());
        // Recompute nothing - even if checksum happened to still match by
        // construction it wouldn't here since checksum covers bytes[0..32]
        // which includes the version field, so this also exercises the
        // checksum path; the version check should reject it first regardless.
        assert!(CalibrationRecord::from_bytes(&bytes).is_none());
    }
}
