//! MS5611-01BA barometric pressure sensor, on the shared internal SPI bus.
//!
//! # Why this is a state machine and not a `read()`
//!
//! An MS5611 conversion is not instantaneous: the part needs up to 9.04 ms at
//! its highest oversampling setting, and each pressure reading requires *two*
//! conversions (D1 pressure, D2 temperature) because the temperature is what
//! compensates the pressure. A blocking driver would therefore stall its caller
//! for milliseconds at a time.
//!
//! In this firmware that is not merely inefficient, it is a defect: `main_usb`'s
//! loop must call `usb_dev.poll()` promptly, and an unserviced USB CDC endpoint
//! is exactly the fault that previously froze QGroundControl (see
//! `BUILD_AND_FLASH.md`). So this driver never waits. [`Ms5611::tick`] is called
//! once per millisecond, advances the conversion, and returns a [`Reading`] only
//! on the tick where one completes.
//!
//! # Compensation
//!
//! Both the first-order compensation and the second-order low-temperature
//! correction are implemented from the datasheet's own equations. The
//! second-order terms are not optional decoration - below 20 °C the
//! uncompensated pressure error grows large enough to matter for altitude, and
//! this board is specified to operate well below that.
//!
//! Intermediate products exceed 32 bits (`OFF` and `SENS` are documented as
//! 41-bit and 42-bit quantities respectively), so the arithmetic is `i64`
//! throughout. Doing it in `i32` silently truncates and yields a plausible but
//! wrong pressure, which is the sort of failure that survives a bench test.

#![allow(dead_code)]

use defmt::warn;
use embedded_hal::digital::OutputPin;
use embedded_hal::spi::SpiBus;

const CMD_RESET: u8 = 0x1E;
const CMD_ADC_READ: u8 = 0x00;
const CMD_CONVERT_D1: u8 = 0x40; // pressure
const CMD_CONVERT_D2: u8 = 0x50; // temperature

/// Oversampling ratio. Higher is quieter and slower; the conversion time is
/// what sets how many ticks the state machine waits.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Osr {
    Osr256,
    Osr512,
    Osr1024,
    Osr2048,
    Osr4096,
}

impl Osr {
    fn cmd_offset(self) -> u8 {
        match self {
            Osr::Osr256 => 0x00,
            Osr::Osr512 => 0x02,
            Osr::Osr1024 => 0x04,
            Osr::Osr2048 => 0x06,
            Osr::Osr4096 => 0x08,
        }
    }

    /// Milliseconds to wait, rounded up from the datasheet's maximum
    /// conversion time and then given one extra millisecond of margin. Reading
    /// the ADC before the conversion finishes returns 0, not an error, so the
    /// margin is what stops a silent zero from entering the compensation.
    fn ticks(self) -> u8 {
        match self {
            Osr::Osr256 => 2,   // 0.60 ms
            Osr::Osr512 => 3,   // 1.17 ms
            Osr::Osr1024 => 4,  // 2.28 ms
            Osr::Osr2048 => 6,  // 4.54 ms
            Osr::Osr4096 => 11, // 9.04 ms
        }
    }
}

/// A compensated measurement.
#[derive(Clone, Copy, Debug)]
pub struct Reading {
    /// Pressure in pascals.
    pub pressure_pa: i32,
    /// Temperature in centidegrees Celsius (2000 = 20.00 °C).
    pub temperature_cdeg: i32,
}

impl Reading {
    /// Pressure in hectopascals (millibars) - the unit MAVLink's
    /// SCALED_PRESSURE expects.
    pub fn pressure_hpa(&self) -> f32 {
        self.pressure_pa as f32 / 100.0
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum State {
    /// Nothing in flight; the next tick starts a temperature conversion.
    Idle,
    /// D2 (temperature) converting, `remaining` ticks to go.
    ConvertingD2 { remaining: u8 },
    /// D1 (pressure) converting, `remaining` ticks to go.
    ConvertingD1 { remaining: u8 },
}

pub struct Ms5611 {
    /// Calibration words C1..C6 as `prom[1]..prom[6]`; `prom[0]` is reserved
    /// and `prom[7]` carries the CRC.
    prom: [u16; 8],
    osr: Osr,
    state: State,
    /// Last raw temperature reading, held across the pressure conversion.
    d2: u32,
    initialised: bool,
}

impl Ms5611 {
    /// Build a driver around a PROM that has already been read and CRC-checked
    /// by [`crate::probe::probe_baro`].
    ///
    /// Taking the PROM rather than re-reading it means the CRC that established
    /// the sensor is present is the same data the compensation uses - there is
    /// no window in which a marginal bus passes the probe and then supplies
    /// different coefficients.
    pub fn from_prom(prom: [u16; 8], osr: Osr) -> Self {
        Self {
            prom,
            osr,
            state: State::Idle,
            d2: 0,
            initialised: true,
        }
    }

    /// Send a reset. Only needed if the part may have been left mid-conversion;
    /// the datasheet requires 2.8 ms afterwards before the PROM can be read.
    pub fn reset<SPI, CS>(spi: &mut SPI, cs: &mut CS) -> Result<(), ()>
    where
        SPI: SpiBus<u8>,
        CS: OutputPin,
    {
        cs.set_low().map_err(|_| ())?;
        let r = spi.write(&[CMD_RESET]);
        cs.set_high().map_err(|_| ())?;
        r.map_err(|_| ())
    }

    fn send_cmd<SPI, CS>(spi: &mut SPI, cs: &mut CS, cmd: u8) -> Result<(), ()>
    where
        SPI: SpiBus<u8>,
        CS: OutputPin,
    {
        cs.set_low().map_err(|_| ())?;
        let r = spi.write(&[cmd]);
        cs.set_high().map_err(|_| ())?;
        r.map_err(|_| ())
    }

    /// Read the 24-bit ADC result of the conversion that just finished.
    fn read_adc<SPI, CS>(spi: &mut SPI, cs: &mut CS) -> Result<u32, ()>
    where
        SPI: SpiBus<u8>,
        CS: OutputPin,
    {
        let tx = [CMD_ADC_READ, 0x00, 0x00, 0x00];
        let mut rx = [0u8; 4];

        cs.set_low().map_err(|_| ())?;
        let r = spi.transfer(&mut rx, &tx);
        cs.set_high().map_err(|_| ())?;
        r.map_err(|_| ())?;

        Ok(((rx[1] as u32) << 16) | ((rx[2] as u32) << 8) | rx[3] as u32)
    }

    /// Advance the conversion by one millisecond.
    ///
    /// Returns `Some(Reading)` only on the tick a pressure conversion
    /// completes - roughly every `2 * osr.ticks()` ms, since each reading needs
    /// a temperature conversion followed by a pressure one.
    pub fn tick<SPI, CS>(&mut self, spi: &mut SPI, cs: &mut CS) -> Option<Reading>
    where
        SPI: SpiBus<u8>,
        CS: OutputPin,
    {
        if !self.initialised {
            return None;
        }

        match self.state {
            State::Idle => {
                if Self::send_cmd(spi, cs, CMD_CONVERT_D2 + self.osr.cmd_offset()).is_ok() {
                    self.state = State::ConvertingD2 { remaining: self.osr.ticks() };
                }
                None
            }

            State::ConvertingD2 { remaining } => {
                if remaining > 1 {
                    self.state = State::ConvertingD2 { remaining: remaining - 1 };
                    return None;
                }
                match Self::read_adc(spi, cs) {
                    Ok(0) | Err(_) => {
                        // A zero here means the ADC was read before the
                        // conversion completed, or the bus failed. Either way
                        // the value is not a temperature - restart rather than
                        // feed it into the compensation.
                        warn!("MS5611: bad D2 (temperature) conversion, restarting");
                        self.state = State::Idle;
                        None
                    }
                    Ok(d2) => {
                        self.d2 = d2;
                        if Self::send_cmd(spi, cs, CMD_CONVERT_D1 + self.osr.cmd_offset()).is_ok() {
                            self.state = State::ConvertingD1 { remaining: self.osr.ticks() };
                        } else {
                            self.state = State::Idle;
                        }
                        None
                    }
                }
            }

            State::ConvertingD1 { remaining } => {
                if remaining > 1 {
                    self.state = State::ConvertingD1 { remaining: remaining - 1 };
                    return None;
                }
                self.state = State::Idle;
                match Self::read_adc(spi, cs) {
                    Ok(0) | Err(_) => {
                        warn!("MS5611: bad D1 (pressure) conversion, restarting");
                        None
                    }
                    Ok(d1) => Some(self.compensate(d1, self.d2)),
                }
            }
        }
    }

    /// Datasheet compensation, first and second order.
    ///
    /// Kept separate from the bus handling so it can be unit-tested against the
    /// datasheet's own worked example on the host, with no SPI involved.
    pub fn compensate(&self, d1: u32, d2: u32) -> Reading {
        let c1 = self.prom[1] as i64;
        let c2 = self.prom[2] as i64;
        let c3 = self.prom[3] as i64;
        let c4 = self.prom[4] as i64;
        let c5 = self.prom[5] as i64;
        let c6 = self.prom[6] as i64;

        let d1 = d1 as i64;
        let d2 = d2 as i64;

        // First order
        let dt = d2 - (c5 << 8);
        let mut temp = 2000 + ((dt * c6) >> 23);
        let mut off = (c2 << 16) + ((c4 * dt) >> 7);
        let mut sens = (c1 << 15) + ((c3 * dt) >> 8);

        // Second order, below 20 C
        if temp < 2000 {
            let t_sq = (temp - 2000) * (temp - 2000);
            let t2 = (dt * dt) >> 31;
            let mut off2 = (5 * t_sq) / 2;
            let mut sens2 = (5 * t_sq) / 4;

            // Very low temperature, below -15 C
            if temp < -1500 {
                let t_vlow = (temp + 1500) * (temp + 1500);
                off2 += 7 * t_vlow;
                sens2 += (11 * t_vlow) / 2;
            }

            temp -= t2;
            off -= off2;
            sens -= sens2;
        }

        let p = (((d1 * sens) >> 21) - off) >> 15;

        Reading {
            pressure_pa: p as i32,
            temperature_cdeg: temp as i32,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The worked example from the MS5611-01BA datasheet. Its calibration
    /// values and raw readings are documented to produce 100009 Pa at 20.07 C.
    fn datasheet_example() -> Ms5611 {
        // prom[0] is reserved and prom[7] carries the CRC; the datasheet's
        // example specifies only C1..C6, which are prom[1]..prom[6].
        Ms5611::from_prom(
            [0, 40127, 36924, 23317, 23282, 33464, 28312, 0],
            Osr::Osr4096,
        )
    }

    #[test]
    fn datasheet_worked_example() {
        let s = datasheet_example();
        let r = s.compensate(9085466, 8569150);
        assert_eq!(r.temperature_cdeg, 2007, "expected 20.07 C");
        assert_eq!(r.pressure_pa, 100009, "expected 100009 Pa");
    }

    #[test]
    fn pressure_hpa_conversion() {
        let r = Reading { pressure_pa: 100009, temperature_cdeg: 2007 };
        assert!((r.pressure_hpa() - 1000.09).abs() < 0.01);
    }

    /// Below 20 C the second-order path must actually change the answer -
    /// a guard against the correction being computed and then discarded.
    #[test]
    fn second_order_correction_applies_below_20c() {
        let s = datasheet_example();
        // A D2 well below the example drives TEMP under 2000.
        let cold = s.compensate(9085466, 8100000);
        assert!(cold.temperature_cdeg < 2000, "test setup should be below 20 C");

        // Recompute first-order only, to confirm the paths differ.
        let c5 = 33464i64;
        let c6 = 28312i64;
        let dt = 8100000i64 - (c5 << 8);
        let first_order_temp = 2000 + ((dt * c6) >> 23);
        assert_ne!(
            cold.temperature_cdeg as i64, first_order_temp,
            "second-order correction was not applied"
        );
    }
}
