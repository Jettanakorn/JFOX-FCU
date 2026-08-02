//! FM25V01 FRAM (128Kbit / 16KB) storage driver, used for persistent
//! accelerometer calibration (see `flight::calibration::storage`). Standard
//! SPI FRAM command set, 2-byte (14-bit) addressing.
//!
//! Unlike `drivers::Mpu6000` (which currently has no working chip-select
//! control at all - see the CS pin note in that driver, flagged as a
//! separate follow-up), this driver takes an explicit CS pin and toggles it
//! around every transaction, since FRAM absolutely requires CS assertion to
//! respond and this chip shares SPI2 with nothing else today but must not be
//! left permanently selected.

use defmt::{debug, trace};
use embedded_hal::digital::OutputPin;
use embedded_hal::spi::SpiBus;

const CMD_WREN: u8 = 0x06; // write enable
const CMD_WRDI: u8 = 0x04; // write disable
const CMD_RDSR: u8 = 0x05; // read status register
const CMD_READ: u8 = 0x03; // read memory
const CMD_WRITE: u8 = 0x02; // write memory

pub const CAPACITY_BYTES: u16 = 16 * 1024; // 128Kbit

pub struct Fm25v01<SPI, CS> {
    spi: SPI,
    cs: CS,
}

impl<SPI, CS> Fm25v01<SPI, CS>
where
    SPI: SpiBus,
    CS: OutputPin,
{
    pub fn new(spi: SPI, cs: CS) -> Self {
        Self { spi, cs }
    }

    fn select(&mut self) -> Result<(), ()> {
        self.cs.set_low().map_err(|_| ())
    }

    fn deselect(&mut self) -> Result<(), ()> {
        self.cs.set_high().map_err(|_| ())
    }

    /// Read the status register - a cheap way to confirm the chip is present
    /// and responding before trusting any read/write, used by the power-on
    /// BIT FRAM self-test.
    pub fn read_status(&mut self) -> Result<u8, ()> {
        self.select()?;
        let mut rx = [0u8; 2];
        let tx = [CMD_RDSR, 0x00];
        let r = self.spi.transfer(&mut rx, &tx).map_err(|_| ());
        self.deselect()?;
        r?;
        Ok(rx[1])
    }

    pub fn read(&mut self, addr: u16, buf: &mut [u8]) -> Result<(), ()> {
        trace!("FRAM read {} bytes @ 0x{:04X}", buf.len(), addr);
        self.select()?;
        let cmd = [CMD_READ, (addr >> 8) as u8, addr as u8];
        let w = self.spi.write(&cmd).map_err(|_| ());
        let r = w.and_then(|_| self.spi.read(buf).map_err(|_| ()));
        self.deselect()?;
        r
    }

    pub fn write(&mut self, addr: u16, data: &[u8]) -> Result<(), ()> {
        trace!("FRAM write {} bytes @ 0x{:04X}", data.len(), addr);
        self.write_enable()?;

        self.select()?;
        let cmd = [CMD_WRITE, (addr >> 8) as u8, addr as u8];
        let w = self.spi.write(&cmd).map_err(|_| ());
        let r = w.and_then(|_| self.spi.write(data).map_err(|_| ()));
        self.deselect()?;
        r?;

        self.write_disable()
    }

    fn write_enable(&mut self) -> Result<(), ()> {
        self.select()?;
        let r = self.spi.write(&[CMD_WREN]).map_err(|_| ());
        self.deselect()?;
        r
    }

    fn write_disable(&mut self) -> Result<(), ()> {
        self.select()?;
        let r = self.spi.write(&[CMD_WRDI]).map_err(|_| ());
        self.deselect()?;
        r
    }

    /// Write a known pattern to `addr`, read it back, and confirm it matches
    /// - a real read/write self-test, not just a status-register presence
    /// check. Used by the power-on BIT sequence. `addr` should be a scratch
    /// location distinct from any real stored data (see
    /// `flight::calibration::storage`'s doc comment for the address it
    /// reserves) so this can never corrupt a real record.
    pub fn self_test(&mut self, scratch_addr: u16) -> Result<bool, ()> {
        const PATTERN: [u8; 4] = [0xA5, 0x5A, 0x3C, 0xC3];
        self.write(scratch_addr, &PATTERN)?;
        let mut readback = [0u8; 4];
        self.read(scratch_addr, &mut readback)?;
        let ok = readback == PATTERN;
        debug!("FRAM self-test: {}", ok);
        Ok(ok)
    }
}
