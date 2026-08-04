//! Board Support Package for JFOX FCU - PX4 FMUv2 family (2.4.5 / Pixhawk 2.4.8)
//!
//! This crate provides board-specific definitions including:
//! - Pin mappings from the hardware schematic
//! - Clock configuration for STM32F427VIT6
//! - Memory map constants
//! - Power management interfaces

#![no_std]

pub mod pins;
pub mod clocks;
pub mod memory_map;

/// Re-export commonly used items
pub use pins::*;
pub use clocks::Clocks;
