//! Pin definitions from PX4FMUv2.4.5 schematic
//!
//! This module provides type-safe pin definitions extracted from the hardware schematic
//! (`docs/PX4FMUv2.4.5.pdf`, sheet 1/12 "FMU SoC Ports / FRAM" and the timer-allocation
//! note on sheet 3). All pin assignments are for the STM32F427VIT6 ("FMU") pinout.
//!
//! ## FMU-only board note
//!
//! Real PX4FMUv2.4.5 hardware is a **two-MCU design**: this STM32F427 ("FMU") handles
//! sensors/compute, and a separate STM32F100 co-processor ("IO", not implemented by this
//! project) generates the primary 8 "MAIN OUT" motor PWM channels, decodes RC input
//! (PPM/S.Bus/Spektrum), and gates everything behind a hardware safety switch. None of
//! that IO-side circuitry is reachable from this chip. This firmware runs FMU-only: motor
//! output uses the FMU's own 6 built-in "AUX"-class PWM channels (`FmuCh1`..`FmuCh6`
//! below) instead of the IO chip's 8, and there is no safety-switch/Spektrum/S.Bus input
//! available on this chip in this architecture.
//!
//! Prior versions of this file placed SPI1 on PE13/14/15 and SPI4 on PE12/13/14, which
//! directly collided with the PWM pins below and does not match the schematic; those
//! assignments have been corrected. AF (alternate function) numbers not explicitly
//! visible in the schematic text were carried over from the pre-existing convention
//! (SPI1/2/4 -> AF5, matching typical STM32F427 SPI alternate-function mapping) and
//! should be cross-checked against the STM32F427 datasheet AF table during hal/spi.rs
//! bring-up.

use core::marker::PhantomData;

/// GPIO pin with port, number, and mode
pub struct Pin<const PORT: char, const NUM: u8, MODE> {
    _mode: PhantomData<MODE>,
}

/// Pin modes
pub struct Input<PULL = Floating> {
    _pull: PhantomData<PULL>,
}
pub struct Output;
pub struct Analog;
pub struct Alternate<const AF: u8>;

/// Pull-up/Pull-down configuration
pub struct Floating;
pub struct PullUp;
pub struct PullDown;

// ==== SPI1 - MPU-6000 (Primary IMU) / internal sensor bus ("SPI_INT") ====
/// SPI1 SCK - PA5 (AF5)
pub type Spi1Sck = Pin<'A', 5, Alternate<5>>;
/// SPI1 MISO - PA6 (AF5)
pub type Spi1Miso = Pin<'A', 6, Alternate<5>>;
/// SPI1 MOSI - PA7 (AF5)
pub type Spi1Mosi = Pin<'A', 7, Alternate<5>>;
/// MPU-6000 Chip Select - PC2
pub type Mpu6000Cs = Pin<'C', 2, Output>;
/// MPU-6000 Data Ready - PD15
pub type Mpu6000Drdy = Pin<'D', 15, Input<PullUp>>;
/// Backup gyro (L3GD20) Chip Select - PC13, shares the SPI1/SPI_INT bus
pub type GyroCs = Pin<'C', 13, Output>;
/// Backup accel/mag (LSM303D) Chip Select - PC15, shares the SPI1/SPI_INT bus
pub type AccelMagCs = Pin<'C', 15, Output>;
/// Barometer (MS5611) Chip Select - PD7, shares the SPI1/SPI_INT bus
pub type BaroCs = Pin<'D', 7, Output>;

// ==== SPI2 - FRAM (FM25V01) ====
/// SPI2 SCK - PB13 (AF5)
pub type Spi2Sck = Pin<'B', 13, Alternate<5>>;
/// SPI2 MISO - PB14 (AF5)
pub type Spi2Miso = Pin<'B', 14, Alternate<5>>;
/// SPI2 MOSI - PB15 (AF5)
pub type Spi2Mosi = Pin<'B', 15, Alternate<5>>;
/// FRAM Chip Select - PD10
pub type FramCs = Pin<'D', 10, Output>;

// ==== SPI4 - External sensors ("SPI_EXT") ====
/// SPI4 SCK - PE2 (AF5)
pub type Spi4Sck = Pin<'E', 2, Alternate<5>>;
/// SPI4 NSS - PE4 (AF5)
pub type Spi4Nss = Pin<'E', 4, Alternate<5>>;
/// SPI4 MISO - PE5 (AF5)
pub type Spi4Miso = Pin<'E', 5, Alternate<5>>;
/// SPI4 MOSI - PE6 (AF5)
pub type Spi4Mosi = Pin<'E', 6, Alternate<5>>;

// ==== I2C1 - External sensors ====
/// I2C1 SCL - PB8 (AF4)
pub type I2c1Scl = Pin<'B', 8, Alternate<4>>;
/// I2C1 SDA - PB9 (AF4)
pub type I2c1Sda = Pin<'B', 9, Alternate<4>>;

// ==== I2C2 - LED driver (TCA62724) ====
/// I2C2 SCL - PB10 (AF4)
pub type I2c2Scl = Pin<'B', 10, Alternate<4>>;
/// I2C2 SDA - PB11 (AF4)
pub type I2c2Sda = Pin<'B', 11, Alternate<4>>;

// ==== UART1 (USART1) ====
/// UART1 TX - PA9 (AF7). Note: PA9 is also the VBUS-sense net on this board, and in the
/// dual-MCU reference design PA10 carries the IO-coprocessor debug console, not general
/// telemetry. Usable as a general-purpose UART in FMU-only builds; verify PA9 has no
/// conflicting analog load before relying on it.
pub type Uart1Tx = Pin<'A', 9, Alternate<7>>;
/// UART1 RX - PA10 (AF7)
pub type Uart1Rx = Pin<'A', 10, Alternate<7>>;

// ==== UART2 (USART2) ====
/// UART2 TX - PD5 (AF7)
pub type Uart2Tx = Pin<'D', 5, Alternate<7>>;
/// UART2 RX - PD6 (AF7)
pub type Uart2Rx = Pin<'D', 6, Alternate<7>>;
/// UART2 CTS - PD3 (AF7)
pub type Uart2Cts = Pin<'D', 3, Alternate<7>>;
/// UART2 RTS - PD4 (AF7)
pub type Uart2Rts = Pin<'D', 4, Alternate<7>>;

// ==== UART3 (USART3) - GPS ====
/// UART3 TX - PD8 (AF7)
pub type Uart3Tx = Pin<'D', 8, Alternate<7>>;
/// UART3 RX - PD9 (AF7)
pub type Uart3Rx = Pin<'D', 9, Alternate<7>>;
/// UART3 CTS - PD11 (AF7)
pub type Uart3Cts = Pin<'D', 11, Alternate<7>>;
/// UART3 RTS - PD12 (AF7)
pub type Uart3Rts = Pin<'D', 12, Alternate<7>>;

// ==== UART4 - GPS ====
/// UART4 TX - PA0 (AF8)
pub type Uart4Tx = Pin<'A', 0, Alternate<8>>;
/// UART4 RX - PA1 (AF8)
pub type Uart4Rx = Pin<'A', 1, Alternate<8>>;

// ==== UART7 ====
/// UART7 TX - PE8 (AF8)
pub type Uart7Tx = Pin<'E', 8, Alternate<8>>;
/// UART7 RX - PE7 (AF8)
pub type Uart7Rx = Pin<'E', 7, Alternate<8>>;

// ==== UART8 ====
/// UART8 TX - PE1 (AF8)
pub type Uart8Tx = Pin<'E', 1, Alternate<8>>;
/// UART8 RX - PE0 (AF8)
pub type Uart8Rx = Pin<'E', 0, Alternate<8>>;

// ==== FMU<->IO serial link (unused in FMU-only builds) ====
/// SERIAL_FMU_TO_IO - PC6. Free general-purpose pin when no IO co-processor is present.
pub type SerialFmuToIo = Pin<'C', 6, Alternate<7>>;
/// SERIAL_IO_TO_FMU - PC7. Free general-purpose pin when no IO co-processor is present.
pub type SerialIoToFmu = Pin<'C', 7, Alternate<7>>;

// ==== PWM Outputs - FMU-CH1..CH6 (TIM1/TIM4) ====
// Real PX4FMUv2.4.5 hardware only exposes 6 PWM channels directly on the FMU; the other
// 8 ("MAIN OUT") are generated by the separate IO co-processor this project doesn't
// implement (see module doc). PD12 and PD15 are NOT PWM pins on this chip (PD12 is
// Uart3Rts, PD15 is Mpu6000Drdy) - the previous 8-channel Pwm7/Pwm8 aliases on those
// pins have been removed.
/// PWM Channel 1 (FMU-CH1) - PE14 (TIM1_CH4, AF1)
pub type Pwm1 = Pin<'E', 14, Alternate<1>>;
/// PWM Channel 2 (FMU-CH2) - PE13 (TIM1_CH3, AF1)
pub type Pwm2 = Pin<'E', 13, Alternate<1>>;
/// PWM Channel 3 (FMU-CH3) - PE11 (TIM1_CH2, AF1)
pub type Pwm3 = Pin<'E', 11, Alternate<1>>;
/// PWM Channel 4 (FMU-CH4) - PE9 (TIM1_CH1, AF1)
pub type Pwm4 = Pin<'E', 9, Alternate<1>>;
/// PWM Channel 5 (FMU-CH5) - PD13 (TIM4_CH2, AF2)
pub type Pwm5 = Pin<'D', 13, Alternate<2>>;
/// PWM Channel 6 (FMU-CH6) - PD14 (TIM4_CH3, AF2)
pub type Pwm6 = Pin<'D', 14, Alternate<2>>;

// ==== CAN Bus ====
/// CAN1 TX - PD1 (AF9)
pub type Can1Tx = Pin<'D', 1, Alternate<9>>;
/// CAN1 RX - PD0 (AF9)
pub type Can1Rx = Pin<'D', 0, Alternate<9>>;
/// CAN2 TX - PB6 (AF9)
pub type Can2Tx = Pin<'B', 6, Alternate<9>>;
/// CAN2 RX - PB12 (AF9)
pub type Can2Rx = Pin<'B', 12, Alternate<9>>;

// ==== USB OTG FS ====
/// USB D- - PA11 (AF10)
pub type UsbDm = Pin<'A', 11, Alternate<10>>;
/// USB D+ - PA12 (AF10)
pub type UsbDp = Pin<'A', 12, Alternate<10>>;

// ==== Piezo Alarm ====
/// Alarm driver output - PA15 (TIM2_CH1)
pub type Alarm = Pin<'A', 15, Alternate<1>>;

// ==== Status LED (direct GPIO, in addition to the I2C2 TCA62724 RGB driver) ====
/// FMU amber LED - PE12. Direct GPIO, safe to use for e.g. a heartbeat/status indicator;
/// does not collide with any SPI/PWM/CAN pin above.
pub type FmuLedAmber = Pin<'E', 12, Output>;

// ==== ADC for Power/Sensor Sensing ====
/// Battery voltage sensing - PA2 (ADC1_IN2)
pub type VddSenseAdc = Pin<'A', 2, Analog>;
/// Battery current sensing - PA3 (ADC1_IN3)
pub type CurrentSenseAdc = Pin<'A', 3, Analog>;
/// 5V rail sensing - PA4 (ADC1_IN4)
pub type V5SenseAdc = Pin<'A', 4, Analog>;
/// Pressure sensor ADC - PC5 (analog baro option; PC1 is a separate spare ADC channel)
pub type PressureSenseAdc = Pin<'C', 5, Analog>;

// ==== Status LEDs (via TCA62724 I2C LED Driver on I2C2) ====
pub struct StatusLeds;

impl StatusLeds {
    pub const RED: u8 = 0;
    pub const GREEN: u8 = 1;
    pub const BLUE: u8 = 2;
}

// ==== Debug/SWD Interface ====
/// SWDIO - PA13
pub type Swdio = Pin<'A', 13, Alternate<0>>;
/// SWCLK - PA14
pub type Swclk = Pin<'A', 14, Alternate<0>>;

// ==== Boot Configuration ====
/// BOOT0 - Must be low for normal operation
/// BOOT1 - PB2 (fixed silicon function, independent of board net naming)
pub type Boot1 = Pin<'B', 2, Input>;
