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

// Expected WHO_AM_I values. The two ICM parts are register-compatible with
// the MPU-6000 for everything this driver uses - see `init()`.
const MPU6000_WHO_AM_I_VALUE: u8 = 0x68;
const ICM20602_WHO_AM_I_VALUE: u8 = 0x12;
const ICM20608_WHO_AM_I_VALUE: u8 = 0xAF;

/// Which part actually answered on the primary IMU chip select.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ImuVariant {
    Mpu6000,
    /// Accepted on register compatibility; not verified on silicon here.
    Icm20602,
    /// Accepted on register compatibility; not verified on silicon here.
    Icm20608,
}

impl ImuVariant {
    pub fn name(&self) -> &'static str {
        match self {
            ImuVariant::Mpu6000 => "MPU-6000",
            ImuVariant::Icm20602 => "ICM-20602",
            ImuVariant::Icm20608 => "ICM-20608",
        }
    }

    /// Whether this part has been confirmed working on real hardware by this
    /// project, as opposed to accepted from its datasheet.
    pub fn is_hardware_verified(&self) -> bool {
        matches!(self, ImuVariant::Mpu6000)
    }
}

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

    /// Initialize the IMU.
    ///
    /// Performs device reset, verifies WHO_AM_I, and configures the sensor.
    ///
    /// # Accepted parts
    ///
    /// The MPU-6000 (`0x68`) and two register-compatible InvenSense successors
    /// commonly substituted for it on Pixhawk 2.4.8 clones: the ICM-20602
    /// (`0x12`) and ICM-20608 (`0xAF`). Every register this driver touches -
    /// `PWR_MGMT_1`, `USER_CTRL`, `CONFIG`, `GYRO_CONFIG`, `ACCEL_CONFIG`,
    /// `SMPLRT_DIV`, and the `ACCEL_XOUT_H` burst - has the same address,
    /// meaning and data layout on all three, and the ±2000 °/s and ±16 g
    /// full-scale codes and sensitivities are identical.
    ///
    /// **This compatibility is read from the parts' register maps, not
    /// verified on silicon here.** It is accepted because refusing a working
    /// sensor outright is worse: the previous behaviour was to return `Err`,
    /// which left the fusion filter permanently unfed and the attitude pinned
    /// at zero with no indication of why. Which part actually answered is
    /// returned so the caller can report it.
    pub fn init(&mut self) -> Result<ImuVariant, ()> {
        info!("Initializing IMU...");

        // Small delay after power-on
        delay_ms(50);

        // Check WHO_AM_I register
        let who_am_i = self.read_register(MPU6000_WHO_AM_I)?;
        let variant = match who_am_i {
            MPU6000_WHO_AM_I_VALUE => ImuVariant::Mpu6000,
            ICM20602_WHO_AM_I_VALUE => ImuVariant::Icm20602,
            ICM20608_WHO_AM_I_VALUE => ImuVariant::Icm20608,
            other => {
                warn!(
                    "IMU WHO_AM_I unrecognised: got 0x{:02X}, expected 0x68 (MPU-6000), 0x12 (ICM-20602) or 0xAF (ICM-20608)",
                    other
                );
                return Err(());
            }
        };
        info!("IMU WHO_AM_I 0x{:02X} -> {}", who_am_i, variant.name());

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

        info!("{} initialization complete", variant.name());
        Ok(variant)
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
