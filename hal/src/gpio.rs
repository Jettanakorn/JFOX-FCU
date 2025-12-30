//! GPIO peripheral implementation with type-safe modes
//!
//! Provides direct register access to GPIO ports with compile-time mode checking.

use bsp::memory_map::*;
use core::marker::PhantomData;

/// GPIO port
pub struct Port<const P: char>;

impl<const P: char> Port<P> {
    const fn base_addr() -> u32 {
        match P {
            'A' => GPIOA_BASE,
            'B' => GPIOB_BASE,
            'C' => GPIOC_BASE,
            'D' => GPIOD_BASE,
            'E' => GPIOE_BASE,
            'F' => GPIOF_BASE,
            'G' => GPIOG_BASE,
            'H' => GPIOH_BASE,
            _ => panic!("Invalid GPIO port"),
        }
    }

    /// Enable clock for this GPIO port
    pub unsafe fn enable_clock() {
        let rcc_ahb1enr = (RCC_BASE + 0x30) as *mut u32;
        let port_bit = match P {
            'A' => 0,
            'B' => 1,
            'C' => 2,
            'D' => 3,
            'E' => 4,
            'F' => 5,
            'G' => 6,
            'H' => 7,
            _ => panic!("Invalid GPIO port"),
        };
        rcc_ahb1enr.write_volatile(rcc_ahb1enr.read_volatile() | (1 << port_bit));
    }
}

/// GPIO pin with port, number, and mode
pub struct Pin<const P: char, const N: u8, MODE> {
    _mode: PhantomData<MODE>,
}

/// Pin modes
pub struct Input<PULL = Floating> {
    _pull: PhantomData<PULL>,
}
pub struct Output;
pub struct Analog;
pub struct Alternate<const AF: u8>;

/// Pull configuration
pub struct Floating;
pub struct PullUp;
pub struct PullDown;

/// Trait for pull configuration
pub trait PullMode {
    fn pull_bits() -> u32;
}

impl PullMode for Floating {
    fn pull_bits() -> u32 { 0x0 }
}

impl PullMode for PullUp {
    fn pull_bits() -> u32 { 0x1 }
}

impl PullMode for PullDown {
    fn pull_bits() -> u32 { 0x2 }
}

impl<const P: char, const N: u8, MODE> Pin<P, N, MODE> {
    const fn base() -> u32 {
        Port::<P>::base_addr()
    }

    /// Initialize pin (enables clock if not already enabled)
    pub unsafe fn new() -> Self {
        Port::<P>::enable_clock();
        Self {
            _mode: PhantomData,
        }
    }
}

impl<const P: char, const N: u8> Pin<P, N, Output> {
    /// Configure pin as push-pull output
    pub unsafe fn into_output(self) -> Self {
        let moder = (Self::base() + 0x00) as *mut u32;
        let otyper = (Self::base() + 0x04) as *mut u32;
        let ospeedr = (Self::base() + 0x08) as *mut u32;

        // Set mode to output (01)
        let mode_val = moder.read_volatile();
        moder.write_volatile((mode_val & !(0x3 << (N * 2))) | (0x1 << (N * 2)));

        // Set output type to push-pull (0)
        let otype_val = otyper.read_volatile();
        otyper.write_volatile(otype_val & !(1 << N));

        // Set speed to high (10)
        let speed_val = ospeedr.read_volatile();
        ospeedr.write_volatile((speed_val & !(0x3 << (N * 2))) | (0x2 << (N * 2)));

        self
    }

    /// Set pin high
    pub fn set_high(&mut self) {
        unsafe {
            let bsrr = (Self::base() + 0x18) as *mut u32;
            bsrr.write_volatile(1 << N);
        }
    }

    /// Set pin low
    pub fn set_low(&mut self) {
        unsafe {
            let bsrr = (Self::base() + 0x18) as *mut u32;
            bsrr.write_volatile(1 << (N + 16));
        }
    }

    /// Toggle pin
    pub fn toggle(&mut self) {
        unsafe {
            let odr = (Self::base() + 0x14) as *mut u32;
            odr.write_volatile(odr.read_volatile() ^ (1 << N));
        }
    }
}

impl<const P: char, const N: u8, PULL: PullMode> Pin<P, N, Input<PULL>> {
    /// Configure pin as input
    pub unsafe fn into_input(self) -> Self {
        let moder = (Self::base() + 0x00) as *mut u32;
        let pupdr = (Self::base() + 0x0C) as *mut u32;

        // Set mode to input (00)
        let mode_val = moder.read_volatile();
        moder.write_volatile(mode_val & !(0x3 << (N * 2)));

        // Set pull-up/pull-down using trait
        let pull_val = pupdr.read_volatile();
        let pull_bits = PULL::pull_bits();
        pupdr.write_volatile((pull_val & !(0x3 << (N * 2))) | (pull_bits << (N * 2)));

        self
    }

    /// Read pin state
    pub fn is_high(&self) -> bool {
        unsafe {
            let idr = (Self::base() + 0x10) as *const u32;
            (idr.read_volatile() & (1 << N)) != 0
        }
    }

    /// Read pin state (inverted)
    pub fn is_low(&self) -> bool {
        !self.is_high()
    }
}

impl<const P: char, const N: u8, const AF: u8> Pin<P, N, Alternate<AF>> {
    /// Configure pin as alternate function
    pub unsafe fn into_alternate(self) -> Self {
        let moder = (Self::base() + 0x00) as *mut u32;
        let afr = if N < 8 {
            (Self::base() + 0x20) as *mut u32 // AFRL
        } else {
            (Self::base() + 0x24) as *mut u32 // AFRH
        };
        let ospeedr = (Self::base() + 0x08) as *mut u32;

        // Set mode to alternate function (10)
        let mode_val = moder.read_volatile();
        moder.write_volatile((mode_val & !(0x3 << (N * 2))) | (0x2 << (N * 2)));

        // Set alternate function
        let afr_offset = (N % 8) * 4;
        let afr_val = afr.read_volatile();
        afr.write_volatile((afr_val & !(0xF << afr_offset)) | ((AF as u32) << afr_offset));

        // Set speed to high
        let speed_val = ospeedr.read_volatile();
        ospeedr.write_volatile((speed_val & !(0x3 << (N * 2))) | (0x2 << (N * 2)));

        self
    }
}
