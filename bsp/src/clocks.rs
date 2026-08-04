//! Clock configuration for STM32F427VIT6
//!
//! Configures the MCU to run at 168MHz using the external 24MHz crystal (HSE).
//!
//! Clock tree:
//! - HSE: 24MHz (external crystal)
//! - PLL: 24MHz / 12 * 168 / 2 = 168MHz
//! - SYSCLK: 168MHz
//! - AHB (HCLK): 168MHz (÷1)
//! - APB1 (PCLK1): 42MHz (÷4, max 45MHz)
//! - APB2 (PCLK2): 84MHz (÷2, max 90MHz)
//! - PLLQ -> USB48: 48MHz exactly (336MHz VCO / 7), the only 48MHz source this
//!   part has - see the "why 168MHz, not 180MHz" note on `Clocks::configure()`.
//!
//! # Why 168MHz and not the part's 180MHz maximum
//!
//! USB OTG FS requires 48MHz +-0.25%, and on STM32F42x/43x that clock can come
//! *only* from the main PLL's Q-output (PLL48CK). Unlike the STM32F446/F469 and
//! F412/F413, this part has no `RCC_DCKCFGR2`/`CK48MSEL` mux and therefore no
//! way to feed USB from PLLSAI instead - RM0090's RCC register map ends at
//! `DCKCFGR` (0x8C), which is why this project's `stm32f4` PAC models nothing
//! beyond it.
//!
//! A 180MHz SYSCLK needs a 360MHz VCO (PLLP=/2), and 360 has no integer PLLQ
//! giving 48 (360/7.5). A 336MHz VCO does: 336/7 = 48 exactly, with PLLP=/2
//! giving 168MHz. So on this silicon, exact USB and 180MHz are mutually
//! exclusive, and working USB was chosen over the extra 12MHz.
//!
//! An earlier revision of this file ran at 180MHz and tried to route PLLSAI to
//! USB by writing `CK48MSEL` at offset 0x90. On real hardware that write lands
//! on reserved space and does nothing: USB kept running from PLLQ at 360/7 ~=
//! 51.43MHz (7.1% fast), and Windows enumeration failed with "Configuration
//! Descriptor Request Failed" under a null VID/PID. That is the bug this
//! configuration fixes.

use defmt::info;

/// RCC (Reset and Clock Control) register base address
const RCC_BASE: u32 = 0x4002_3800;

/// Flash interface register base address
const FLASH_BASE: u32 = 0x4002_3C00;

/// Clock frequencies
pub const HSE_FREQ_HZ: u32 = 24_000_000;
pub const SYSCLK_FREQ_HZ: u32 = 168_000_000;
pub const HCLK_FREQ_HZ: u32 = 168_000_000;
pub const PCLK1_FREQ_HZ: u32 = 42_000_000;
pub const PCLK2_FREQ_HZ: u32 = 84_000_000;
/// USB OTG FS requires 48MHz +-0.25%, supplied here by the main PLL's
/// Q-output: 336MHz VCO / PLLQ=7 = 48MHz exactly, with zero error. This is
/// the only 48MHz source on STM32F42x/43x - see the module-level note on why
/// that constrains SYSCLK to 168MHz.
pub const USB48_FREQ_HZ: u32 = 48_000_000;

/// System clock configuration
pub struct Clocks {
    pub sysclk: u32,
    pub hclk: u32,
    pub pclk1: u32,
    pub pclk2: u32,
}

impl Clocks {
    /// Configure system clocks to 168MHz
    ///
    /// This function performs the following:
    /// 1. Enable HSE (24MHz external crystal)
    /// 2. Configure PLL: 24MHz / 12 * 168 / 2 = 168MHz, PLLQ=7 -> 48MHz USB
    /// 3. Configure flash latency (5 wait states @ 168MHz)
    /// 4. Set bus prescalers (AHB, APB1, APB2)
    /// 5. Switch SYSCLK to PLL
    ///
    /// No separate USB-clock step is needed or possible on this part: PLLQ is
    /// the USB 48MHz source, configured in step 2 alongside SYSCLK.
    ///
    /// # Safety
    ///
    /// Must be called only once during initialization, before any peripherals are initialized.
    pub unsafe fn configure() -> Self {
        info!("Configuring clocks for 168MHz operation...");

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
        // PLLM=12, PLLN=168, PLLP=2 (/2), PLLQ=7, PLLSRC=HSE
        let pllcfgr = (12 << 0)      // PLLM: Divide 24MHz by 12 = 2MHz
                    | (168 << 6)     // PLLN: Multiply by 168 = 336MHz VCO
                    | (0 << 16)      // PLLP: Divide by 2 = 168MHz (00b = /2)
                    | (7 << 24)      // PLLQ: Divide by 7 = 48MHz exactly, for USB
                    | (1 << 22);     // PLLSRC: HSE as PLL source

        rcc.add(0x04 / 4).write_volatile(pllcfgr);

        // Enable PLL
        cr.write_volatile(cr.read_volatile() | (1 << 24)); // RCC_CR |= PLLON

        // Wait for PLL to lock
        while (cr.read_volatile() & (1 << 25)) == 0 {} // Wait for PLLRDY
        info!("PLL locked at 168MHz (PLLQ = 48MHz for USB)");

        // ==== Step 3: Configure Flash latency ====
        info!("Configuring Flash latency...");
        // 5 wait states required for 168MHz @ 3.3V (VOS scale 1: 150 < HCLK <= 168)
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
            (0 << 4) |   // HPRE: AHB prescaler = 1 (168MHz)
            (5 << 10) |  // PPRE1: APB1 prescaler = 4 (42MHz, max 45MHz)
            (4 << 13)    // PPRE2: APB2 prescaler = 2 (84MHz, max 90MHz)
        );

        // ==== Step 5: Switch SYSCLK to PLL ====
        info!("Switching SYSCLK to PLL...");
        let cfgr_val = cfgr.read_volatile();
        cfgr.write_volatile((cfgr_val & !0x3) | 0x2); // SW[1:0] = 10b (PLL)

        // Wait until PLL is used as system clock
        while (cfgr.read_volatile() & 0xC) != 0x8 {} // Wait for SWS[1:0] = 10b

        // No step 6: the USB 48MHz clock needs no separate configuration on
        // this part. PLLQ=7 against the 336MHz VCO set in step 2 already
        // yields exactly 48MHz, and PLL48CK is hardwired to USB OTG FS /
        // SDIO / RNG - STM32F42x/43x has no CK48MSEL mux to select anything
        // else. See this module's "Why 168MHz" note for the history here.

        info!("Clock configuration complete:");
        info!("  SYSCLK: {}MHz", SYSCLK_FREQ_HZ / 1_000_000);
        info!("  HCLK:   {}MHz", HCLK_FREQ_HZ / 1_000_000);
        info!("  PCLK1:  {}MHz", PCLK1_FREQ_HZ / 1_000_000);
        info!("  PCLK2:  {}MHz", PCLK2_FREQ_HZ / 1_000_000);
        info!("  USB48:  {}MHz (via PLLQ)", USB48_FREQ_HZ / 1_000_000);

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
        self.pclk1 * 2 // 84MHz
    }

    /// Get timer clock frequency on APB2
    /// (APB2 timers run at 2x PCLK2 when prescaler != 1)
    pub fn tim_pclk2(&self) -> u32 {
        self.pclk2 * 2 // 168MHz
    }
}
