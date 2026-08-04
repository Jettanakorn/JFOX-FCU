//! bxCAN driver for CAN1 (PD0/PD1, see `bsp::pins::Can1Rx`/`Can1Tx`), used for
//! the inter-board TMR voting bus (see `flight::redundancy::TmrVoter` and
//! `common::can_frames`). Hand-rolled register access, matching the rest of
//! `hal`'s style - no PAC dependency in this crate, no `bxcan` crate pulled
//! in (see the same rationale documented for `math::matrix` not using
//! `nalgebra`: this repo hand-rolls its low-level drivers consistently).
//!
//! Only standard (11-bit) identifiers, classic CAN (no CAN-FD), and a single
//! TX mailbox / single RX FIFO (FIFO0) with an accept-all filter are
//! implemented - sufficient for the command-vote/sensor-cross-check traffic
//! this bus carries. Bit timing is computed for a fixed 14-time-quanta bit
//! (1 sync + 11 TS1 + 2 TS2, ~85.7% sample point), chosen because it divides
//! the 42MHz APB1 clock (`bsp::clocks::PCLK1_FREQ_HZ`) evenly for both
//! 500kbps (BRP=6) and 1Mbps (BRP=3) - unverified against a real
//! bus/oscilloscope, flag for hardware bring-up.
//!
//! These constants are clock-dependent: the previous 9-tq bit divided the
//! old 45MHz APB1 evenly, but not the 42MHz that came with the move to a
//! 168MHz SYSCLK (see `bsp::clocks`' "Why 168MHz" note). At 42MHz a 9-tq bit
//! yields a non-integer prescaler and `init()` would reject every bitrate
//! with `BitrateNotAchievable`. Re-check this arithmetic against
//! `PCLK1_FREQ_HZ` if the clock tree changes again.

#![allow(dead_code)]

use bsp::memory_map::*;

const TQ_PER_BIT: u32 = 14; // 1 sync + TS1 + TS2, must equal TS1+TS2+1
const TS1_ACTUAL: u32 = 11; // register field = actual - 1
const TS2_ACTUAL: u32 = 2;
const SJW_ACTUAL: u32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CanBitrate {
    Kbps500,
    Mbps1,
}

impl CanBitrate {
    const fn hz(self) -> u32 {
        match self {
            CanBitrate::Kbps500 => 500_000,
            CanBitrate::Mbps1 => 1_000_000,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CanError {
    /// The MCU never left initialization mode after requesting to (MSR.INAK
    /// never set) - likely a clocking/wiring problem, not a transient fault.
    InitTimeout,
    /// `pclk1_hz` does not divide evenly into `bitrate * TQ_PER_BIT`; the
    /// resulting bit timing would not match the requested rate exactly.
    BitrateNotAchievable,
    /// No TX mailbox was free (all 3 pending). Caller should retry.
    TxBusy,
}

/// A raw CAN data frame: 11-bit standard identifier, 0-8 data bytes.
#[derive(Clone, Copy, Debug)]
pub struct CanFrame {
    pub id: u16,
    pub dlc: u8,
    pub data: [u8; 8],
}

pub struct Can<const N: u8> {
    base: u32,
}

impl<const N: u8> Can<N> {
    const fn base_addr() -> u32 {
        match N {
            1 => CAN1_BASE,
            2 => CAN2_BASE,
            _ => panic!("Invalid CAN peripheral number (expected 1 or 2)"),
        }
    }

    /// # Safety
    ///
    /// Caller must ensure exclusive access to this CAN peripheral.
    pub unsafe fn new() -> Self {
        let can = Self { base: Self::base_addr() };
        can.enable_clock();
        can
    }

    unsafe fn enable_clock(&self) {
        let (reg, bit) = match N {
            1 => (RCC_BASE + 0x40, 25), // RCC_APB1ENR, CAN1EN
            2 => (RCC_BASE + 0x40, 26), // RCC_APB1ENR, CAN2EN
            _ => panic!("Invalid CAN peripheral number"),
        };
        let enr = reg as *mut u32;
        enr.write_volatile(enr.read_volatile() | (1 << bit));
    }

    const fn compute_brp(pclk1_hz: u32, bitrate_hz: u32) -> Option<u32> {
        let denom = bitrate_hz * TQ_PER_BIT;
        if denom == 0 || pclk1_hz % denom != 0 {
            return None;
        }
        let brp = pclk1_hz / denom;
        if brp == 0 || brp > 1024 {
            return None;
        }
        Some(brp - 1) // register field is (actual prescaler - 1)
    }

    /// Enter initialization mode, configure bit timing and an accept-all
    /// filter on FIFO0, then leave initialization mode.
    pub fn init(&mut self, bitrate: CanBitrate, pclk1_hz: u32) -> Result<(), CanError> {
        let brp = Self::compute_brp(pclk1_hz, bitrate.hz()).ok_or(CanError::BitrateNotAchievable)?;

        unsafe {
            let mcr = (self.base + 0x000) as *mut u32;
            let msr = (self.base + 0x004) as *const u32;
            let btr = (self.base + 0x01C) as *mut u32;

            // Request initialization mode (INRQ) and wait for acknowledge (INAK).
            mcr.write_volatile(mcr.read_volatile() | (1 << 0));
            let mut timeout = 100_000u32;
            while (msr.read_volatile() & (1 << 0)) == 0 {
                timeout -= 1;
                if timeout == 0 {
                    return Err(CanError::InitTimeout);
                }
            }

            // Automatic bus-off management (ABOM) so a transient bus fault
            // recovers without firmware intervention - appropriate for a
            // flight-critical link with no human in the loop to reset it.
            mcr.write_volatile(mcr.read_volatile() | (1 << 6));

            // Bit timing: SJW, TS2, TS1 (register values = actual - 1), BRP.
            let btr_val = ((SJW_ACTUAL - 1) << 24)
                | ((TS2_ACTUAL - 1) << 20)
                | ((TS1_ACTUAL - 1) << 16)
                | brp;
            btr.write_volatile(btr_val);

            self.configure_accept_all_filter();

            // Leave initialization mode and wait for acknowledge.
            mcr.write_volatile(mcr.read_volatile() & !(1 << 0));
            let mut timeout = 100_000u32;
            while (msr.read_volatile() & (1 << 0)) != 0 {
                timeout -= 1;
                if timeout == 0 {
                    return Err(CanError::InitTimeout);
                }
            }
        }

        Ok(())
    }

    /// Filter bank 0, 32-bit mask mode, mask=0 (don't-care on every bit) ->
    /// accepts every standard-ID frame, routed to FIFO0. Filter registers are
    /// shared master registers even when configuring CAN2, but this driver
    /// only targets CAN1 in practice (see module docs).
    unsafe fn configure_accept_all_filter(&self) {
        let fmr = (CAN1_BASE + 0x200) as *mut u32;
        let fm1r = (CAN1_BASE + 0x204) as *mut u32;
        let fs1r = (CAN1_BASE + 0x20C) as *mut u32;
        let ffa1r = (CAN1_BASE + 0x214) as *mut u32;
        let fa1r = (CAN1_BASE + 0x21C) as *mut u32;
        let f0r1 = (CAN1_BASE + 0x240) as *mut u32;
        let f0r2 = (CAN1_BASE + 0x244) as *mut u32;

        fmr.write_volatile(fmr.read_volatile() | (1 << 0)); // FINIT: filter init mode
        fm1r.write_volatile(fm1r.read_volatile() & !(1 << 0)); // bank 0: mask mode
        fs1r.write_volatile(fs1r.read_volatile() | (1 << 0)); // bank 0: 32-bit scale
        ffa1r.write_volatile(ffa1r.read_volatile() & !(1 << 0)); // bank 0 -> FIFO0
        f0r1.write_volatile(0); // ID = 0
        f0r2.write_volatile(0); // mask = 0 -> don't care -> accept all
        fa1r.write_volatile(fa1r.read_volatile() | (1 << 0)); // activate bank 0
        fmr.write_volatile(fmr.read_volatile() & !(1 << 0)); // leave filter init mode
    }

    /// Transmit via mailbox 0 only (simplest correct behavior for this bus's
    /// traffic pattern - low rate, no need for the other two mailboxes).
    /// Returns `CanError::TxBusy` if mailbox 0 already has a pending frame;
    /// caller decides whether/how to retry.
    pub fn transmit(&mut self, frame: &CanFrame) -> Result<(), CanError> {
        unsafe {
            let tsr = (self.base + 0x008) as *const u32;
            if (tsr.read_volatile() & (1 << 26)) == 0 {
                // TME0 clear: mailbox 0 not empty.
                return Err(CanError::TxBusy);
            }

            let tir = (self.base + 0x180) as *mut u32;
            let tdtr = (self.base + 0x184) as *mut u32;
            let tdlr = (self.base + 0x188) as *mut u32;
            let tdhr = (self.base + 0x18C) as *mut u32;

            let dlc = frame.dlc.min(8) as u32;
            tdtr.write_volatile(dlc);

            let d = &frame.data;
            let low = u32::from_le_bytes([d[0], d[1], d[2], d[3]]);
            let high = u32::from_le_bytes([d[4], d[5], d[6], d[7]]);
            tdlr.write_volatile(low);
            tdhr.write_volatile(high);

            // STID in bits [31:21], IDE=0 (standard), RTR=0 (data frame).
            let tir_val = ((frame.id as u32 & 0x7FF) << 21) | (1 << 0); // | TXRQ
            tir.write_volatile(tir_val);
        }
        Ok(())
    }

    /// Pop one frame from FIFO0, if any is pending.
    pub fn receive(&mut self) -> Option<CanFrame> {
        unsafe {
            let rf0r = (self.base + 0x00C) as *mut u32;
            if (rf0r.read_volatile() & 0x3) == 0 {
                return None; // FMP0 == 0: nothing pending
            }

            let rir = (self.base + 0x1B0) as *const u32;
            let rdtr = (self.base + 0x1B4) as *const u32;
            let rdlr = (self.base + 0x1B8) as *const u32;
            let rdhr = (self.base + 0x1BC) as *const u32;

            let id = ((rir.read_volatile() >> 21) & 0x7FF) as u16;
            let dlc = (rdtr.read_volatile() & 0xF) as u8;
            let low = rdlr.read_volatile().to_le_bytes();
            let high = rdhr.read_volatile().to_le_bytes();
            let mut data = [0u8; 8];
            data[..4].copy_from_slice(&low);
            data[4..].copy_from_slice(&high);

            // Release the FIFO0 output mailbox (RFOM0) so the next frame can arrive.
            rf0r.write_volatile(rf0r.read_volatile() | (1 << 5));

            Some(CanFrame { id, dlc, data })
        }
    }
}
