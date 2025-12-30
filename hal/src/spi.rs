//! SPI peripheral implementation with direct register access
//!
//! Supports SPI1, SPI2, SPI4, and SPI5 for sensor communication.
//! SPI1 is used for MPU-6000 (primary IMU).
//! SPI2 is used for FRAM storage.

use bsp::memory_map::*;
use defmt::{debug, trace};

/// SPI peripheral
pub struct Spi<const N: u8> {
    base: u32,
}

impl<const N: u8> Spi<N> {
    const fn base_addr() -> u32 {
        match N {
            1 => SPI1_BASE,
            2 => SPI2_BASE,
            4 => SPI4_BASE,
            5 => SPI5_BASE,
            _ => panic!("Invalid SPI number"),
        }
    }

    /// Create new SPI instance
    ///
    /// # Safety
    ///
    /// Caller must ensure exclusive access to the SPI peripheral
    pub unsafe fn new() -> Self {
        let spi = Self {
            base: Self::base_addr(),
        };

        // Enable SPI clock
        spi.enable_clock();

        spi
    }

    unsafe fn enable_clock(&self) {
        let (reg, bit) = match N {
            1 => (RCC_BASE + 0x44, 12), // RCC_APB2ENR, SPI1EN
            2 => (RCC_BASE + 0x40, 14), // RCC_APB1ENR, SPI2EN
            4 => (RCC_BASE + 0x44, 13), // RCC_APB2ENR, SPI4EN
            5 => (RCC_BASE + 0x44, 20), // RCC_APB2ENR, SPI5EN
            _ => panic!("Invalid SPI"),
        };

        let enr = reg as *mut u32;
        enr.write_volatile(enr.read_volatile() | (1 << bit));
    }

    /// Initialize SPI in Mode 3 (CPOL=1, CPHA=1)
    ///
    /// Mode 3 is required for MPU-6000 and many other sensors.
    ///
    /// # Arguments
    ///
    /// * `br_div` - Baud rate divider (0-7)
    ///   - 0: fPCLK/2
    ///   - 1: fPCLK/4
    ///   - 2: fPCLK/8
    ///   - 3: fPCLK/16
    ///   - 4: fPCLK/32
    ///   - 5: fPCLK/64
    ///   - 6: fPCLK/128
    ///   - 7: fPCLK/256
    pub fn init_mode3(&mut self, br_div: u8) {
        debug!("Initializing SPI{} in mode 3, baud rate div={}", N, 1 << (br_div + 1));

        unsafe {
            let cr1 = (self.base + 0x00) as *mut u32;
            let cr2 = (self.base + 0x04) as *mut u32;

            // Disable SPI first
            cr1.write_volatile(0);

            // Configure SPI:
            // - Master mode (MSTR)
            // - Mode 3: CPOL=1, CPHA=1
            // - 8-bit data
            // - MSB first
            // - Software slave management
            let cr1_val = (1 << 2)              // MSTR: Master
                        | ((br_div as u32 & 0x7) << 3)  // BR: Baud rate
                        | (1 << 0)              // CPHA: Phase 1
                        | (1 << 1)              // CPOL: Polarity 1 (Mode 3)
                        | (1 << 9)              // SSM: Software slave management
                        | (1 << 8);             // SSI: Internal slave select

            cr1.write_volatile(cr1_val);

            // Configure CR2 (optional features)
            cr2.write_volatile(0);

            // Enable SPI
            cr1.write_volatile(cr1.read_volatile() | (1 << 6)); // SPE: SPI enable
        }

        debug!("SPI{} initialized", N);
    }

    /// Initialize SPI in Mode 0 (CPOL=0, CPHA=0)
    pub fn init_mode0(&mut self, br_div: u8) {
        debug!("Initializing SPI{} in mode 0, baud rate div={}", N, 1 << (br_div + 1));

        unsafe {
            let cr1 = (self.base + 0x00) as *mut u32;
            let cr2 = (self.base + 0x04) as *mut u32;

            cr1.write_volatile(0);

            let cr1_val = (1 << 2)              // MSTR: Master
                        | ((br_div as u32 & 0x7) << 3)  // BR: Baud rate
                        | (1 << 9)              // SSM: Software slave management
                        | (1 << 8);             // SSI: Internal slave select

            cr1.write_volatile(cr1_val);
            cr2.write_volatile(0);

            cr1.write_volatile(cr1.read_volatile() | (1 << 6));
        }

        debug!("SPI{} initialized", N);
    }

    /// Transfer a single byte (blocking)
    pub fn transfer_byte(&mut self, data: u8) -> u8 {
        unsafe {
            let dr = (self.base + 0x0C) as *mut u8;
            let sr = (self.base + 0x08) as *const u32;

            // Wait for TXE (transmit buffer empty)
            while (sr.read_volatile() & (1 << 1)) == 0 {}
            dr.write_volatile(data);

            // Wait for RXNE (receive buffer not empty)
            while (sr.read_volatile() & (1 << 0)) == 0 {}
            dr.read_volatile()
        }
    }

    /// Transfer a buffer (blocking)
    pub fn transfer(&mut self, tx: &[u8], rx: &mut [u8]) {
        let len = tx.len().min(rx.len());
        trace!("SPI{} transfer {} bytes", N, len);

        for i in 0..len {
            rx[i] = self.transfer_byte(tx[i]);
        }
    }

    /// Write-only transfer (discard received data)
    pub fn write(&mut self, data: &[u8]) {
        trace!("SPI{} write {} bytes", N, data.len());

        for &byte in data {
            self.transfer_byte(byte);
        }
    }

    /// Read-only transfer (send 0x00)
    pub fn read(&mut self, buffer: &mut [u8]) {
        trace!("SPI{} read {} bytes", N, buffer.len());

        for byte in buffer.iter_mut() {
            *byte = self.transfer_byte(0x00);
        }
    }
}

/// Implement embedded-hal SPI traits
impl<const N: u8> embedded_hal::spi::ErrorType for Spi<N> {
    type Error = core::convert::Infallible;
}

impl<const N: u8> embedded_hal::spi::SpiBus for Spi<N> {
    fn read(&mut self, words: &mut [u8]) -> Result<(), Self::Error> {
        self.read(words);
        Ok(())
    }

    fn write(&mut self, words: &[u8]) -> Result<(), Self::Error> {
        self.write(words);
        Ok(())
    }

    fn transfer(&mut self, read: &mut [u8], write: &[u8]) -> Result<(), Self::Error> {
        self.transfer(write, read);
        Ok(())
    }

    fn transfer_in_place(&mut self, words: &mut [u8]) -> Result<(), Self::Error> {
        // Transfer in-place by reading each byte back
        for byte in words.iter_mut() {
            *byte = self.transfer_byte(*byte);
        }
        Ok(())
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        unsafe {
            let sr = (self.base + 0x08) as *const u32;
            // Wait for BSY (busy) flag to clear
            while (sr.read_volatile() & (1 << 7)) != 0 {}
        }
        Ok(())
    }
}
