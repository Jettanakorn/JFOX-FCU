//! Hardware Abstraction Layer for STM32F427VIT6
//!
//! Provides bare-metal register-level access to STM32F4 peripherals:
//! - GPIO: Digital I/O with type-safe pin modes
//! - SPI: SPI1/2/4/5 for sensor communication
//! - UART: UART1-4 for telemetry and GPS
//! - Timer: TIM1-14 for PWM and timing
//! - PWM: Motor control output
//! - ADC: Analog-to-digital conversion
//! - DMA: Direct memory access
//! - I2C: I2C1/2 for sensor communication

#![no_std]

pub mod gpio;
pub mod spi;
pub mod uart;
pub mod timer;
pub mod pwm;
pub mod adc;
pub mod i2c;
pub mod dma;
pub mod dwt;
pub mod can;

/// Re-export commonly used items
pub use gpio::*;
pub use spi::*;
