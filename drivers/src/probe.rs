//! Internal sensor-bus probe: ask every device that *might* be on SPI1 who it
//! is, and report what actually answered.
//!
//! This exists because sensor population on the PX4 FMUv2 family is a per-unit
//! build option, not a property of the design. `hardware/PX4FMUv2.4.5_NETS.md`
//! records five sensor positions in the schematic (`U501` L3G4200DH, `U502`
//! L3GD20H, `U504` LSM303D, `U505` MPU-6000, `U506` MS5611) and notes plainly
//! that which are fitted must be verified per board rather than assumed. Pixhawk
//! 2.4.8 clones widen that further - an ICM-20608 or ICM-20602 in the MPU-6000
//! position is common.
//!
//! So the firmware asks instead of assuming. Every device here is identified by
//! reading a fixed ID register over SPI and comparing against the values in its
//! own datasheet; anything that does not answer correctly is reported absent and
//! is never read again.
//!
//! ## Why the MS5611 is handled differently
//!
//! It has no WHO_AM_I register. The datasheet's PROM instead carries a 4-bit CRC
//! in the low nibble of its last word, computed over the other seven words, so
//! presence is established by reading the PROM and checking that CRC recomputes.
//! That is a stronger check than a magic byte: a floating MISO reads as all-ones
//! or all-zeros, and neither produces a valid CRC4.
//!
//! ## Chip-select discipline
//!
//! Every device on this bus shares SPI1 (`SPI_INT`), so exactly one CS may be low
//! at a time. Each probe asserts its own CS, transfers, and releases before the
//! next runs. A device left selected corrupts the next probe, which is the usual
//! way a bus scan reports phantom parts.

#![allow(dead_code)]

use defmt::{info, warn};
use embedded_hal::digital::OutputPin;
use embedded_hal::spi::SpiBus;

/// SPI read bit - all four parts here use "MSB set means read".
const READ: u8 = 0x80;

/// MPU-6000 / ICM-206xx `WHO_AM_I` register.
const MPU_WHO_AM_I_REG: u8 = 0x75;
const MPU6000_ID: u8 = 0x68;
const ICM20602_ID: u8 = 0x12;
const ICM20608_ID: u8 = 0xAF;

/// ST `WHO_AM_I` register - same address on L3G4200D, L3GD20, L3GD20H, LSM303D.
const ST_WHO_AM_I_REG: u8 = 0x0F;
const L3G4200D_ID: u8 = 0xD3;
const L3GD20_ID: u8 = 0xD4;
const L3GD20H_ID: u8 = 0xD7;
const LSM303D_ID: u8 = 0x49;

/// MS5611 commands.
const MS5611_CMD_RESET: u8 = 0x1E;
const MS5611_CMD_PROM_READ_BASE: u8 = 0xA0;

/// What answered at one bus position.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Device {
    /// Nothing answered, or the answer was not a value any known part returns.
    Absent,
    Mpu6000,
    Icm20602,
    Icm20608,
    L3g4200d,
    L3gd20,
    L3gd20h,
    Lsm303d,
    Ms5611,
    /// Something answered, but with an ID this firmware does not recognise.
    /// Carries the raw byte so the boot log can show it rather than swallow it.
    Unknown(u8),
}

impl Device {
    pub fn is_present(&self) -> bool {
        !matches!(self, Device::Absent)
    }

    /// Whether this device can be driven by a driver that exists in this
    /// crate. `Icm20602`/`Icm20608` are register-compatible with the MPU-6000
    /// for the accel/gyro reads this firmware performs, but that compatibility
    /// has never been exercised on real silicon here, so they are reported and
    /// not claimed as supported.
    pub fn is_supported(&self) -> bool {
        matches!(self, Device::Mpu6000 | Device::Ms5611)
    }

    pub fn name(&self) -> &'static str {
        match self {
            Device::Absent => "absent",
            Device::Mpu6000 => "MPU-6000",
            Device::Icm20602 => "ICM-20602",
            Device::Icm20608 => "ICM-20608",
            Device::L3g4200d => "L3G4200D",
            Device::L3gd20 => "L3GD20",
            Device::L3gd20h => "L3GD20H",
            Device::Lsm303d => "LSM303D",
            Device::Ms5611 => "MS5611",
            Device::Unknown(_) => "unknown",
        }
    }
}

/// What the whole internal bus looks like after a scan.
#[derive(Clone, Copy, Debug)]
pub struct BusScan {
    /// Primary IMU position - `U505` on the reference schematic, CS on PC2.
    pub imu: Device,
    /// Backup gyro position - `U501`/`U502`, CS on PC13.
    pub gyro: Device,
    /// Accel/magnetometer position - `U504`, CS on PC15.
    pub accel_mag: Device,
    /// Barometer position - `U506`, CS on PD7.
    pub baro: Device,
}

impl BusScan {
    pub const fn empty() -> Self {
        Self {
            imu: Device::Absent,
            gyro: Device::Absent,
            accel_mag: Device::Absent,
            baro: Device::Absent,
        }
    }

    pub fn count_present(&self) -> u8 {
        [self.imu, self.gyro, self.accel_mag, self.baro]
            .iter()
            .filter(|d| d.is_present())
            .count() as u8
    }

    /// Log every position, present or not. Absence is as informative as
    /// presence here - a board with no barometer is a normal build option, not
    /// a fault, and the log should say which it is rather than being silent.
    pub fn log(&self) {
        info!("--- internal sensor bus (SPI1) ---");
        info!("  IMU       (CS PC2)  : {}", self.imu.name());
        info!("  gyro      (CS PC13) : {}", self.gyro.name());
        info!("  accel/mag (CS PC15) : {}", self.accel_mag.name());
        info!("  baro      (CS PD7)  : {}", self.baro.name());
        info!("  {} of 4 positions populated", self.count_present());
    }
}

/// Read one register from a device that uses the "MSB set means read"
/// convention, asserting and releasing `cs` around the transfer.
fn read_reg<SPI, CS>(spi: &mut SPI, cs: &mut CS, reg: u8) -> Option<u8>
where
    SPI: SpiBus<u8>,
    CS: OutputPin,
{
    let tx = [reg | READ, 0x00];
    let mut rx = [0u8; 2];

    cs.set_low().ok()?;
    let r = spi.transfer(&mut rx, &tx);
    cs.set_high().ok()?;

    r.ok()?;
    Some(rx[1])
}

/// Identify whatever sits at the primary IMU position.
pub fn probe_imu<SPI, CS>(spi: &mut SPI, cs: &mut CS) -> Device
where
    SPI: SpiBus<u8>,
    CS: OutputPin,
{
    match read_reg(spi, cs, MPU_WHO_AM_I_REG) {
        None => Device::Absent,
        Some(id) => match id {
            MPU6000_ID => Device::Mpu6000,
            ICM20602_ID => Device::Icm20602,
            ICM20608_ID => Device::Icm20608,
            // A floating or shorted MISO reads all-ones or all-zeros. Those are
            // the two values most likely to mean "no device", not "unknown
            // device", so they are reported as absent rather than as a mystery
            // part someone might then go looking for.
            0x00 | 0xFF => Device::Absent,
            other => Device::Unknown(other),
        },
    }
}

/// Identify whatever sits at an ST sensor position (backup gyro or accel/mag).
pub fn probe_st<SPI, CS>(spi: &mut SPI, cs: &mut CS) -> Device
where
    SPI: SpiBus<u8>,
    CS: OutputPin,
{
    match read_reg(spi, cs, ST_WHO_AM_I_REG) {
        None => Device::Absent,
        Some(id) => match id {
            L3G4200D_ID => Device::L3g4200d,
            L3GD20_ID => Device::L3gd20,
            L3GD20H_ID => Device::L3gd20h,
            LSM303D_ID => Device::Lsm303d,
            0x00 | 0xFF => Device::Absent,
            other => Device::Unknown(other),
        },
    }
}

/// The MS5611 PROM CRC4, ported from the datasheet's own reference routine
/// (AN520). `prom` is the eight 16-bit PROM words as read; the returned nibble
/// is compared against the low nibble of `prom[7]`.
///
/// Two details the datasheet is explicit about and that are easy to lose:
/// the CRC nibble itself must be zeroed before computing, and the final word
/// is treated as a high byte followed by a zero low byte.
pub fn ms5611_crc4(prom: &[u16; 8]) -> u8 {
    let mut n_rem: u16 = 0;
    let mut buf = *prom;
    buf[7] &= 0xFF00; // zero the CRC nibble (and the rest of the low byte)

    for i in 0..16 {
        let byte = if i % 2 == 1 {
            (buf[i >> 1] & 0x00FF) as u8
        } else {
            ((buf[i >> 1] & 0xFF00) >> 8) as u8
        };
        n_rem ^= byte as u16;
        for _ in 0..8 {
            if n_rem & 0x8000 != 0 {
                n_rem = (n_rem << 1) ^ 0x3000;
            } else {
                n_rem <<= 1;
            }
        }
    }
    ((n_rem >> 12) & 0x000F) as u8
}

/// Identify a barometer by reading its PROM and validating the CRC4.
///
/// Returns the PROM alongside the verdict so a caller that is about to use the
/// sensor does not have to read it a second time - the coefficients are needed
/// for every conversion.
pub fn probe_baro<SPI, CS>(spi: &mut SPI, cs: &mut CS) -> (Device, [u16; 8])
where
    SPI: SpiBus<u8>,
    CS: OutputPin,
{
    let mut prom = [0u16; 8];

    for (i, word) in prom.iter_mut().enumerate() {
        let tx = [MS5611_CMD_PROM_READ_BASE + (i as u8) * 2, 0x00, 0x00];
        let mut rx = [0u8; 3];

        if cs.set_low().is_err() {
            return (Device::Absent, prom);
        }
        let r = spi.transfer(&mut rx, &tx);
        let _ = cs.set_high();
        if r.is_err() {
            return (Device::Absent, prom);
        }
        *word = ((rx[1] as u16) << 8) | rx[2] as u16;
    }

    // All-zero or all-ones PROM is a disconnected bus, not a sensor. Checking
    // this first keeps the CRC result meaningful - CRC4 over all zeros happens
    // to be 0, which would otherwise "validate".
    let all_same = prom.iter().all(|&w| w == 0x0000) || prom.iter().all(|&w| w == 0xFFFF);
    if all_same {
        return (Device::Absent, prom);
    }

    let expected = (prom[7] & 0x000F) as u8;
    let computed = ms5611_crc4(&prom);
    if computed == expected {
        (Device::Ms5611, prom)
    } else {
        warn!(
            "baro position answered but PROM CRC4 failed: computed {=u8:#04x}, expected {=u8:#04x}",
            computed, expected
        );
        (Device::Absent, prom)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The worked example from the MS5611 datasheet's CRC4 application note:
    /// this PROM content is documented to produce a CRC of 0xB.
    #[test]
    fn crc4_matches_datasheet_example() {
        let prom: [u16; 8] = [
            0x3132, 0x3334, 0x3536, 0x3738, 0x3940, 0x4142, 0x4344, 0x4500,
        ];
        assert_eq!(ms5611_crc4(&prom), 0x0B);
    }

    /// A disconnected bus must not validate. This is the case the all-same
    /// guard in `probe_baro` exists for - note the CRC alone would pass here.
    #[test]
    fn crc4_over_zeros_is_zero() {
        let prom = [0u16; 8];
        assert_eq!(ms5611_crc4(&prom), 0);
    }

    #[test]
    fn absent_devices_are_not_present() {
        assert!(!Device::Absent.is_present());
        assert!(Device::Mpu6000.is_present());
        assert!(Device::Unknown(0x42).is_present());
    }

    #[test]
    fn unknown_is_reported_but_not_supported() {
        assert!(!Device::Unknown(0x42).is_supported());
        assert!(!Device::Icm20608.is_supported());
        assert!(Device::Mpu6000.is_supported());
        assert!(Device::Ms5611.is_supported());
    }

    #[test]
    fn scan_counts_only_populated_positions() {
        let mut s = BusScan::empty();
        assert_eq!(s.count_present(), 0);
        s.imu = Device::Mpu6000;
        s.baro = Device::Ms5611;
        assert_eq!(s.count_present(), 2);
    }
}
