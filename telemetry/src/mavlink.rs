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
const SCALED_IMU_MSG_ID: u8 = 26;
const SCALED_IMU_CRC_EXTRA: u8 = 170;
const SCALED_PRESSURE_MSG_ID: u8 = 29;
const SCALED_PRESSURE_CRC_EXTRA: u8 = 115;

/// `MAV_SYS_STATUS_SENSOR` bits, for the three SYS_STATUS bitmaps. Only the
/// ones this firmware can actually report are defined - a bit set in
/// `present` that nothing ever populates tells a GCS a lie it cannot check.
pub mod sensor_bits {
    pub const GYRO_3D: u32 = 0x0000_0001;
    pub const ACCEL_3D: u32 = 0x0000_0002;
    pub const MAG_3D: u32 = 0x0000_0004;
    pub const ABSOLUTE_PRESSURE: u32 = 0x0000_0008;
    pub const GYRO_3D_2: u32 = 0x0002_0000;
    pub const ACCEL_3D_2: u32 = 0x0004_0000;
}

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
    let health = if sensors_healthy { SENSOR_BITS } else { 0 };
    encode_sys_status_detailed(seq, SENSOR_BITS, SENSOR_BITS, health)
}

/// SYS_STATUS with real per-sensor bitmaps, for callers that have actually
/// probed the bus and know which devices answered.
///
/// `present`/`enabled`/`health` are `MAV_SYS_STATUS_SENSOR` bitmaps - see
/// [`sensor_bits`]. A GCS reads a bit clear in `health` but set in
/// `present` as "this sensor exists and has failed", which is why a sensor
/// that was never detected must be absent from *all three* maps rather than
/// present-and-unhealthy.
///
/// Note the wire order is not the declaration order: MAVLink sorts fields by
/// descending type size, which moves `battery_remaining` (int8) from its
/// declared position after `current_battery` to the very end of the payload.
/// Getting that wrong produces a frame with a valid CRC and wrong contents,
/// which is worse than one that fails to parse.
pub fn encode_sys_status_detailed(
    seq: u8,
    present: u32,
    enabled: u32,
    health: u32,
) -> [u8; 39] {
    let mut payload = [0u8; 31];
    payload[0..4].copy_from_slice(&present.to_le_bytes());
    payload[4..8].copy_from_slice(&enabled.to_le_bytes());
    payload[8..12].copy_from_slice(&health.to_le_bytes());
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

/// SCALED_IMU (msg 26) - raw-ish IMU in engineering units, which is what a
/// GCS plots when you want to see the sensor rather than the estimate.
///
/// Units are fixed by the dialect and are *not* the units this firmware works
/// in internally, so the caller converts:
/// - accel: milli-g (`mG`)
/// - gyro: milli-radians/second (`mrad/s`)
/// - mag: milli-gauss (`mgauss`)
///
/// Pass zeros for `*mag` when no magnetometer is fitted or read; a GCS plots
/// a flat zero trace, which reads as "not measured" rather than as a bogus
/// field value.
#[allow(clippy::too_many_arguments)]
pub fn encode_scaled_imu(
    seq: u8,
    time_boot_ms: u32,
    xacc: i16, yacc: i16, zacc: i16,
    xgyro: i16, ygyro: i16, zgyro: i16,
    xmag: i16, ymag: i16, zmag: i16,
) -> [u8; 30] {
    let mut payload = [0u8; 22];
    payload[0..4].copy_from_slice(&time_boot_ms.to_le_bytes());
    payload[4..6].copy_from_slice(&xacc.to_le_bytes());
    payload[6..8].copy_from_slice(&yacc.to_le_bytes());
    payload[8..10].copy_from_slice(&zacc.to_le_bytes());
    payload[10..12].copy_from_slice(&xgyro.to_le_bytes());
    payload[12..14].copy_from_slice(&ygyro.to_le_bytes());
    payload[14..16].copy_from_slice(&zgyro.to_le_bytes());
    payload[16..18].copy_from_slice(&xmag.to_le_bytes());
    payload[18..20].copy_from_slice(&ymag.to_le_bytes());
    payload[20..22].copy_from_slice(&zmag.to_le_bytes());

    let mut out = [0u8; 30];
    build_frame(&mut out, seq, SCALED_IMU_MSG_ID, SCALED_IMU_CRC_EXTRA, &payload);
    out
}

/// SCALED_PRESSURE (msg 29) - barometer, in the dialect's units:
/// `press_abs`/`press_diff` in hectopascals (mbar), `temperature` in
/// centidegrees Celsius. `press_diff` is 0 here: this board has no
/// differential (airspeed) sensor.
pub fn encode_scaled_pressure(
    seq: u8,
    time_boot_ms: u32,
    press_abs_hpa: f32,
    temperature_cdeg: i16,
) -> [u8; 22] {
    let mut payload = [0u8; 14];
    payload[0..4].copy_from_slice(&time_boot_ms.to_le_bytes());
    payload[4..8].copy_from_slice(&press_abs_hpa.to_le_bytes());
    payload[8..12].copy_from_slice(&0.0f32.to_le_bytes()); // press_diff: no airspeed sensor
    payload[12..14].copy_from_slice(&temperature_cdeg.to_le_bytes());

    let mut out = [0u8; 22];
    build_frame(&mut out, seq, SCALED_PRESSURE_MSG_ID, SCALED_PRESSURE_CRC_EXTRA, &payload);
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

// ===========================================================================
// Receive path
// ===========================================================================

const COMMAND_LONG_MSG_ID: u8 = 76;
const COMMAND_LONG_CRC_EXTRA: u8 = 152;
const COMMAND_LONG_PAYLOAD_LEN: u8 = 33;
const COMMAND_ACK_MSG_ID: u8 = 77;
const COMMAND_ACK_CRC_EXTRA: u8 = 143;
const PARAM_REQUEST_READ_MSG_ID: u8 = 20;
const PARAM_REQUEST_READ_CRC_EXTRA: u8 = 214;
const PARAM_REQUEST_LIST_MSG_ID: u8 = 21;
const PARAM_REQUEST_LIST_CRC_EXTRA: u8 = 159;
const PARAM_VALUE_MSG_ID: u8 = 22;
const PARAM_VALUE_CRC_EXTRA: u8 = 220;
const PARAM_SET_MSG_ID: u8 = 23;
const PARAM_SET_CRC_EXTRA: u8 = 168;
const AUTOPILOT_VERSION_MSG_ID: u8 = 148;
const AUTOPILOT_VERSION_CRC_EXTRA: u8 = 178;
const STATUSTEXT_MSG_ID: u8 = 253;
const STATUSTEXT_CRC_EXTRA: u8 = 83;

/// MAVLink's fixed-width `param_id` field.
pub const PARAM_ID_LEN: usize = 16;

/// `MAV_CMD` values this firmware recognises.
pub mod cmd {
    pub const COMPONENT_ARM_DISARM: u16 = 400;
    pub const NAV_RETURN_TO_LAUNCH: u16 = 20;
    pub const REQUEST_AUTOPILOT_CAPABILITIES: u16 = 520;
}

/// `MAV_RESULT` values, for COMMAND_ACK.
pub mod result {
    pub const ACCEPTED: u8 = 0;
    pub const TEMPORARILY_REJECTED: u8 = 1;
    pub const DENIED: u8 = 2;
    pub const UNSUPPORTED: u8 = 3;
    pub const FAILED: u8 = 4;
}

/// A decoded, CRC-validated inbound message.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Message {
    /// HEARTBEAT from a GCS. Carries nothing this firmware needs, but its
    /// *arrival* is the link-liveness signal a failsafe would time out on.
    Heartbeat,
    CommandLong {
        command: u16,
        param1: f32,
        target_system: u8,
        target_component: u8,
        confirmation: u8,
    },
    /// GCS wants the whole parameter set streamed to it.
    ParamRequestList,
    /// GCS wants one parameter. Either by index, or by name when
    /// `param_index` is -1 (which is how a GCS re-requests a parameter it
    /// dropped, since it knows the name but not necessarily the index).
    ParamRequestRead {
        param_index: i16,
        param_id: [u8; PARAM_ID_LEN],
    },
    ParamSet {
        param_id: [u8; PARAM_ID_LEN],
        param_value: f32,
    },
}

/// `CRC_EXTRA` for the messages this parser accepts.
///
/// A MAVLink frame cannot be CRC-checked without knowing its message's
/// `CRC_EXTRA`, so an unknown message ID is *unverifiable*, not merely
/// unsupported. Those frames are dropped rather than passed along
/// unvalidated - accepting a command whose integrity was never checked is
/// exactly the failure a command link must not have.
fn crc_extra_for(msg_id: u8) -> Option<u8> {
    match msg_id {
        HEARTBEAT_MSG_ID => Some(HEARTBEAT_CRC_EXTRA),
        COMMAND_LONG_MSG_ID => Some(COMMAND_LONG_CRC_EXTRA),
        PARAM_REQUEST_READ_MSG_ID => Some(PARAM_REQUEST_READ_CRC_EXTRA),
        PARAM_REQUEST_LIST_MSG_ID => Some(PARAM_REQUEST_LIST_CRC_EXTRA),
        PARAM_SET_MSG_ID => Some(PARAM_SET_CRC_EXTRA),
        _ => None,
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum RxState {
    /// Hunting for STX.
    Idle,
    Len,
    Seq,
    SysId,
    CompId,
    MsgId,
    Payload,
    CrcLo,
    CrcHi,
}

/// Incremental MAVLink v1 frame parser.
///
/// Fed one byte at a time; returns a [`Message`] only for a frame whose CRC
/// (including `CRC_EXTRA`) validates and whose ID this firmware understands.
/// Resynchronises on its own - a corrupt frame costs the frame, not the link.
pub struct Parser {
    state: RxState,
    len: u8,
    seq: u8,
    sys_id: u8,
    comp_id: u8,
    msg_id: u8,
    payload: [u8; 255],
    idx: usize,
    crc_lo: u8,
    /// Frames dropped for a CRC mismatch. A link that is up but corrupting is
    /// worth being able to see, rather than presenting as silence.
    pub crc_errors: u32,
    /// Frames dropped because the message ID has no known `CRC_EXTRA`.
    pub unknown_msgs: u32,
}

impl Default for Parser {
    fn default() -> Self {
        Self::new()
    }
}

impl Parser {
    pub const fn new() -> Self {
        Self {
            state: RxState::Idle,
            len: 0,
            seq: 0,
            sys_id: 0,
            comp_id: 0,
            msg_id: 0,
            payload: [0u8; 255],
            idx: 0,
            crc_lo: 0,
            crc_errors: 0,
            unknown_msgs: 0,
        }
    }

    /// Feed one received byte. Returns a decoded message only when a frame
    /// completes *and* its CRC validates *and* its ID is one we understand.
    pub fn push(&mut self, b: u8) -> Option<Message> {
        match self.state {
            RxState::Idle => {
                if b == MAVLINK_STX {
                    self.state = RxState::Len;
                }
                None
            }
            RxState::Len => {
                self.len = b;
                self.idx = 0;
                self.state = RxState::Seq;
                None
            }
            RxState::Seq => {
                self.seq = b;
                self.state = RxState::SysId;
                None
            }
            RxState::SysId => {
                self.sys_id = b;
                self.state = RxState::CompId;
                None
            }
            RxState::CompId => {
                self.comp_id = b;
                self.state = RxState::MsgId;
                None
            }
            RxState::MsgId => {
                self.msg_id = b;
                // A zero-length payload jumps straight to the checksum.
                self.state = if self.len == 0 { RxState::CrcLo } else { RxState::Payload };
                None
            }
            RxState::Payload => {
                self.payload[self.idx] = b;
                self.idx += 1;
                if self.idx >= self.len as usize {
                    self.state = RxState::CrcLo;
                }
                None
            }
            RxState::CrcLo => {
                self.crc_lo = b;
                self.state = RxState::CrcHi;
                None
            }
            RxState::CrcHi => {
                let received = ((b as u16) << 8) | self.crc_lo as u16;
                self.state = RxState::Idle;
                self.validate(received)
            }
        }
    }

    /// Recompute the frame's CRC and decode it if it holds up.
    fn validate(&mut self, received: u16) -> Option<Message> {
        // Unknown IDs cannot be checked at all - their CRC_EXTRA is unknown -
        // so they are counted and dropped, never guessed at.
        let Some(crc_extra) = crc_extra_for(self.msg_id) else {
            self.unknown_msgs = self.unknown_msgs.wrapping_add(1);
            return None;
        };

        // Same coverage as the transmit path: LEN..MSGID, then payload, then
        // CRC_EXTRA last. The STX byte is not included.
        let mut crc: u16 = 0xFFFF;
        crc_accumulate(self.len, &mut crc);
        crc_accumulate(self.seq, &mut crc);
        crc_accumulate(self.sys_id, &mut crc);
        crc_accumulate(self.comp_id, &mut crc);
        crc_accumulate(self.msg_id, &mut crc);
        for &p in &self.payload[..self.len as usize] {
            crc_accumulate(p, &mut crc);
        }
        crc_accumulate(crc_extra, &mut crc);

        if crc != received {
            self.crc_errors = self.crc_errors.wrapping_add(1);
            return None;
        }

        self.decode()
    }

    fn decode(&self) -> Option<Message> {
        match self.msg_id {
            HEARTBEAT_MSG_ID => Some(Message::Heartbeat),
            COMMAND_LONG_MSG_ID => {
                // A short payload with a valid CRC is a truncated sender, not
                // corruption. Decoding it would read stale bytes from the
                // buffer, so it is refused.
                if self.len < COMMAND_LONG_PAYLOAD_LEN {
                    return None;
                }
                let p = &self.payload;
                Some(Message::CommandLong {
                    param1: f32::from_le_bytes([p[0], p[1], p[2], p[3]]),
                    command: u16::from_le_bytes([p[28], p[29]]),
                    target_system: p[30],
                    target_component: p[31],
                    confirmation: p[32],
                })
            }
            PARAM_REQUEST_LIST_MSG_ID => Some(Message::ParamRequestList),

            PARAM_REQUEST_READ_MSG_ID => {
                if self.len < 20 {
                    return None;
                }
                let p = &self.payload;
                let mut id = [0u8; PARAM_ID_LEN];
                id.copy_from_slice(&p[4..4 + PARAM_ID_LEN]);
                Some(Message::ParamRequestRead {
                    param_index: i16::from_le_bytes([p[0], p[1]]),
                    param_id: id,
                })
            }

            PARAM_SET_MSG_ID => {
                if self.len < 23 {
                    return None;
                }
                let p = &self.payload;
                let mut id = [0u8; PARAM_ID_LEN];
                id.copy_from_slice(&p[6..6 + PARAM_ID_LEN]);
                Some(Message::ParamSet {
                    param_value: f32::from_le_bytes([p[0], p[1], p[2], p[3]]),
                    param_id: id,
                })
            }

            _ => None,
        }
    }
}

/// PARAM_VALUE (msg 22) - one parameter, and the count/index pair a GCS uses
/// to know whether it has the whole set yet.
///
/// `param_count` must be the same on every message of a stream, and
/// `param_index` must be the parameter's real position: a GCS tracks which
/// indices it has seen and re-requests the gaps. Sending a running counter
/// instead of the true index is a classic way to make a parameter download
/// hang at 99%.
pub fn encode_param_value(
    seq: u8,
    param_id: &[u8; PARAM_ID_LEN],
    param_value: f32,
    param_type: u8,
    param_count: u16,
    param_index: u16,
) -> [u8; 33] {
    let mut payload = [0u8; 25];
    payload[0..4].copy_from_slice(&param_value.to_le_bytes());
    payload[4..6].copy_from_slice(&param_count.to_le_bytes());
    payload[6..8].copy_from_slice(&param_index.to_le_bytes());
    payload[8..8 + PARAM_ID_LEN].copy_from_slice(param_id);
    payload[24] = param_type;

    let mut out = [0u8; 33];
    build_frame(&mut out, seq, PARAM_VALUE_MSG_ID, PARAM_VALUE_CRC_EXTRA, &payload);
    out
}

/// AUTOPILOT_VERSION (msg 148) - answers a GCS's capabilities request.
///
/// Everything here is deliberately modest. `capabilities` advertises only
/// PARAM_FLOAT, because that is genuinely all this firmware supports; claiming
/// mission or FTP capability would make a GCS attempt protocols that would then
/// silently fail.
pub fn encode_autopilot_version(seq: u8, flight_sw_version: u32) -> [u8; 68] {
    /// MAV_PROTOCOL_CAPABILITY_PARAM_FLOAT
    const CAP_PARAM_FLOAT: u64 = 1;

    let mut payload = [0u8; 60];
    payload[0..8].copy_from_slice(&CAP_PARAM_FLOAT.to_le_bytes()); // capabilities
    payload[8..16].copy_from_slice(&0u64.to_le_bytes()); // uid: none
    payload[16..20].copy_from_slice(&flight_sw_version.to_le_bytes());
    payload[20..24].copy_from_slice(&0u32.to_le_bytes()); // middleware_sw_version
    payload[24..28].copy_from_slice(&0u32.to_le_bytes()); // os_sw_version
    payload[28..32].copy_from_slice(&0u32.to_le_bytes()); // board_version
    payload[32..34].copy_from_slice(&0u16.to_le_bytes()); // vendor_id
    payload[34..36].copy_from_slice(&0u16.to_le_bytes()); // product_id
    // flight/middleware/os custom version: 8 bytes each, left zero.

    let mut out = [0u8; 68];
    build_frame(&mut out, seq, AUTOPILOT_VERSION_MSG_ID, AUTOPILOT_VERSION_CRC_EXTRA, &payload);
    out
}

/// `MAV_SEVERITY` values for STATUSTEXT.
pub mod severity {
    pub const CRITICAL: u8 = 2;
    pub const ERROR: u8 = 3;
    pub const WARNING: u8 = 4;
    pub const NOTICE: u8 = 5;
    pub const INFO: u8 = 6;
}

/// STATUSTEXT (msg 253) - free text into the GCS message panel.
///
/// This is the only diagnostic channel this firmware has to an operator
/// without a debug probe. `defmt` output requires SWD hardware that is not
/// always available, so anything a person needs to see at boot - which sensors
/// answered, which failed - has to come out here or it is invisible.
///
/// `text` is a fixed 50-byte field, NUL padded, and is truncated rather than
/// refused if longer: losing the tail of a message is better than losing the
/// message.
pub fn encode_statustext(seq: u8, severity: u8, text: &[u8]) -> [u8; 59] {
    let mut payload = [0u8; 51];
    payload[0] = severity;
    let n = if text.len() > 50 { 50 } else { text.len() };
    payload[1..1 + n].copy_from_slice(&text[..n]);

    let mut out = [0u8; 59];
    build_frame(&mut out, seq, STATUSTEXT_MSG_ID, STATUSTEXT_CRC_EXTRA, &payload);
    out
}

/// COMMAND_ACK (msg 77) - every COMMAND_LONG must be answered, including ones
/// that are refused. A GCS that gets no ACK retries, and a command link that
/// silently ignores what it cannot do is indistinguishable from a dead one.
pub fn encode_command_ack(seq: u8, command: u16, result: u8) -> [u8; 11] {
    let mut payload = [0u8; 3];
    payload[0..2].copy_from_slice(&command.to_le_bytes());
    payload[2] = result;

    let mut out = [0u8; 11];
    build_frame(&mut out, seq, COMMAND_ACK_MSG_ID, COMMAND_ACK_CRC_EXTRA, &payload);
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
    fn scaled_imu_matches_pymavlink_reference() {
        let expected: [u8; 30] = [
            0xFE, 0x16, 0x07, 0x01, 0x01, 0x1A, 0x40, 0xE2, 0x01, 0x00, 0xF4, 0xFF, 0x22, 0x00,
            0xE8, 0x03, 0xFB, 0xFF, 0x06, 0x00, 0xF9, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x3B, 0x7B,
        ];
        assert_eq!(
            encode_scaled_imu(7, 123456, -12, 34, 1000, -5, 6, -7, 0, 0, 0),
            expected
        );
    }

    #[test]
    fn scaled_pressure_matches_pymavlink_reference() {
        let expected: [u8; 22] = [
            0xFE, 0x0E, 0x08, 0x01, 0x01, 0x1D, 0x40, 0xE2, 0x01, 0x00, 0x00, 0x50, 0x7D, 0x44,
            0x00, 0x00, 0x00, 0x00, 0xD7, 0x07, 0x74, 0x1E,
        ];
        assert_eq!(encode_scaled_pressure(8, 123456, 1013.25, 2007), expected);
    }

    /// The refactor that introduced `encode_sys_status_detailed` must not have
    /// changed what `encode_sys_status` puts on the wire.
    #[test]
    fn sys_status_delegates_without_changing_the_frame() {
        assert_eq!(
            encode_sys_status(3, true),
            encode_sys_status_detailed(3, 0x1F, 0x1F, 0x1F)
        );
        assert_eq!(
            encode_sys_status(4, false),
            encode_sys_status_detailed(4, 0x1F, 0x1F, 0x00)
        );
    }

    /// A sensor that was never detected must be absent from all three bitmaps.
    /// Present-but-unhealthy means "fitted and broken" to a GCS, which is a
    /// different and wrong claim.
    #[test]
    fn absent_sensor_is_absent_from_every_bitmap() {
        use sensor_bits::*;
        let present = GYRO_3D | ACCEL_3D; // IMU only: no baro, no mag
        let frame = encode_sys_status_detailed(1, present, present, present);

        let p = u32::from_le_bytes([frame[6], frame[7], frame[8], frame[9]]);
        let e = u32::from_le_bytes([frame[10], frame[11], frame[12], frame[13]]);
        let h = u32::from_le_bytes([frame[14], frame[15], frame[16], frame[17]]);

        assert_eq!(p & ABSOLUTE_PRESSURE, 0);
        assert_eq!(e & ABSOLUTE_PRESSURE, 0);
        assert_eq!(h & ABSOLUTE_PRESSURE, 0);
        assert_eq!(p & MAG_3D, 0);
    }

    // --- receive path ---

    /// COMMAND_LONG, MAV_CMD_COMPONENT_ARM_DISARM, param1 = 1.0 (arm),
    /// from sysid 255 / compid 0 as a GCS sends it.
    const ARM_FRAME: [u8; 41] = [
        0xFE, 0x21, 0x03, 0xFF, 0x00, 0x4C, 0x00, 0x00, 0x80, 0x3F, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x90, 0x01, 0x01, 0x01, 0x00, 0xA7, 0x70,
    ];

    const DISARM_FRAME: [u8; 41] = [
        0xFE, 0x21, 0x04, 0xFF, 0x00, 0x4C, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x90, 0x01, 0x01, 0x01, 0x00, 0x8A, 0x58,
    ];

    const GCS_HEARTBEAT_FRAME: [u8; 17] = [
        0xFE, 0x09, 0x05, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x08, 0x00, 0x00,
        0x03, 0xF2, 0x52,
    ];

    fn feed(p: &mut Parser, bytes: &[u8]) -> Option<Message> {
        let mut last = None;
        for &b in bytes {
            if let Some(m) = p.push(b) {
                last = Some(m);
            }
        }
        last
    }

    #[test]
    fn parses_arm_command_from_pymavlink_frame() {
        let mut p = Parser::new();
        match feed(&mut p, &ARM_FRAME) {
            Some(Message::CommandLong { command, param1, target_system, target_component, confirmation }) => {
                assert_eq!(command, cmd::COMPONENT_ARM_DISARM);
                assert_eq!(param1, 1.0);
                assert_eq!(target_system, 1);
                assert_eq!(target_component, 1);
                assert_eq!(confirmation, 0);
            }
            other => panic!("expected CommandLong, got {:?}", other),
        }
        assert_eq!(p.crc_errors, 0);
    }

    #[test]
    fn parses_disarm_command() {
        let mut p = Parser::new();
        match feed(&mut p, &DISARM_FRAME) {
            Some(Message::CommandLong { command, param1, .. }) => {
                assert_eq!(command, cmd::COMPONENT_ARM_DISARM);
                assert_eq!(param1, 0.0);
            }
            other => panic!("expected CommandLong, got {:?}", other),
        }
    }

    #[test]
    fn parses_gcs_heartbeat() {
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &GCS_HEARTBEAT_FRAME), Some(Message::Heartbeat));
    }

    /// A single flipped payload bit must be rejected. This is the property the
    /// whole CRC path exists for - an unvalidated command link is worse than
    /// no command link.
    #[test]
    fn rejects_frame_with_corrupted_payload() {
        let mut bad = ARM_FRAME;
        bad[6] ^= 0x01;
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &bad), None);
        assert_eq!(p.crc_errors, 1);
    }

    /// A corrupted CRC must be rejected just as firmly as a corrupted payload.
    #[test]
    fn rejects_frame_with_corrupted_crc() {
        let mut bad = ARM_FRAME;
        bad[40] ^= 0xFF;
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &bad), None);
        assert_eq!(p.crc_errors, 1);
    }

    /// An unknown message ID has no known CRC_EXTRA, so it cannot be verified
    /// and must be dropped rather than guessed at.
    #[test]
    fn drops_unverifiable_unknown_message() {
        let mut unknown = ARM_FRAME;
        unknown[5] = 0xFD; // an ID this firmware has no CRC_EXTRA for
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &unknown), None);
        assert_eq!(p.unknown_msgs, 1);
        assert_eq!(p.crc_errors, 0, "unknown IDs are not CRC failures");
    }

    /// Leading garbage costs nothing: bytes that are not STX are discarded
    /// while idle, and the next real frame parses.
    #[test]
    fn resynchronises_after_leading_garbage() {
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &[0x00, 0xFF, 0x12, 0xAB]), None);
        assert!(matches!(feed(&mut p, &ARM_FRAME), Some(Message::CommandLong { .. })));
    }

    /// A frame truncated mid-payload costs the *next* frame as well, and the
    /// one after that recovers.
    ///
    /// This is inherent to MAVLink v1, not a defect here: the framing has no
    /// byte stuffing, so nothing makes `0xFE` unambiguous. While the parser is
    /// still counting payload bytes it consumes the next frame's start byte as
    /// payload, that frame then fails its CRC, and only the following frame is
    /// seen cleanly. Asserted explicitly because a command link that quietly
    /// eats a frame after every truncation is a property worth knowing about -
    /// it is why a GCS retrying an unacknowledged command matters.
    #[test]
    fn truncated_frame_costs_the_following_frame_then_recovers() {
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &ARM_FRAME[..20]), None); // cut mid-payload

        // The frame immediately after the truncation is swallowed.
        assert_eq!(feed(&mut p, &ARM_FRAME), None);
        assert_eq!(p.crc_errors, 1, "the swallowed frame fails its CRC");

        // The one after that is clean.
        assert!(matches!(feed(&mut p, &ARM_FRAME), Some(Message::CommandLong { .. })));
    }

    /// Bytes arriving one at a time across many calls must parse identically
    /// to a single burst - the endpoint delivers whatever chunk size it likes.
    #[test]
    fn parses_identically_when_split_across_calls() {
        let mut p = Parser::new();
        let mut got = None;
        for &b in ARM_FRAME.iter() {
            if let Some(m) = p.push(b) {
                got = Some(m);
            }
        }
        assert!(matches!(got, Some(Message::CommandLong { .. })));
    }

    // --- parameter protocol ---

    #[test]
    fn parses_param_request_list() {
        let f: [u8; 10] = [0xFE, 0x02, 0x0B, 0xFF, 0x00, 0x15, 0x01, 0x01, 0xC7, 0x7E];
        let mut p = Parser::new();
        assert_eq!(feed(&mut p, &f), Some(Message::ParamRequestList));
    }

    #[test]
    fn parses_param_set() {
        let f: [u8; 31] = [
            0xFE, 0x17, 0x0C, 0xFF, 0x00, 0x17, 0x00, 0x00, 0xD0, 0x40, 0x01, 0x01, 0x4D, 0x43,
            0x5F, 0x52, 0x4F, 0x4C, 0x4C, 0x5F, 0x41, 0x54, 0x54, 0x5F, 0x50, 0x00, 0x00, 0x00,
            0x09, 0x27, 0x9A,
        ];
        let mut p = Parser::new();
        match feed(&mut p, &f) {
            Some(Message::ParamSet { param_id, param_value }) => {
                assert_eq!(param_value, 6.5);
                assert_eq!(&param_id[..13], b"MC_ROLL_ATT_P");
                assert_eq!(&param_id[13..], &[0, 0, 0]);
            }
            other => panic!("expected ParamSet, got {:?}", other),
        }
    }

    #[test]
    fn parses_param_request_read_by_index() {
        let f: [u8; 28] = [
            0xFE, 0x14, 0x0D, 0xFF, 0x00, 0x14, 0x03, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0A, 0x63,
        ];
        let mut p = Parser::new();
        match feed(&mut p, &f) {
            Some(Message::ParamRequestRead { param_index, .. }) => assert_eq!(param_index, 3),
            other => panic!("expected ParamRequestRead, got {:?}", other),
        }
    }

    #[test]
    fn param_value_matches_pymavlink_reference() {
        let expected: [u8; 33] = [
            0xFE, 0x19, 0x0E, 0x01, 0x01, 0x16, 0x00, 0x00, 0x90, 0x40, 0x1A, 0x00, 0x00, 0x00,
            0x4D, 0x43, 0x5F, 0x52, 0x4F, 0x4C, 0x4C, 0x5F, 0x41, 0x54, 0x54, 0x5F, 0x50, 0x00,
            0x00, 0x00, 0x09, 0x9B, 0x9F,
        ];
        let mut id = [0u8; PARAM_ID_LEN];
        id[..13].copy_from_slice(b"MC_ROLL_ATT_P");
        assert_eq!(encode_param_value(14, &id, 4.5, 9, 26, 0), expected);
    }

    #[test]
    fn autopilot_version_matches_pymavlink_reference() {
        let expected: [u8; 68] = [
            0xFE, 0x3C, 0x0F, 0x01, 0x01, 0x94, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x68, 0xAF,
        ];
        assert_eq!(encode_autopilot_version(15, 0x0001_0000), expected);
    }

    #[test]
    fn command_ack_matches_pymavlink_reference() {
        let expected: [u8; 11] = [0xFE, 0x03, 0x09, 0x01, 0x01, 0x4D, 0x90, 0x01, 0x00, 0x58, 0xDA];
        assert_eq!(
            encode_command_ack(9, cmd::COMPONENT_ARM_DISARM, result::ACCEPTED),
            expected
        );
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
