//! Hand-rolled MAVLink v1 encoder - HEARTBEAT, SYS_STATUS, and ATTITUDE only.
//!
//! Deliberately small and hand-rolled rather than depending on the `mavlink`
//! crate (code-generated from the full dialect, `std`-oriented), matching
//! this codebase's convention elsewhere (`common::can_frames`,
//! `math::matrix` - see the latter's doc comment for the general rationale)
//! and appropriate given this is an interim GCS-compatibility bridge meant
//! to be superseded by a JFOXLink transport later, not a permanent fixture.
//!
//! **Every constant here is sourced from the authoritative
//! `mavlink/c_library_v2` reference implementation, not recalled from
//! memory** - a previous version of this firmware's MAVLink heartbeat
//! shipped without a CRC entirely (see git history / session notes for
//! `firmware/src/main_usb.rs`), which is exactly the failure mode "looks
//! right, silently rejected by every real parser" that motivates being this
//! careful here:
//! - CRC16/MCRF4XX accumulate function and seed: `checksum.h`.
//! - Which bytes get CRC'd and in what order (LEN..MSGID, then payload,
//!   then `CRC_EXTRA` last): `mavlink_helpers.h`'s
//!   `mavlink_finalize_message_buffer`.
//! - Per-message `CRC_EXTRA`, message ID, and payload field layout/order:
//!   each message's own generated header
//!   (`common/mavlink_msg_sys_status.h`, `common/mavlink_msg_attitude.h`,
//!   `minimal/mavlink_msg_heartbeat.h` - HEARTBEAT lives in the `minimal`
//!   dialect that `common` extends, not `common` itself).
//! - Enum values (`MAV_TYPE_QUADROTOR`, `MAV_AUTOPILOT_GENERIC`,
//!   `MAV_STATE_STANDBY`/`_ACTIVE`, `MAV_MODE_FLAG_SAFETY_ARMED`):
//!   `minimal/minimal.h`.
//! - The `#[cfg(test)]` vectors below were generated and independently
//!   round-trip-decoded with a real `pymavlink` install, not hand-computed.

const MAVLINK_STX: u8 = 0xFE;
const SYS_ID: u8 = 1;
const COMP_ID: u8 = 1;

const HEARTBEAT_MSG_ID: u8 = 0;
const HEARTBEAT_CRC_EXTRA: u8 = 50;
const SYS_STATUS_MSG_ID: u8 = 1;
const SYS_STATUS_CRC_EXTRA: u8 = 124;
const ATTITUDE_MSG_ID: u8 = 30;
const ATTITUDE_CRC_EXTRA: u8 = 39;

const MAV_TYPE_QUADROTOR: u8 = 2;
const MAV_AUTOPILOT_GENERIC: u8 = 0;
const MAV_STATE_STANDBY: u8 = 3;
const MAV_STATE_ACTIVE: u8 = 4;
const MAV_MODE_FLAG_SAFETY_ARMED: u8 = 0x80;

/// One step of the CRC-16/MCRF4XX ("X.25") accumulator MAVLink uses - a
/// direct, faithful port of `checksum.h`'s `crc_accumulate`, not a
/// from-scratch reimplementation of the algorithm from a general CRC-16/X.25
/// description (which is why this looks like nibble-swap bit-twiddling
/// rather than the more common table-driven or reflected-shift-register
/// formulations - it's intentionally the exact same arithmetic as the
/// reference C, to eliminate any chance of an equivalent-but-not-identical
/// variant).
fn crc_accumulate(data: u8, crc_accum: &mut u16) {
    let mut tmp: u8 = data ^ (*crc_accum as u8);
    tmp ^= tmp << 4;
    *crc_accum = (*crc_accum >> 8) ^ ((tmp as u16) << 8) ^ ((tmp as u16) << 3) ^ ((tmp as u16) >> 4);
}

/// CRC over an arbitrary buffer, seeded per `checksum.h`'s `crc_init`
/// (`X25_INIT_CRC = 0xFFFF`). Exposed for testing; frame assembly below
/// additionally folds in the per-message `CRC_EXTRA` byte, which this
/// function does not know about (it isn't part of "a buffer").
pub fn crc16_x25(bytes: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &b in bytes {
        crc_accumulate(b, &mut crc);
    }
    crc
}

/// Assembles one MAVLink v1 frame into `out`, which must be exactly
/// `payload.len() + 8` bytes (STX, LEN, SEQ, SYSID, COMPID, MSGID, payload,
/// 2-byte CRC). Panics (via slice indexing) if `out` is the wrong length -
/// a caller bug, not a runtime condition, since every call site here uses a
/// fixed-size array sized to match its own fixed-size payload.
fn build_frame(out: &mut [u8], seq: u8, msg_id: u8, crc_extra: u8, payload: &[u8]) {
    let payload_len = payload.len();
    out[0] = MAVLINK_STX;
    out[1] = payload_len as u8;
    out[2] = seq;
    out[3] = SYS_ID;
    out[4] = COMP_ID;
    out[5] = msg_id;
    out[6..6 + payload_len].copy_from_slice(payload);

    // CRC covers LEN..MSGID and the payload (NOT the leading STX byte), then
    // CRC_EXTRA is accumulated last, appended to the wire but not itself
    // transmitted - see this module's doc comment for the source of this
    // ordering.
    let mut crc: u16 = 0xFFFF;
    for &b in &out[1..6 + payload_len] {
        crc_accumulate(b, &mut crc);
    }
    crc_accumulate(crc_extra, &mut crc);

    out[6 + payload_len] = (crc & 0xFF) as u8;
    out[7 + payload_len] = (crc >> 8) as u8;
}

/// HEARTBEAT (msg 0) - required for GCS autopilot detection. `armed`
/// reflects `flight::arming::ArmingFsm::output_allowed()` in the caller;
/// `system_status` is derived from it (`MAV_STATE_ACTIVE` when armed,
/// `MAV_STATE_STANDBY` otherwise) since this binary has no richer flight-mode
/// state machine to report.
pub fn encode_heartbeat(seq: u8, armed: bool) -> [u8; 17] {
    let mut payload = [0u8; 9];
    payload[0..4].copy_from_slice(&0u32.to_le_bytes()); // custom_mode: unused
    payload[4] = MAV_TYPE_QUADROTOR;
    payload[5] = MAV_AUTOPILOT_GENERIC;
    payload[6] = if armed { MAV_MODE_FLAG_SAFETY_ARMED } else { 0 };
    payload[7] = if armed { MAV_STATE_ACTIVE } else { MAV_STATE_STANDBY };
    payload[8] = 3; // mavlink_version

    let mut out = [0u8; 17];
    build_frame(&mut out, seq, HEARTBEAT_MSG_ID, HEARTBEAT_CRC_EXTRA, &payload);
    out
}

/// SYS_STATUS (msg 1) - v1 payload only (31 bytes; the 3 extra `_extended`
/// sensor-bitmap fields in the generated C struct are a MAVLink v2
/// extension, not part of this v1 frame). `sensors_healthy` reflects
/// `flight::bit::BitReport::all_passed()` in the caller - all three
/// present/enabled/health bitmaps are set identically (`0x1F`, an arbitrary
/// small nonzero bitmap - this binary doesn't track individual per-sensor
/// bits) except health drops to 0 when unhealthy, matching how a real GCS
/// reads this field (a bit clear in `..._health` means "this present/enabled
/// sensor has an error").
pub fn encode_sys_status(seq: u8, sensors_healthy: bool) -> [u8; 39] {
    const SENSOR_BITS: u32 = 0x1F;
    let mut payload = [0u8; 31];
    payload[0..4].copy_from_slice(&SENSOR_BITS.to_le_bytes()); // present
    payload[4..8].copy_from_slice(&SENSOR_BITS.to_le_bytes()); // enabled
    let health = if sensors_healthy { SENSOR_BITS } else { 0 };
    payload[8..12].copy_from_slice(&health.to_le_bytes()); // health
    payload[12..14].copy_from_slice(&250u16.to_le_bytes()); // load (d%, unused - fixed placeholder)
    payload[14..16].copy_from_slice(&0xFFFFu16.to_le_bytes()); // voltage_battery: not sent
    payload[16..18].copy_from_slice(&(-1i16).to_le_bytes()); // current_battery: not sent
    payload[18..20].copy_from_slice(&0u16.to_le_bytes()); // drop_rate_comm
    payload[20..22].copy_from_slice(&0u16.to_le_bytes()); // errors_comm
    payload[22..24].copy_from_slice(&0u16.to_le_bytes()); // errors_count1
    payload[24..26].copy_from_slice(&0u16.to_le_bytes()); // errors_count2
    payload[26..28].copy_from_slice(&0u16.to_le_bytes()); // errors_count3
    payload[28..30].copy_from_slice(&0u16.to_le_bytes()); // errors_count4
    payload[30] = (-1i8) as u8; // battery_remaining: not sent

    let mut out = [0u8; 39];
    build_frame(&mut out, seq, SYS_STATUS_MSG_ID, SYS_STATUS_CRC_EXTRA, &payload);
    out
}

/// ATTITUDE (msg 30) - what drives the GCS attitude indicator. `time_boot_ms`
/// is a monotonic milliseconds-since-boot counter (the caller's own
/// millisecond loop counter is fine - this field is only used by the GCS for
/// staleness/ordering, not an absolute clock). Angles/rates in radians and
/// rad/s, matching `flight::MadgwickFilter::get_euler()`'s convention
/// directly - no unit conversion needed.
#[allow(clippy::too_many_arguments)]
pub fn encode_attitude(seq: u8, time_boot_ms: u32, roll: f32, pitch: f32, yaw: f32, rollspeed: f32, pitchspeed: f32, yawspeed: f32) -> [u8; 36] {
    let mut payload = [0u8; 28];
    payload[0..4].copy_from_slice(&time_boot_ms.to_le_bytes());
    payload[4..8].copy_from_slice(&roll.to_le_bytes());
    payload[8..12].copy_from_slice(&pitch.to_le_bytes());
    payload[12..16].copy_from_slice(&yaw.to_le_bytes());
    payload[16..20].copy_from_slice(&rollspeed.to_le_bytes());
    payload[20..24].copy_from_slice(&pitchspeed.to_le_bytes());
    payload[24..28].copy_from_slice(&yawspeed.to_le_bytes());

    let mut out = [0u8; 36];
    build_frame(&mut out, seq, ATTITUDE_MSG_ID, ATTITUDE_CRC_EXTRA, &payload);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    // Reference vectors generated with a real `pymavlink` install (not
    // hand-computed) and independently round-trip-decoded through
    // pymavlink's own parser before being copied here - see this module's
    // doc comment. Regenerate with the throwaway script noted in
    // docs/do178c/SIL_TEST_PROGRAM.md-adjacent session notes if these ever
    // need re-deriving (different field values, new messages, etc).

    #[test]
    fn heartbeat_disarmed_matches_pymavlink_reference() {
        let expected: [u8; 17] = [254, 9, 0, 1, 1, 0, 0, 0, 0, 0, 2, 0, 0, 3, 3, 25, 133];
        assert_eq!(encode_heartbeat(0, false), expected);
    }

    #[test]
    fn heartbeat_armed_matches_pymavlink_reference() {
        let expected: [u8; 17] = [254, 9, 7, 1, 1, 0, 0, 0, 0, 0, 2, 0, 128, 4, 3, 245, 84];
        assert_eq!(encode_heartbeat(7, true), expected);
    }

    #[test]
    fn sys_status_healthy_matches_pymavlink_reference() {
        let expected: [u8; 39] = [
            254, 31, 3, 1, 1, 1, 31, 0, 0, 0, 31, 0, 0, 0, 31, 0, 0, 0, 250, 0, 255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 105, 51,
        ];
        assert_eq!(encode_sys_status(3, true), expected);
    }

    #[test]
    fn sys_status_unhealthy_matches_pymavlink_reference() {
        let expected: [u8; 39] = [
            254, 31, 4, 1, 1, 1, 31, 0, 0, 0, 31, 0, 0, 0, 0, 0, 0, 0, 250, 0, 255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 255, 109, 176,
        ];
        assert_eq!(encode_sys_status(4, false), expected);
    }

    #[test]
    fn attitude_matches_pymavlink_reference() {
        let expected: [u8; 36] = [
            254, 28, 5, 1, 1, 30, 210, 4, 0, 0, 154, 153, 153, 62, 205, 204, 76, 190, 205, 204, 204, 61, 10, 215, 35, 60, 10, 215, 163, 188, 0, 0, 0, 0, 64, 71,
        ];
        assert_eq!(encode_attitude(5, 1234, 0.3, -0.2, 0.1, 0.01, -0.02, 0.0), expected);
    }

    #[test]
    fn heartbeat_base_mode_reflects_armed_state() {
        let armed = encode_heartbeat(0, true);
        let disarmed = encode_heartbeat(0, false);
        // base_mode is payload byte index 6, at frame offset 6+6=12.
        assert_eq!(armed[12] & MAV_MODE_FLAG_SAFETY_ARMED, MAV_MODE_FLAG_SAFETY_ARMED);
        assert_eq!(disarmed[12] & MAV_MODE_FLAG_SAFETY_ARMED, 0);
    }

    #[test]
    fn crc16_x25_of_empty_buffer_is_the_seed() {
        assert_eq!(crc16_x25(&[]), 0xFFFF);
    }
}
