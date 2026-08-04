//! Onboard parameter table.
//!
//! A ground station's first act after connecting is to ask for the parameter
//! list, and it will not consider a vehicle fully up until it has one. More
//! usefully, calibration values, control gains and failsafe thresholds all need
//! somewhere to live that survives a reboot and can be changed without a
//! reflash. This is that place.
//!
//! # What is in here is real
//!
//! Every entry maps to a value the flight application actually uses - the
//! cascaded-PID gains in `flight::stabilize::AxisGains` and the MPC iteration
//! caps in `firmware/src/main.rs`. Nothing is invented to pad the list. A
//! parameter a GCS can see and set but which changes nothing is worse than an
//! absent one: the operator gets feedback that their change took effect.
//!
//! **In `jfox-fcu-usb` specifically, these are served and stored but do not
//! alter that binary's behaviour**, because it runs no control loop. It is the
//! parameter *transport* being exercised there. They take effect in
//! `jfox-fcu-flight`.
//!
//! # Naming
//!
//! MAVLink's `param_id` is a fixed 16-byte field, not a string - it is NUL
//! padded only if shorter than 16, and a name of exactly 16 characters carries
//! no terminator at all. [`ParamTable::index_of`] compares over the padded form
//! for that reason; comparing as C strings would mishandle the 16-character
//! case, which is the classic way a GCS ends up unable to write one parameter
//! out of a list.

#![allow(dead_code)]

/// MAVLink `MAV_PARAM_TYPE_REAL32`. Every parameter here is a float; the
/// iteration caps are integers by meaning but are carried as floats because
/// that is what the wire format and every GCS expects.
pub const MAV_PARAM_TYPE_REAL32: u8 = 9;

/// Length of MAVLink's `param_id` field.
pub const PARAM_ID_LEN: usize = 16;

/// A parameter's identity and default, held in flash.
pub struct ParamDesc {
    pub name: &'static str,
    pub default: f32,
    /// Inclusive range a `PARAM_SET` must fall within. A GCS is allowed to
    /// send anything; refusing out-of-range values here is what stops a typo
    /// from becoming a control gain.
    pub min: f32,
    pub max: f32,
}

macro_rules! p {
    ($name:literal, $default:expr, $min:expr, $max:expr) => {
        ParamDesc { name: $name, default: $default, min: $min, max: $max }
    };
}

/// The parameter set, in wire index order.
///
/// Index is positional and a GCS caches it, so **entries must only ever be
/// appended**. Reordering or removing one silently changes what a stored
/// parameter file means.
pub static PARAMS: &[ParamDesc] = &[
    // Roll axis - flight::stabilize::AxisGains, defaults from
    // firmware/src/main.rs::default_stabilize_gains()
    p!("MC_ROLL_ATT_P", 4.5, 0.0, 20.0),
    p!("MC_ROLL_ATT_I", 0.0, 0.0, 10.0),
    p!("MC_ROLL_ATT_D", 0.0, 0.0, 10.0),
    p!("MC_ROLL_ATT_LIM", 3.0, 0.1, 20.0),
    p!("MC_ROLL_RAT_P", 0.15, 0.0, 5.0),
    p!("MC_ROLL_RAT_I", 0.02, 0.0, 5.0),
    p!("MC_ROLL_RAT_D", 0.002, 0.0, 1.0),
    p!("MC_ROLL_RAT_LIM", 1.0, 0.1, 1.0),
    // Pitch axis
    p!("MC_PITCH_ATT_P", 4.5, 0.0, 20.0),
    p!("MC_PITCH_ATT_I", 0.0, 0.0, 10.0),
    p!("MC_PITCH_ATT_D", 0.0, 0.0, 10.0),
    p!("MC_PITCH_ATT_LIM", 3.0, 0.1, 20.0),
    p!("MC_PITCH_RAT_P", 0.15, 0.0, 5.0),
    p!("MC_PITCH_RAT_I", 0.02, 0.0, 5.0),
    p!("MC_PITCH_RAT_D", 0.002, 0.0, 1.0),
    p!("MC_PITCH_RAT_LIM", 1.0, 0.1, 1.0),
    // Yaw axis
    p!("MC_YAW_ATT_P", 4.0, 0.0, 20.0),
    p!("MC_YAW_ATT_I", 0.0, 0.0, 10.0),
    p!("MC_YAW_ATT_D", 0.0, 0.0, 10.0),
    p!("MC_YAW_ATT_LIM", 3.0, 0.1, 20.0),
    p!("MC_YAW_RAT_P", 0.2, 0.0, 5.0),
    p!("MC_YAW_RAT_I", 0.02, 0.0, 5.0),
    p!("MC_YAW_RAT_D", 0.0, 0.0, 1.0),
    p!("MC_YAW_RAT_LIM", 1.0, 0.1, 1.0),
    // MPC solver caps - firmware/src/main.rs. Both were sized by assumption
    // rather than measurement, which is exactly why they belong here: they are
    // the values HARDWARE_BRINGUP.md Stage 1 tells you to adjust against real
    // control-loop timing.
    p!("MPC_ADMM_ITERS", 10.0, 1.0, 50.0),
    p!("MPC_RIC_ITERS", 20.0, 1.0, 100.0),
];

/// Live parameter values.
pub struct ParamTable {
    values: [f32; PARAMS.len()],
}

/// Why a `PARAM_SET` was refused.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum SetError {
    /// No parameter by that name.
    UnknownName,
    /// Value outside the descriptor's declared range.
    OutOfRange,
    /// Value was NaN or infinite. A GCS should never send one, but a corrupt
    /// float that passed CRC would otherwise poison a gain permanently.
    NotFinite,
}

impl Default for ParamTable {
    fn default() -> Self {
        Self::new()
    }
}

impl ParamTable {
    /// All parameters at their compiled-in defaults.
    pub fn new() -> Self {
        let mut values = [0.0f32; PARAMS.len()];
        let mut i = 0;
        while i < PARAMS.len() {
            values[i] = PARAMS[i].default;
            i += 1;
        }
        Self { values }
    }

    pub const fn count(&self) -> u16 {
        PARAMS.len() as u16
    }

    pub fn get(&self, index: usize) -> Option<f32> {
        self.values.get(index).copied()
    }

    pub fn desc(&self, index: usize) -> Option<&'static ParamDesc> {
        PARAMS.get(index)
    }

    /// Copy a parameter's name into MAVLink's fixed 16-byte field, NUL padded.
    pub fn name_bytes(index: usize) -> Option<[u8; PARAM_ID_LEN]> {
        let d = PARAMS.get(index)?;
        let mut out = [0u8; PARAM_ID_LEN];
        let bytes = d.name.as_bytes();
        let n = if bytes.len() > PARAM_ID_LEN { PARAM_ID_LEN } else { bytes.len() };
        out[..n].copy_from_slice(&bytes[..n]);
        Some(out)
    }

    /// Find a parameter by its wire-format name.
    ///
    /// Compares over the full padded 16 bytes rather than treating the field as
    /// a C string, so a name occupying all 16 bytes - which carries no NUL -
    /// matches correctly.
    pub fn index_of(id: &[u8; PARAM_ID_LEN]) -> Option<usize> {
        PARAMS.iter().position(|d| {
            let mut padded = [0u8; PARAM_ID_LEN];
            let b = d.name.as_bytes();
            let n = if b.len() > PARAM_ID_LEN { PARAM_ID_LEN } else { b.len() };
            padded[..n].copy_from_slice(&b[..n]);
            padded == *id
        })
    }

    /// Apply a `PARAM_SET`, returning the index written.
    ///
    /// Range and finiteness are enforced here rather than trusted from the
    /// sender. MAVLink carries no notion of a parameter's valid range, so a GCS
    /// cannot check on the vehicle's behalf even when it wants to.
    pub fn set(&mut self, id: &[u8; PARAM_ID_LEN], value: f32) -> Result<usize, SetError> {
        let idx = Self::index_of(id).ok_or(SetError::UnknownName)?;
        if !value.is_finite() {
            return Err(SetError::NotFinite);
        }
        let d = &PARAMS[idx];
        if value < d.min || value > d.max {
            return Err(SetError::OutOfRange);
        }
        self.values[idx] = value;
        Ok(idx)
    }

    /// Reset everything to compiled-in defaults.
    pub fn reset_to_defaults(&mut self) {
        for (i, d) in PARAMS.iter().enumerate() {
            self.values[i] = d.default;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_descriptors() {
        let t = ParamTable::new();
        for (i, d) in PARAMS.iter().enumerate() {
            assert_eq!(t.get(i), Some(d.default), "{}", d.name);
        }
    }

    #[test]
    fn every_default_is_inside_its_own_range() {
        for d in PARAMS.iter() {
            assert!(
                d.default >= d.min && d.default <= d.max,
                "{} default {} outside [{}, {}]",
                d.name, d.default, d.min, d.max
            );
        }
    }

    #[test]
    fn names_fit_the_wire_field_and_are_unique() {
        for d in PARAMS.iter() {
            assert!(
                d.name.len() <= PARAM_ID_LEN,
                "{} is {} chars, over the {}-byte param_id field",
                d.name, d.name.len(), PARAM_ID_LEN
            );
        }
        for (i, a) in PARAMS.iter().enumerate() {
            for b in PARAMS.iter().skip(i + 1) {
                assert_ne!(a.name, b.name, "duplicate parameter name");
            }
        }
    }

    #[test]
    fn round_trips_by_name() {
        let mut t = ParamTable::new();
        let id = ParamTable::name_bytes(0).unwrap();
        assert_eq!(ParamTable::index_of(&id), Some(0));
        assert_eq!(t.set(&id, 5.0), Ok(0));
        assert_eq!(t.get(0), Some(5.0));
    }

    #[test]
    fn rejects_out_of_range_and_unknown_and_nan() {
        let mut t = ParamTable::new();
        let id = ParamTable::name_bytes(0).unwrap(); // MC_ROLL_ATT_P, max 20
        assert_eq!(t.set(&id, 1000.0), Err(SetError::OutOfRange));
        assert_eq!(t.set(&id, f32::NAN), Err(SetError::NotFinite));
        assert_eq!(t.set(&id, f32::INFINITY), Err(SetError::NotFinite));
        // The refused writes must not have changed anything.
        assert_eq!(t.get(0), Some(PARAMS[0].default));

        let bogus = [b'Z'; PARAM_ID_LEN];
        assert_eq!(t.set(&bogus, 1.0), Err(SetError::UnknownName));
    }

    /// A 16-character name has no NUL terminator on the wire. Matching must
    /// still work, which is why comparison is over the padded form.
    #[test]
    fn matches_a_name_that_fills_the_field() {
        let longest = PARAMS.iter().map(|d| d.name.len()).max().unwrap();
        assert!(longest <= PARAM_ID_LEN);
        for i in 0..PARAMS.len() {
            let id = ParamTable::name_bytes(i).unwrap();
            assert_eq!(ParamTable::index_of(&id), Some(i), "{}", PARAMS[i].name);
        }
    }

    #[test]
    fn reset_restores_defaults() {
        let mut t = ParamTable::new();
        let id = ParamTable::name_bytes(4).unwrap();
        t.set(&id, 1.234).unwrap();
        assert_ne!(t.get(4), Some(PARAMS[4].default));
        t.reset_to_defaults();
        assert_eq!(t.get(4), Some(PARAMS[4].default));
    }
}
