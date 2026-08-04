//! MPU-6000 6-axis IMU driver (SPI)
//!
//! The MPU-6000 combines a 3-axis gyroscope and 3-axis accelerometer on the same silicon die.
//! This is the primary IMU sensor on the JFOX FCU, connected via SPI1.
//!
//! Features:
//! - ±250, ±500, ±1000, ±2000 °/s gyro ranges
//! - ±2g, ±4g, ±8g, ±16g accelerometer ranges
//! - Programmable sample rate up to 8kHz
//! - Digital Motion Processor (DMP) - not used in this implementation
//! - Data ready interrupt
//!
//! Takes an explicit chip-select pin and toggles it around every SPI
//! transaction (matching `drivers::Fm25v01`'s pattern). `hal::spi::Spi`'s
//! `init_mode3`/`init_mode0` configure software slave management (SSM/SSI),
//! which deasserts the hardware NSS line entirely - without a
//! software-controlled CS pin here, this driver had no working chip-select
//! at all, which only coincidentally works, if at all, with exactly one
//! device on the bus and breaks the moment a second one is added.

use defmt::{debug, info, warn, trace};
use embedded_hal::digital::OutputPin;
use math::Vec3;

// MPU-6000 Register Map
const MPU6000_WHO_AM_I: u8 = 0x75;
const MPU6000_PWR_MGMT_1: u8 = 0x6B;
const MPU6000_PWR_MGMT_2: u8 = 0x6C;
const MPU6000_GYRO_CONFIG: u8 = 0x1B;
const MPU6000_ACCEL_CONFIG: u8 = 0x1C;
const MPU6000_CONFIG: u8 = 0x1A;
const MPU6000_SMPLRT_DIV: u8 = 0x19;
const MPU6000_INT_PIN_CFG: u8 = 0x37;
const MPU6000_INT_ENABLE: u8 = 0x38;
const MPU6000_INT_STATUS: u8 = 0x3A;
const MPU6000_ACCEL_XOUT_H: u8 = 0x3B;
const MPU6000_TEMP_OUT_H: u8 = 0x41;
const MPU6000_GYRO_XOUT_H: u8 = 0x43;
const MPU6000_SIGNAL_PATH_RESET: u8 = 0x68;
const MPU6000_USER_CTRL: u8 = 0x6A;

// Expected WHO_AM_I value
const MPU6000_WHO_AM_I_VALUE: u8 = 0x68;

/// Gyroscope full-scale range
#[derive(Clone, Copy, Debug, defmt::Format)]
pub enum GyroRange {
    Dps250 = 0,  // ±250 °/s
    Dps500 = 1,  // ±500 °/s
    Dps1000 = 2, // ±1000 °/s
    Dps2000 = 3, // ±2000 °/s
}

/// Accelerometer full-scale range
#[derive(Clone, Copy, Debug, defmt::Format)]
pub enum AccelRange {
    G2 = 0,  // ±2g
    G4 = 1,  // ±4g
    G8 = 2,  // ±8g
    G16 = 3, // ±16g
}

/// Digital low-pass filter bandwidth
#[derive(Clone, Copy, Debug, defmt::Format)]
pub enum DlpfBandwidth {
    Hz260 = 0,
    Hz184 = 1,
    Hz94 = 2,
    Hz44 = 3,
    Hz21 = 4,
    Hz10 = 5,
    Hz5 = 6,
}

/// IMU data from MPU-6000
#[derive(Clone, Copy, Debug)]
pub struct ImuData {
    pub accel: Vec3,  // m/s²
    pub gyro: Vec3,   // rad/s
    pub temp: f32,    // °C
}

/// MPU-6000 driver
pub struct Mpu6000<SPI, CS> {
    spi: SPI,
    cs: CS,
    gyro_scale: f32,
    accel_scale: f32,
}

impl<SPI, CS> Mpu6000<SPI, CS>
where
    SPI: embedded_hal::spi::SpiBus,
    CS: OutputPin,
{
    /// Create new MPU-6000 driver. `cs` is driven high (deasserted) here so
    /// construction always leaves the device in a known, unselected idle
    /// state rather than depending on the pin's power-on-reset level.
    pub fn new(spi: SPI, mut cs: CS) -> Self {
        let _ = cs.set_high();
        Self {
            spi,
            cs,
            gyro_scale: 2000.0 / 32768.0,  // Default: ±2000 °/s
            accel_scale: 16.0 / 32768.0,   // Default: ±16g
        }
    }

    fn select(&mut self) -> Result<(), ()> {
        self.cs.set_low().map_err(|_| ())
    }

    fn deselect(&mut self) -> Result<(), ()> {
        self.cs.set_high().map_err(|_| ())
    }

    /// Initialize MPU-6000
    ///
    /// Performs device reset, verifies WHO_AM_I, and configures sensor.
    pub fn init(&mut self) -> Result<(), ()> {
        info!("Initializing MPU-6000...");

        // Small delay after power-on
        delay_ms(50);

        // Check WHO_AM_I register
        let who_am_i = self.read_register(MPU6000_WHO_AM_I)?;
        if who_am_i != MPU6000_WHO_AM_I_VALUE {
            warn!("MPU-6000 WHO_AM_I mismatch: expected 0x{:02X}, got 0x{:02X}",
                  MPU6000_WHO_AM_I_VALUE, who_am_i);
            return Err(());
        }
        info!("MPU-6000 WHO_AM_I OK: 0x{:02X}", who_am_i);

        // Reset device
        self.write_register(MPU6000_PWR_MGMT_1, 0x80)?;
        delay_ms(100);

        // Wake up device, use PLL with X-axis gyro reference
        self.write_register(MPU6000_PWR_MGMT_1, 0x01)?;
        delay_ms(10);

        // Disable I2C interface (SPI-only mode)
        self.write_register(MPU6000_USER_CTRL, 0x10)?;

        // Configure gyro: ±2000 °/s
        self.set_gyro_range(GyroRange::Dps2000)?;

        // Configure accel: ±16g
        self.set_accel_range(AccelRange::G16)?;

        // Set sample rate to 1000Hz
        // Sample Rate = Gyro Output Rate / (1 + SMPLRT_DIV)
        // With DLPF, Gyro Output Rate = 1kHz
        // SMPLRT_DIV = 0 => 1kHz
        self.write_register(MPU6000_SMPLRT_DIV, 0x00)?;

        // Configure DLPF: 184Hz bandwidth
        // This provides good noise filtering while maintaining responsiveness
        self.set_dlpf(DlpfBandwidth::Hz184)?;

        // Configure interrupt: active high, push-pull, latch until read, cleared on any read
        self.write_register(MPU6000_INT_PIN_CFG, 0x10)?;

        // Enable data ready interrupt
        self.write_register(MPU6000_INT_ENABLE, 0x01)?;

        info!("MPU-6000 initialization complete");
        Ok(())
    }

    /// Set gyroscope range
    pub fn set_gyro_range(&mut self, range: GyroRange) -> Result<(), ()> {
        self.write_register(MPU6000_GYRO_CONFIG, (range as u8) << 3)?;

        self.gyro_scale = match range {
            GyroRange::Dps250 => 250.0 / 32768.0,
            GyroRange::Dps500 => 500.0 / 32768.0,
            GyroRange::Dps1000 => 1000.0 / 32768.0,
            GyroRange::Dps2000 => 2000.0 / 32768.0,
        };

        debug!("Gyro range set to {:?}, scale={}", range, self.gyro_scale);
        Ok(())
    }

    /// Set accelerometer range
    pub fn set_accel_range(&mut self, range: AccelRange) -> Result<(), ()> {
        self.write_register(MPU6000_ACCEL_CONFIG, (range as u8) << 3)?;

        self.accel_scale = match range {
            AccelRange::G2 => 2.0 / 32768.0,
            AccelRange::G4 => 4.0 / 32768.0,
            AccelRange::G8 => 8.0 / 32768.0,
            AccelRange::G16 => 16.0 / 32768.0,
        };

        debug!("Accel range set to {:?}, scale={}", range, self.accel_scale);
        Ok(())
    }

    /// Set digital low-pass filter bandwidth
    pub fn set_dlpf(&mut self, bandwidth: DlpfBandwidth) -> Result<(), ()> {
        self.write_register(MPU6000_CONFIG, bandwidth as u8)?;
        debug!("DLPF bandwidth set to {:?}", bandwidth);
        Ok(())
    }

    /// Read IMU data (accel + gyro + temp)
    pub fn read_data(&mut self) -> Result<ImuData, ()> {
        // Read 14 bytes starting from ACCEL_XOUT_H:
        // ACCEL_XOUT (2), ACCEL_YOUT (2), ACCEL_ZOUT (2),
        // TEMP_OUT (2),
        // GYRO_XOUT (2), GYRO_YOUT (2), GYRO_ZOUT (2)
        let mut buf = [0u8; 14];
        self.read_registers(MPU6000_ACCEL_XOUT_H, &mut buf)?;

        // Parse accelerometer data (raw -> m/s²)
        let accel_x_raw = i16::from_be_bytes([buf[0], buf[1]]);
        let accel_y_raw = i16::from_be_bytes([buf[2], buf[3]]);
        let accel_z_raw = i16::from_be_bytes([buf[4], buf[5]]);

        let accel = Vec3::new(
            accel_x_raw as f32 * self.accel_scale * 9.80665,
            accel_y_raw as f32 * self.accel_scale * 9.80665,
            accel_z_raw as f32 * self.accel_scale * 9.80665,
        );

        // Parse temperature (raw -> °C)
        let temp_raw = i16::from_be_bytes([buf[6], buf[7]]);
        let temp = temp_raw as f32 / 340.0 + 36.53;

        // Parse gyroscope data (raw -> rad/s)
        let gyro_x_raw = i16::from_be_bytes([buf[8], buf[9]]);
        let gyro_y_raw = i16::from_be_bytes([buf[10], buf[11]]);
        let gyro_z_raw = i16::from_be_bytes([buf[12], buf[13]]);

        let gyro = Vec3::new(
            gyro_x_raw as f32 * self.gyro_scale * 0.017453293, // deg/s to rad/s
            gyro_y_raw as f32 * self.gyro_scale * 0.017453293,
            gyro_z_raw as f32 * self.gyro_scale * 0.017453293,
        );

        trace!("IMU: accel=({}, {}, {}), gyro=({}, {}, {}), temp={}",
               accel.x, accel.y, accel.z, gyro.x, gyro.y, gyro.z, temp);

        Ok(ImuData { accel, gyro, temp })
    }

    /// Check if data is ready
    pub fn is_data_ready(&mut self) -> Result<bool, ()> {
        let status = self.read_register(MPU6000_INT_STATUS)?;
        Ok((status & 0x01) != 0)
    }

    /// Read single register
    fn read_register(&mut self, reg: u8) -> Result<u8, ()> {
        let mut rx = [0u8; 2];
        let tx = [reg | 0x80, 0x00]; // Set MSB for read

        self.select()?;
        let r = self.spi.transfer(&mut rx, &tx).map_err(|_| ());
        self.deselect()?;
        r?;
        Ok(rx[1])
    }

    /// Write single register
    fn write_register(&mut self, reg: u8, val: u8) -> Result<(), ()> {
        let tx = [reg & 0x7F, val]; // Clear MSB for write

        self.select()?;
        let r = self.spi.write(&tx).map_err(|_| ());
        self.deselect()?;
        r
    }

    /// Read multiple registers
    fn read_registers(&mut self, reg: u8, buf: &mut [u8]) -> Result<(), ()> {
        let mut tx = [0u8; 15];
        tx[0] = reg | 0x80; // Set MSB for read

        let mut rx = [0u8; 15];
        let len = buf.len() + 1;

        self.select()?;
        let r = self.spi.transfer(&mut rx[..len], &tx[..len]).map_err(|_| ());
        self.deselect()?;
        r?;
        buf.copy_from_slice(&rx[1..len]);
        Ok(())
    }
}

/// Simple delay function (TODO: use proper timer-based delay)
fn delay_ms(ms: u32) {
    let cycles = ms * 168_000; // Approximate for 168MHz (see bsp::clocks)
    for _ in 0..cycles {
        cortex_m::asm::nop();
    }
}
