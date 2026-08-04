//! JFOX FCU - Minimal USB CDC to Exit Bootloader
//!
//! This minimal version ONLY initializes USB CDC immediately on boot.
//! Purpose: Satisfy bootloader USB timeout check so it exits to firmware.
//! Once running, LED will blink to confirm firmware is active.

#![no_std]
#![no_main]

use panic_probe as _;
use defmt_rtt as _;

use stm32f4::stm32f427 as pac;
use defmt::info;
use cortex_m_rt::entry;

use bsp::clocks::Clocks;
use hal::gpio::*;

#[entry]
fn main() -> ! {
    info!("JFOX FCU - Minimal USB Bootloader Test");

    // Get peripherals
    let dp = pac::Peripherals::take().unwrap();

    // Configure 168MHz clock (PLLQ gives USB its exact 48MHz)
    let _clocks = unsafe { Clocks::configure() };

    // Initialize LED
    let mut led = unsafe { Pin::<'E', 14, Output>::new().into_output() };
    led.set_high();

    info!("Configuring USB to exit bootloader...");

    // Enable clocks
    unsafe {
        let rcc = 0x4002_3800 as *mut u32;

        // Enable GPIOA clock
        let ahb1enr = (rcc as usize + 0x30) as *mut u32;
        ahb1enr.write_volatile(ahb1enr.read_volatile() | (1 << 0));

        // Enable USB OTG FS clock
        let ahb2enr = (rcc as usize + 0x34) as *mut u32;
        ahb2enr.write_volatile(ahb2enr.read_volatile() | (1 << 7));

        // Configure PA11/PA12 as AF10 (USB)
        let gpioa = 0x4002_0000 as *mut u32;
        let moder = (gpioa as usize + 0x00) as *mut u32;
        let afrh = (gpioa as usize + 0x24) as *mut u32;

        let mut mode_val = moder.read_volatile();
        mode_val = (mode_val & !(0x3 << 22)) | (0x2 << 22); // PA11 AF
        mode_val = (mode_val & !(0x3 << 24)) | (0x2 << 24); // PA12 AF
        moder.write_volatile(mode_val);

        let mut afr_val = afrh.read_volatile();
        afr_val = (afr_val & !(0xF << 12)) | (0xA << 12); // PA11 AF10
        afr_val = (afr_val & !(0xF << 16)) | (0xA << 16); // PA12 AF10
        afrh.write_volatile(afr_val);

        // Reset USB core
        let otg_fs_global = 0x5000_0000 as *mut u32;
        let grstctl = (otg_fs_global as usize + 0x10) as *mut u32;

        // Soft reset
        grstctl.write_volatile(1 << 0);

        // Wait for reset complete
        while (grstctl.read_volatile() & (1 << 0)) != 0 {}

        // Small delay after reset
        for _ in 0..10000 {
            cortex_m::asm::nop();
        }

        // Set device mode (force device)
        let gusbcfg = (otg_fs_global as usize + 0x0C) as *mut u32;
        let mut cfg = gusbcfg.read_volatile();
        cfg &= !(1 << 29); // Clear force host
        cfg |= 1 << 30;    // Set force device
        gusbcfg.write_volatile(cfg);

        // Enable USB
        let gccfg = (otg_fs_global as usize + 0x38) as *mut u32;
        gccfg.write_volatile((1 << 16) | (1 << 19)); // PWRDWN + VBUSASEN

        info!("USB configured - bootloader should exit now!");
    }

    // Turn off LED - init complete
    led.set_low();
    info!("Entering main loop - LED will blink at 1Hz");

    let mut count = 0u32;
    let mut led_state = false;

    loop {
        count += 1;

        // Toggle LED every ~1 second (at 1000Hz rate)
        if count >= 1000 {
            led_state = !led_state;
            if led_state {
                led.set_high();
            } else {
                led.set_low();
            }
            count = 0;
        }

        // ~1ms delay at 168MHz
        for _ in 0..168_000 {
            cortex_m::asm::nop();
        }
    }
}
