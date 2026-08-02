//! PWM output implementation for motor control
//!
//! Drives TIM1 (FMU-CH1..CH4, advanced-control timer on APB2) and TIM4
//! (FMU-CH5/CH6, general-purpose timer on APB1) in PWM mode 1, 1us/tick
//! resolution, for standard 1000-2000us ESC pulse widths.
//!
//! TIM1 and TIM4 sit on different clock domains (see `bsp::clocks::Clocks`:
//! `tim_pclk2()` = 180MHz for TIM1, `tim_pclk1()` = 90MHz for TIM4) - callers
//! must pass the correct input clock to `init()`, it is not assumed.
//!
//! GPIO alternate-function configuration for the PWM pins (`bsp::pins::Pwm1`..
//! `Pwm6`) is the caller's responsibility, matching the existing `hal::spi`/
//! `hal::uart` convention of not coupling pin muxing into the peripheral driver.

#![allow(dead_code)]

use bsp::memory_map::*;
use defmt::debug;

/// PWM timer peripheral (N=1 -> TIM1/FMU-CH1..CH4, N=4 -> TIM4/FMU-CH5..CH6)
pub struct Pwm<const N: u8> {
    base: u32,
}

impl<const N: u8> Pwm<N> {
    const fn base_addr() -> u32 {
        match N {
            1 => TIM1_BASE,
            4 => TIM4_BASE,
            _ => panic!("Invalid PWM timer number (expected 1 or 4)"),
        }
    }

    /// TIM1 is an advanced-control timer (has RCR + BDTR, CCR1 at offset 0x34);
    /// TIM4 is a general-purpose timer (no RCR, CCR1 at offset 0x30).
    const fn is_advanced() -> bool {
        N == 1
    }

    const fn ccr1_offset() -> u32 {
        if Self::is_advanced() {
            0x34
        } else {
            0x30
        }
    }

    /// Create a new PWM timer instance and enable its peripheral clock.
    ///
    /// # Safety
    ///
    /// Caller must ensure exclusive access to this timer peripheral.
    pub unsafe fn new() -> Self {
        let pwm = Self { base: Self::base_addr() };
        pwm.enable_clock();
        pwm
    }

    unsafe fn enable_clock(&self) {
        let (reg, bit) = match N {
            1 => (RCC_BASE + 0x44, 0), // RCC_APB2ENR, TIM1EN
            4 => (RCC_BASE + 0x40, 2), // RCC_APB1ENR, TIM4EN
            _ => panic!("Invalid PWM timer number"),
        };
        let enr = reg as *mut u32;
        enr.write_volatile(enr.read_volatile() | (1 << bit));
    }

    /// Configure all 4 channels for PWM mode 1, 1us/tick resolution, at the
    /// given refresh rate. `tim_clk_hz` is this timer's actual input clock
    /// (`bsp::clocks::Clocks::tim_pclk2()` for TIM1, `tim_pclk1()` for TIM4)
    /// and must be an exact multiple of 1MHz.
    pub fn init(&mut self, tim_clk_hz: u32, refresh_hz: u32) {
        debug!("Initializing TIM{}: clk={}Hz, refresh={}Hz", N, tim_clk_hz, refresh_hz);
        assert!(tim_clk_hz % 1_000_000 == 0, "PWM timer clock must be a multiple of 1MHz");

        let psc = (tim_clk_hz / 1_000_000) - 1; // 1 tick = 1us
        let arr = (1_000_000 / refresh_hz) - 1; // period in us

        unsafe {
            let cr1 = (self.base + 0x00) as *mut u32;
            let ccmr1 = (self.base + 0x18) as *mut u32;
            let ccmr2 = (self.base + 0x1C) as *mut u32;
            let ccer = (self.base + 0x20) as *mut u32;
            let psc_reg = (self.base + 0x28) as *mut u32;
            let arr_reg = (self.base + 0x2C) as *mut u32;

            // Stop the counter while reconfiguring.
            cr1.write_volatile(0);

            psc_reg.write_volatile(psc);
            arr_reg.write_volatile(arr);

            // PWM mode 1 (OCxM = 110) + preload enable (OCxPE) on all 4 channels.
            // CCMR1: CH1 in bits [6:4]+[3], CH2 in bits [14:12]+[11].
            let ccmr1_val = (0b110 << 4) | (1 << 3) | (0b110 << 12) | (1 << 11);
            ccmr1.write_volatile(ccmr1_val);
            // CCMR2: CH3 in bits [6:4]+[3], CH4 in bits [14:12]+[11].
            let ccmr2_val = (0b110 << 4) | (1 << 3) | (0b110 << 12) | (1 << 11);
            ccmr2.write_volatile(ccmr2_val);

            // Enable all 4 compare outputs, active-high polarity (CCxP=0).
            let ccer_val = (1 << 0) | (1 << 4) | (1 << 8) | (1 << 12);
            ccer.write_volatile(ccer_val);

            if Self::is_advanced() {
                // TIM1 only: main output enable, required for outputs to reach pins.
                let bdtr = (self.base + 0x44) as *mut u32;
                bdtr.write_volatile(1 << 15); // MOE
            }

            // ARPE (auto-reload preload enable) + CEN (counter enable).
            cr1.write_volatile((1 << 7) | (1 << 0));
        }

        debug!("TIM{} PWM initialized: psc={}, arr={}", N, psc, arr);
    }

    const fn ccr_offset(channel: u8) -> u32 {
        assert!(channel >= 1 && channel <= 4, "PWM channel must be 1-4");
        Self::ccr1_offset() + ((channel as u32) - 1) * 4
    }

    /// Set a channel's pulse width directly in microseconds (standard ESC
    /// range is 1000-2000us). `channel` is 1-4.
    pub fn set_channel_us(&mut self, channel: u8, pulse_us: u16) {
        unsafe {
            let ccr = (self.base + Self::ccr_offset(channel)) as *mut u32;
            ccr.write_volatile(pulse_us as u32);
        }
    }

    /// Set a channel's duty cycle as a 0.0..=1.0 fraction of the configured
    /// period (clamped). `channel` is 1-4.
    pub fn set_channel_duty(&mut self, channel: u8, duty: f32) {
        let duty = duty.clamp(0.0, 1.0);
        unsafe {
            let arr_reg = (self.base + 0x2C) as *const u32;
            let arr = arr_reg.read_volatile();
            let ccr = (self.base + Self::ccr_offset(channel)) as *mut u32;
            ccr.write_volatile(((arr as f32 + 1.0) * duty) as u32);
        }
    }
}
