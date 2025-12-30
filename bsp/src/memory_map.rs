//! Memory map constants for STM32F427VIT6
//!
//! This module defines base addresses for all peripherals and memory regions.

// ==== Memory Regions ====
pub const FLASH_BASE: u32 = 0x0800_0000;
pub const FLASH_SIZE: u32 = 2 * 1024 * 1024; // 2MB

pub const SRAM_BASE: u32 = 0x2000_0000;
pub const SRAM_SIZE: u32 = 192 * 1024; // 192KB

pub const CCMRAM_BASE: u32 = 0x1000_0000;
pub const CCMRAM_SIZE: u32 = 64 * 1024; // 64KB

// ==== AHB1 Peripherals ====
pub const GPIOA_BASE: u32 = 0x4002_0000;
pub const GPIOB_BASE: u32 = 0x4002_0400;
pub const GPIOC_BASE: u32 = 0x4002_0800;
pub const GPIOD_BASE: u32 = 0x4002_0C00;
pub const GPIOE_BASE: u32 = 0x4002_1000;
pub const GPIOF_BASE: u32 = 0x4002_1400;
pub const GPIOG_BASE: u32 = 0x4002_1800;
pub const GPIOH_BASE: u32 = 0x4002_1C00;

pub const RCC_BASE: u32 = 0x4002_3800;
pub const FLASH_R_BASE: u32 = 0x4002_3C00;
pub const DMA1_BASE: u32 = 0x4002_6000;
pub const DMA2_BASE: u32 = 0x4002_6400;

// ==== APB1 Peripherals ====
pub const TIM2_BASE: u32 = 0x4000_0000;
pub const TIM3_BASE: u32 = 0x4000_0400;
pub const TIM4_BASE: u32 = 0x4000_0800;
pub const TIM5_BASE: u32 = 0x4000_0C00;
pub const TIM6_BASE: u32 = 0x4000_1000;
pub const TIM7_BASE: u32 = 0x4000_1400;
pub const TIM12_BASE: u32 = 0x4000_1800;
pub const TIM13_BASE: u32 = 0x4000_1C00;
pub const TIM14_BASE: u32 = 0x4000_2000;

pub const SPI2_BASE: u32 = 0x4000_3800;
pub const SPI3_BASE: u32 = 0x4000_3C00;

pub const USART2_BASE: u32 = 0x4000_4400;
pub const USART3_BASE: u32 = 0x4000_4800;
pub const UART4_BASE: u32 = 0x4000_4C00;
pub const UART5_BASE: u32 = 0x4000_5000;

pub const I2C1_BASE: u32 = 0x4000_5400;
pub const I2C2_BASE: u32 = 0x4000_5800;
pub const I2C3_BASE: u32 = 0x4000_5C00;

pub const CAN1_BASE: u32 = 0x4000_6400;
pub const CAN2_BASE: u32 = 0x4000_6800;

pub const PWR_BASE: u32 = 0x4000_7000;

// ==== APB2 Peripherals ====
pub const TIM1_BASE: u32 = 0x4001_0000;
pub const TIM8_BASE: u32 = 0x4001_0400;

pub const USART1_BASE: u32 = 0x4001_1000;
pub const USART6_BASE: u32 = 0x4001_1400;

pub const ADC1_BASE: u32 = 0x4001_2000;
pub const ADC2_BASE: u32 = 0x4001_2100;
pub const ADC3_BASE: u32 = 0x4001_2200;
pub const ADC_COMMON_BASE: u32 = 0x4001_2300;

pub const SPI1_BASE: u32 = 0x4001_3000;
pub const SPI4_BASE: u32 = 0x4001_3400;
pub const SPI5_BASE: u32 = 0x4001_5000;
pub const SPI6_BASE: u32 = 0x4001_5400;

pub const SYSCFG_BASE: u32 = 0x4001_3800;
pub const EXTI_BASE: u32 = 0x4001_3C00;

pub const TIM9_BASE: u32 = 0x4001_4000;
pub const TIM10_BASE: u32 = 0x4001_4400;
pub const TIM11_BASE: u32 = 0x4001_4800;

// ==== AHB2 Peripherals ====
pub const USB_OTG_FS_BASE: u32 = 0x5000_0000;

// ==== Cortex-M4 Core Peripherals ====
pub const NVIC_BASE: u32 = 0xE000_E100;
pub const SCB_BASE: u32 = 0xE000_ED00;
pub const SYSTICK_BASE: u32 = 0xE000_E010;
pub const FPU_BASE: u32 = 0xE000_EF30;
