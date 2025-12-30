//! Pin definitions from PX4FMUv2.4.5 schematic
//!
//! This module provides type-safe pin definitions extracted from the hardware schematic.
//! All pin assignments are based on the STM32F427VIT6 pinout.

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

// ==== SPI1 - MPU-6000 (Primary IMU) ====
/// SPI1 SCK - PE13 (AF5)
pub type Spi1Sck = Pin<'E', 13, Alternate<5>>;
/// SPI1 MISO - PE14 (AF5)
pub type Spi1Miso = Pin<'E', 14, Alternate<5>>;
/// SPI1 MOSI - PE15 (AF5)
pub type Spi1Mosi = Pin<'E', 15, Alternate<5>>;
/// MPU-6000 Chip Select - PC2
pub type Mpu6000Cs = Pin<'C', 2, Output>;
/// MPU-6000 Data Ready - PD15
pub type Mpu6000Drdy = Pin<'D', 15, Input<PullUp>>;

// ==== SPI2 - FRAM ====
/// SPI2 SCK - PD13 (AF5)
pub type Spi2Sck = Pin<'D', 13, Alternate<5>>;
/// SPI2 MISO - PD14 (AF5)
pub type Spi2Miso = Pin<'D', 14, Alternate<5>>;
/// SPI2 MOSI - PD15 (AF5)
pub type Spi2Mosi = Pin<'D', 15, Alternate<5>>;
/// FRAM Chip Select - PD10
pub type FramCs = Pin<'D', 10, Output>;

// ==== SPI4 - External sensors ====
/// SPI4 SCK - PE12 (AF5)
pub type Spi4Sck = Pin<'E', 12, Alternate<5>>;
/// SPI4 MISO - PE13 (AF5)
pub type Spi4Miso = Pin<'E', 13, Alternate<5>>;
/// SPI4 MOSI - PE14 (AF5)
pub type Spi4Mosi = Pin<'E', 14, Alternate<5>>;

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

// ==== UART1 - Telemetry/Serial1 ====
/// UART1 TX - PA9 (AF7)
pub type Uart1Tx = Pin<'A', 9, Alternate<7>>;
/// UART1 RX - PA10 (AF7)
pub type Uart1Rx = Pin<'A', 10, Alternate<7>>;

// ==== UART2 - Telemetry/Serial2 ====
/// UART2 TX - PD5 (AF7)
pub type Uart2Tx = Pin<'D', 5, Alternate<7>>;
/// UART2 RX - PD6 (AF7)
pub type Uart2Rx = Pin<'D', 6, Alternate<7>>;

// ==== UART3 - Serial3/GPS ====
/// UART3 TX - PD8 (AF7)
pub type Uart3Tx = Pin<'D', 8, Alternate<7>>;
/// UART3 RX - PD9 (AF7)
pub type Uart3Rx = Pin<'D', 9, Alternate<7>>;

// ==== UART4 - GPS/Serial4 ====
/// UART4 TX - PA0 (AF8)
pub type Uart4Tx = Pin<'A', 0, Alternate<8>>;
/// UART4 RX - PA1 (AF8)
pub type Uart4Rx = Pin<'A', 1, Alternate<8>>;

// ==== PWM Outputs (TIM1/TIM4 for motor control) ====
/// PWM Channel 1 - PE14 (TIM1_CH4, AF1)
pub type Pwm1 = Pin<'E', 14, Alternate<1>>;
/// PWM Channel 2 - PE13 (TIM1_CH3, AF1)
pub type Pwm2 = Pin<'E', 13, Alternate<1>>;
/// PWM Channel 3 - PE11 (TIM1_CH2, AF1)
pub type Pwm3 = Pin<'E', 11, Alternate<1>>;
/// PWM Channel 4 - PE9 (TIM1_CH1, AF1)
pub type Pwm4 = Pin<'E', 9, Alternate<1>>;
/// PWM Channel 5 - PD13 (TIM4_CH2, AF2)
pub type Pwm5 = Pin<'D', 13, Alternate<2>>;
/// PWM Channel 6 - PD14 (TIM4_CH3, AF2)
pub type Pwm6 = Pin<'D', 14, Alternate<2>>;
/// PWM Channel 7 - PD12 (TIM4_CH1, AF2)
pub type Pwm7 = Pin<'D', 12, Alternate<2>>;
/// PWM Channel 8 - PD15 (TIM4_CH4, AF2)
pub type Pwm8 = Pin<'D', 15, Alternate<2>>;

// ==== CAN Bus ====
/// CAN1 TX - PD1 (AF9)
pub type Can1Tx = Pin<'D', 1, Alternate<9>>;
/// CAN1 RX - PD0 (AF9)
pub type Can1Rx = Pin<'D', 0, Alternate<9>>;

// ==== USB OTG FS ====
/// USB D- - PA11 (AF10)
pub type UsbDm = Pin<'A', 11, Alternate<10>>;
/// USB D+ - PA12 (AF10)
pub type UsbDp = Pin<'A', 12, Alternate<10>>;

// ==== Safety Switch ====
/// Safety switch input - PB11
pub type SafetySwitch = Pin<'B', 11, Input<PullUp>>;
/// Safety LED output - PB1
pub type SafetyLed = Pin<'B', 1, Output>;

// ==== Spektrum/DSM RC Input ====
/// Spektrum receiver UART - PB7
pub type SpektrumRx = Pin<'B', 7, Input>;

// ==== S.Bus Input/Output ====
/// S.Bus input/output - PC6 (UART6_TX, AF8)
pub type SbusPin = Pin<'C', 6, Alternate<8>>;

// ==== ADC for Power Sensing ====
/// VDD voltage sensing - PA2 (ADC1_IN2)
pub type VddSenseAdc = Pin<'A', 2, Analog>;
/// Current sensing - PA3 (ADC1_IN3)
pub type CurrentSenseAdc = Pin<'A', 3, Analog>;
/// 5V rail sensing - PA4 (ADC1_IN4)
pub type V5SenseAdc = Pin<'A', 4, Analog>;

// ==== Pressure Sensor (Analog) ====
/// Pressure sensor ADC - PC1 (ADC1_IN11)
pub type PressureSenseAdc = Pin<'C', 1, Analog>;

// ==== Status LEDs (via TCA62724 I2C LED Driver) ====
/// These are controlled via I2C2, not direct GPIO
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
/// BOOT1 - PB2
pub type Boot1 = Pin<'B', 2, Input>;
