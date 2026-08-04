//! UART peripheral implementation with direct register access
//!
//! Supports UART1-4 for telemetry, GPS, and debug output.

use bsp::memory_map::*;
use core::fmt;
use defmt::trace;

/// UART peripheral
pub struct Uart<const N: u8> {
    base: u32,
}

impl<const N: u8> Uart<N> {
    const fn base_addr() -> u32 {
        match N {
            1 => USART1_BASE,
            2 => USART2_BASE,
            3 => USART3_BASE,
            4 => UART4_BASE,
            _ => panic!("Invalid UART number"),
        }
    }

    /// Create new UART instance
    ///
    /// # Safety
    ///
    /// Caller must ensure exclusive access to the UART peripheral
    pub unsafe fn new() -> Self {
        let uart = Self {
            base: Self::base_addr(),
        };

        // Enable UART clock
        uart.enable_clock();

        uart
    }

    unsafe fn enable_clock(&self) {
        let (reg, bit) = match N {
            1 => (RCC_BASE + 0x44, 4),  // RCC_APB2ENR, USART1EN
            2 => (RCC_BASE + 0x40, 17), // RCC_APB1ENR, USART2EN
            3 => (RCC_BASE + 0x40, 18), // RCC_APB1ENR, USART3EN
            4 => (RCC_BASE + 0x40, 19), // RCC_APB1ENR, UART4EN
            _ => panic!("Invalid UART"),
        };

        let enr = reg as *mut u32;
        enr.write_volatile(enr.read_volatile() | (1 << bit));
    }

    /// Initialize UART with specified baud rate
    ///
    /// Assumes system is already clocked:
    /// - USART1 on APB2 (`bsp::clocks::PCLK2_FREQ_HZ`)
    /// - USART2-4 on APB1 (`bsp::clocks::PCLK1_FREQ_HZ`)
    pub fn init(&mut self, baud: u32) {
        unsafe {
            let cr1 = (self.base + 0x0C) as *mut u32;
            let brr = (self.base + 0x08) as *mut u32;

            // Disable UART
            cr1.write_volatile(0);

            // Calculate baud rate divisor
            // BRR = fCK / (16 * baud)
            // Taken from bsp rather than hardcoded: these must track
            // `bsp::clocks::Clocks::configure()`'s prescalers, and a stale
            // copy here silently skews every baud rate.
            let clock = match N {
                1 => bsp::clocks::PCLK2_FREQ_HZ, // APB2
                _ => bsp::clocks::PCLK1_FREQ_HZ, // APB1
            };
            let divisor = clock / (16 * baud);
            brr.write_volatile(divisor);

            // Configure UART:
            // - 8 data bits
            // - 1 stop bit
            // - No parity
            // - TX enable, RX enable
            let cr1_val = (1 << 13) // UE: UART enable
                        | (1 << 3)  // TE: Transmitter enable
                        | (1 << 2); // RE: Receiver enable

            cr1.write_volatile(cr1_val);
        }

        trace!("UART{} initialized at {} baud", N, baud);
    }

    /// Send a single byte (blocking)
    pub fn write_byte(&mut self, data: u8) {
        unsafe {
            let sr = (self.base + 0x00) as *const u32;
            let dr = (self.base + 0x04) as *mut u8;

            // Wait for TXE (transmit data register empty)
            while (sr.read_volatile() & (1 << 7)) == 0 {}

            dr.write_volatile(data);
        }
    }

    /// Send a string (blocking)
    pub fn write_str(&mut self, s: &str) {
        for byte in s.as_bytes() {
            self.write_byte(*byte);
        }
    }

    /// Read a single byte (blocking)
    pub fn read_byte(&mut self) -> u8 {
        unsafe {
            let sr = (self.base + 0x00) as *const u32;
            let dr = (self.base + 0x04) as *const u8;

            // Wait for RXNE (read data register not empty)
            while (sr.read_volatile() & (1 << 5)) == 0 {}

            dr.read_volatile()
        }
    }

    /// Check if data is available to read
    pub fn data_available(&self) -> bool {
        unsafe {
            let sr = (self.base + 0x00) as *const u32;
            (sr.read_volatile() & (1 << 5)) != 0
        }
    }
}

/// Implement core::fmt::Write for UART
impl<const N: u8> fmt::Write for Uart<N> {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        self.write_str(s);
        Ok(())
    }
}
