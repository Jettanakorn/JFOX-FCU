//! Clock configuration for STM32F427VIT6
//!
//! Configures the MCU to run at 180MHz using the external 24MHz crystal (HSE).
//!
//! Clock tree:
//! - HSE: 24MHz (external crystal)
//! - PLL: 24MHz / 12 * 180 / 2 = 180MHz
//! - SYSCLK: 180MHz
//! - AHB (HCLK): 180MHz (÷1)
//! - APB1 (PCLK1): 45MHz (÷4, max 45MHz)
//! - APB2 (PCLK2): 90MHz (÷2, max 90MHz)

use defmt::info;

/// RCC (Reset and Clock Control) register base address
const RCC_BASE: u32 = 0x4002_3800;

/// Flash interface register base address
const FLASH_BASE: u32 = 0x4002_3C00;

/// Clock frequencies
pub const HSE_FREQ_HZ: u32 = 24_000_000;
pub const SYSCLK_FREQ_HZ: u32 = 180_000_000;
pub const HCLK_FREQ_HZ: u32 = 180_000_000;
pub const PCLK1_FREQ_HZ: u32 = 45_000_000;
pub const PCLK2_FREQ_HZ: u32 = 90_000_000;

/// System clock configuration
pub struct Clocks {
    pub sysclk: u32,
    pub hclk: u32,
    pub pclk1: u32,
    pub pclk2: u32,
}

impl Clocks {
    /// Configure system clocks to 180MHz
    ///
    /// This function performs the following:
    /// 1. Enable HSE (24MHz external crystal)
    /// 2. Configure PLL: 24MHz / 12 * 180 / 2 = 180MHz
    /// 3. Configure flash latency (5 wait states @ 180MHz)
    /// 4. Set bus prescalers (AHB, APB1, APB2)
    /// 5. Switch SYSCLK to PLL
    ///
    /// # Safety
    ///
    /// Must be called only once during initialization, before any peripherals are initialized.
    pub unsafe fn configure() -> Self {
        info!("Configuring clocks for 180MHz operation...");

        let rcc = RCC_BASE as *mut u32;
        let flash_acr = FLASH_BASE as *mut u32;

        // ==== Step 1: Enable HSE ====
        info!("Enabling HSE (24MHz)...");
        let cr = rcc.add(0x00 / 4);
        cr.write_volatile(cr.read_volatile() | (1 << 16)); // RCC_CR |= HSEON

        // Wait for HSE to become ready
        while (cr.read_volatile() & (1 << 17)) == 0 {} // Wait for HSERDY
        info!("HSE ready");

        // ==== Step 2: Configure PLL ====
        info!("Configuring PLL...");
        // PLL configuration register (RCC_PLLCFGR)
        // PLLM=12, PLLN=180, PLLP=2 (/2), PLLQ=7, PLLSRC=HSE
        let pllcfgr = (12 << 0)      // PLLM: Divide 24MHz by 12 = 2MHz
                    | (180 << 6)     // PLLN: Multiply by 180 = 360MHz
                    | (0 << 16)      // PLLP: Divide by 2 = 180MHz (00b = /2)
                    | (7 << 24)      // PLLQ: Divide by 7 for USB (360/7 ≈ 51MHz)
                    | (1 << 22);     // PLLSRC: HSE as PLL source

        rcc.add(0x04 / 4).write_volatile(pllcfgr);

        // Enable PLL
        cr.write_volatile(cr.read_volatile() | (1 << 24)); // RCC_CR |= PLLON

        // Wait for PLL to lock
        while (cr.read_volatile() & (1 << 25)) == 0 {} // Wait for PLLRDY
        info!("PLL locked at 180MHz");

        // ==== Step 3: Configure Flash latency ====
        info!("Configuring Flash latency...");
        // 5 wait states required for 180MHz @ 3.3V
        // Also enable instruction/data caches and prefetch
        flash_acr.write_volatile(
            (5 << 0) |  // LATENCY = 5
            (1 << 8) |  // PRFTEN: Prefetch enable
            (1 << 9) |  // ICEN: Instruction cache enable
            (1 << 10)   // DCEN: Data cache enable
        );

        // ==== Step 4: Configure bus prescalers ====
        info!("Configuring bus prescalers...");
        let cfgr = rcc.add(0x08 / 4);
        cfgr.write_volatile(
            (0 << 4) |   // HPRE: AHB prescaler = 1 (180MHz)
            (5 << 10) |  // PPRE1: APB1 prescaler = 4 (45MHz, max 45MHz)
            (4 << 13)    // PPRE2: APB2 prescaler = 2 (90MHz, max 90MHz)
        );

        // ==== Step 5: Switch SYSCLK to PLL ====
        info!("Switching SYSCLK to PLL...");
        let cfgr_val = cfgr.read_volatile();
        cfgr.write_volatile((cfgr_val & !0x3) | 0x2); // SW[1:0] = 10b (PLL)

        // Wait until PLL is used as system clock
        while (cfgr.read_volatile() & 0xC) != 0x8 {} // Wait for SWS[1:0] = 10b

        info!("Clock configuration complete:");
        info!("  SYSCLK: {}MHz", SYSCLK_FREQ_HZ / 1_000_000);
        info!("  HCLK:   {}MHz", HCLK_FREQ_HZ / 1_000_000);
        info!("  PCLK1:  {}MHz", PCLK1_FREQ_HZ / 1_000_000);
        info!("  PCLK2:  {}MHz", PCLK2_FREQ_HZ / 1_000_000);

        Self {
            sysclk: SYSCLK_FREQ_HZ,
            hclk: HCLK_FREQ_HZ,
            pclk1: PCLK1_FREQ_HZ,
            pclk2: PCLK2_FREQ_HZ,
        }
    }

    /// Get the current SYSCLK frequency
    pub fn sysclk(&self) -> u32 {
        self.sysclk
    }

    /// Get the AHB bus (HCLK) frequency
    pub fn hclk(&self) -> u32 {
        self.hclk
    }

    /// Get the APB1 bus (PCLK1) frequency
    pub fn pclk1(&self) -> u32 {
        self.pclk1
    }

    /// Get the APB2 bus (PCLK2) frequency
    pub fn pclk2(&self) -> u32 {
        self.pclk2
    }

    /// Get timer clock frequency on APB1
    /// (APB1 timers run at 2x PCLK1 when prescaler != 1)
    pub fn tim_pclk1(&self) -> u32 {
        self.pclk1 * 2 // 90MHz
    }

    /// Get timer clock frequency on APB2
    /// (APB2 timers run at 2x PCLK2 when prescaler != 1)
    pub fn tim_pclk2(&self) -> u32 {
        self.pclk2 * 2 // 180MHz
    }
}
