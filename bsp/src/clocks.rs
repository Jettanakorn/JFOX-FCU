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
//! - PLLSAI -> USB48: 48MHz (24MHz/12 * 96 / 4), routed to USB OTG FS/SDIO/RNG
//!   via CK48MSEL - the main PLL's Q-output cannot hit 48MHz exactly against
//!   this file's 360MHz VCO, see the PLLSAI step in `Clocks::configure()`.

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
/// USB OTG FS requires 48MHz +-0.25%. The main PLL's Q-output cannot
/// produce this exactly against this file's 360MHz VCO (360/PLLQ has no
/// integer solution equal to 48) - see `Clocks::configure()`'s PLLSAI step.
pub const USB48_FREQ_HZ: u32 = 48_000_000;

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

        // ==== Step 6: Configure PLLSAI for a spec-correct 48MHz USB clock ====
        // The main PLL's Q-output (PLLQ=7 against this 360MHz VCO) gives
        // ~51.43MHz, not the 48MHz (+-0.25%) USB Full Speed requires - 360MHz
        // has no integer PLLQ that divides to exactly 48MHz. STM32F427 has a
        // second PLL (PLLSAI) for exactly this kind of secondary-clock
        // conflict: same PLLM input (2MHz) as the main PLL, its own VCO
        // multiplier/dividers.
        // PLLSAIN=96 -> VCO = 2MHz * 96 = 192MHz (must be 100-432MHz: OK).
        // PLLSAIP=/4 (encoded 01b) -> 192MHz / 4 = 48MHz exactly.
        info!("Configuring PLLSAI for 48MHz USB clock...");
        let pllsaicfgr = rcc.add(0x88 / 4);
        // PLLSAIN (bits 6:14) and PLLSAIP (bits 16:17) confirmed against
        // this project's stm32f4 0.15.1 PAC: pllsaicfgr's reset value
        // (0x2400_3000) decodes to PLLSAIQ=4/PLLSAIR=2 at the PAC's named
        // bit positions, and bits 16:17 read 0 in that reset value,
        // consistent with PLLSAIP's documented reset default - the PAC just
        // doesn't expose PLLSAIP as a named field. PLLSAIQ/PLLSAIR (SAI1/LCD
        // dividers) are left at 0 - unused, this project has no SAI1/LCD.
        let pllsain: u32 = 96 << 6;
        let pllsaip: u32 = 0b01 << 16;
        pllsaicfgr.write_volatile(pllsain | pllsaip);

        // Enable PLLSAI (RCC_CR bit 28, confirmed against the PAC's
        // rcc::cr::pllsaion()) and wait for lock (bit 29, pllsairdy()) - same
        // register already used above for HSEON/HSERDY and PLLON/PLLRDY.
        cr.write_volatile(cr.read_volatile() | (1 << 28)); // PLLSAION
        while (cr.read_volatile() & (1 << 29)) == 0 {} // Wait for PLLSAIRDY
        info!("PLLSAI locked at 48MHz");

        // Route PLLSAI's 48MHz output (not the main PLL's ~51.4MHz PLLQ
        // output) to USB OTG FS/SDIO/RNG via CK48MSEL.
        //
        // UNVERIFIED IN THIS ENVIRONMENT: unlike every other register write
        // in this function, this one (RCC_DCKCFGR2 at offset 0x90, CK48MSEL
        // at bit 27) is NOT modeled by this project's stm32f4 0.15.1 PAC at
        // all - its generated RCC register block stops at DCKCFGR (0x8C),
        // and that register (which IS modeled) turns out to be unrelated
        // (SAI1/LCD/timer-prescaler muxing only, no CK48MSEL field). The
        // offset and bit position below are from STM32F42x/43x reference-
        // manual (RM0090) knowledge with NO independent cross-check
        // available in this environment (no RM0090 copy in this repo, PAC
        // doesn't model this register). CONFIRM AGAINST THE REAL RM0090 (or
        // real hardware USB enumeration behavior) BEFORE TRUSTING THIS - this
        // is the one exception to this project's usual verify-before-trust
        // discipline, forced by an incomplete PAC, not a deliberate one.
        info!("Routing PLLSAI 48MHz to USB via CK48MSEL (UNVERIFIED register - see comment)...");
        let dckcfgr2 = rcc.add(0x90 / 4);
        dckcfgr2.write_volatile(dckcfgr2.read_volatile() | (1 << 27)); // CK48MSEL = 1 (PLLSAI)

        info!("Clock configuration complete:");
        info!("  SYSCLK: {}MHz", SYSCLK_FREQ_HZ / 1_000_000);
        info!("  HCLK:   {}MHz", HCLK_FREQ_HZ / 1_000_000);
        info!("  PCLK1:  {}MHz", PCLK1_FREQ_HZ / 1_000_000);
        info!("  PCLK2:  {}MHz", PCLK2_FREQ_HZ / 1_000_000);
        info!("  USB48:  {}MHz (via PLLSAI)", USB48_FREQ_HZ / 1_000_000);

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
