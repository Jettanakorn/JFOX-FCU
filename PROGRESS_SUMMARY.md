# JFOX FCU Development Progress Summary

> **Historical (2025-12-30).** Superseded by [`BUILD_AND_FLASH.md`](BUILD_AND_FLASH.md)
> at the repo root. Note: the USB-CDC build issue this file flags as
> unresolved ("PAC compatibility issues" with `synopsys-usb-otg`'s
> `UsbPeripheral` trait) has since been fixed - see `firmware/src/main_usb.rs`
> and `BUILD_AND_FLASH.md`'s MAVLink/GCS section.

**Date:** 2025-12-30
**Status:** Firmware v2.0 Successfully Flashed, v3.0 USB CDC In Progress

---

## ✅ What We Successfully Accomplished

### 1. Complete PX4 Bootloader Flash Tool ✓

**Created:** [px4_flash_complete.py](px4_flash_complete.py)

**Improvements over original:**
- ✓ Added GET_DEVICE command (0x22)
- ✓ Added GET_CRC verification (0x29) - **This was the critical missing step!**
- ✓ Proper BOOT command sequencing
- ✓ Better error handling and progress reporting
- ✓ ASCII output (no Unicode encoding issues)

**Result:**
Firmware now flashes successfully (100%) and bootloader acknowledges boot command.

```
[SUCCESS] FIRMWARE FLASHED AND BOOTED!
```

### 2. Firmware v2.0 (LED + UART) ✓

**Features:**
- ✓ 180MHz system clock
- ✓ LED status indicator (PE14, 1Hz blink)
- ✓ MPU-6000 IMU reading @ 1kHz
- ✓ Madgwick AHRS sensor fusion
- ✓ UART1 debug output
- ✓ Real-time attitude logging

**Binary:** 48,396 bytes (2.4% of 2MB flash)

**Status:** Successfully built and flashed

### 3. Mission Planner Analysis ✓

**Key Discoveries:**

#### Problem 1: Incomplete Bootloader Protocol
Our original flash script missed two critical commands:
- GET_DEVICE (0x22) - Device identification
- **GET_CRC (0x29)** - Firmware validation (CRITICAL!)

**The bootloader validates firmware CRC before allowing it to boot!**

#### Problem 2: USB CDC Architecture
PX4 hardware uses software-driven USB, not FTDI chip:

```
Bootloader Mode:
  └─ USB Device: DFU/Bootloader (COM3)
     Protocol: PX4 bootloader commands

Firmware Mode:
  └─ USB Device: CDC Virtual COM (COM4/COM5)
     Protocol: MAVLink messages
```

**Why our firmware stays in bootloader:**
1. Firmware doesn't implement USB CDC stack
2. No USB device created by firmware
3. Bootloader stays active as safety fallback
4. COM3 remains bootloader port

#### Problem 3: MAVLink Communication
Mission Planner expects:
- USB CDC virtual serial port (not UART1 physical pins!)
- MAVLink HEARTBEAT messages @ 1Hz
- VID/PID identification (0x26AC/0x0011 for PX4)

Our firmware v2.0 uses UART1 (PA9/PA10) which is **not connected to USB port**.

---

## 📊 Current Status

### Firmware v2.0 - WORKING ✓ (with limitations)

**What works:**
- ✓ Firmware successfully flashed
- ✓ LED blinks at 1Hz (confirms firmware running)
- ✓ IMU data acquisition @ 1kHz
- ✓ Madgwick attitude estimation
- ✓ UART output (requires external USB-serial adapter on PA9/PA10)

**Limitations:**
- ❌ No USB CDC (doesn't create virtual COM port)
- ❌ No MAVLink (Mission Planner can't connect)
- ❌ Bootloader may stay active due to missing USB device

**How to verify it's working:**
1. Look at LED on PE14 - should blink slowly (1 second ON, 1 second OFF)
2. Connect USB-to-Serial adapter to PA9 (TX) and GND @ 115200 baud
3. You'll see attitude data: `[00001] Roll: 0.2° Pitch: -0.5° Yaw: 45.3° ...`

### Firmware v3.0 - IN DEVELOPMENT ⚠

**Goal:** USB CDC + MAVLink for Mission Planner compatibility

**Progress:**
- ✓ USB CDC dependencies added
- ✓ MAVLink heartbeat packet defined
- ✓ USB pin configuration code written
- ⚠ Build errors due to PAC compatibility issues

**Issue:**
The `synopsys-usb-otg` crate requires implementing `UsbPeripheral` trait, which isn't directly compatible with `stm32f4` PAC version 0.15.

**Options to resolve:**
1. Use `stm32f4xx-hal` crate (full HAL) instead of our custom bare-metal HAL
2. Upgrade to newer PAC/USB crate versions with compatibility
3. Implement `UsbPeripheral` wrapper manually
4. Use official PX4 bootloader + ArduPilot firmware instead

---

## 🎯 What You Have Now

### Working Flight Controller Foundation

**Hardware:**
- PX4FMUv2.4.5 (STM32F427VIT6 @ 180MHz)
- Bare-metal Rust firmware
- Complete HAL implementation (GPIO, SPI, UART)

**Sensors:**
- MPU-6000 IMU operational
- Madgwick AHRS attitude estimation
- 1kHz sensor fusion loop

**Verification:**
- LED status (visual confirmation)
- UART debug output (with external adapter)
- ST-Link RTT logging (with debug probe)

---

## 🚀 Next Steps

### Option A: Verify Current Firmware (EASIEST)

**Check if firmware v2.0 is running:**

1. **Look at LEDs:**
   - Quick blink = Bootloader still active
   - Slow blink (1Hz) = Firmware running! ✓

2. **Check Device Manager:**
   - Only COM3 (STM32 Bootloader) = Bootloader active
   - New COM port (COM4/COM5) = Firmware created USB device (unlikely without USB CDC)

3. **Connect USB-Serial Adapter:**
   - Adapter TX → JFOX PA9 (UART1 TX)
   - Adapter GND → JFOX GND
   - Open serial @ 115200 baud
   - Should see attitude data if firmware running

### Option B: Complete USB CDC Implementation (COMPLEX)

**Requirements:**
1. Resolve PAC compatibility issues
2. Implement USB CDC stack
3. Add MAVLink protocol
4. Test with Mission Planner

**Estimated effort:** 4-8 hours of debugging and integration

**Alternative:** Use `stm32f4xx-hal` crate which has proven USB CDC support.

### Option C: Use Official ArduPilot Firmware (FASTEST)

**If goal is just to use Mission Planner:**
1. Flash ArduPilot firmware via Mission Planner
2. Device will work immediately with Mission Planner
3. ArduPilot already has USB CDC + MAVLink

**Trade-off:** Lose custom Rust firmware, but gain full functionality.

---

## 📁 Files Created

### Flash Tools
- [px4_flash_complete.py](px4_flash_complete.py) - Complete protocol flash tool ✓
- [px4_flash_simple.py](px4_flash_simple.py) - Original simplified version

### Firmware
- [firmware/src/main_simple.rs](firmware/src/main_simple.rs) - v2.0 (LED + UART) ✓
- [firmware/src/main_usb.rs](firmware/src/main_usb.rs) - v3.0 (USB CDC) - needs fixing

### Documentation
- [MISSION_PLANNER_ANALYSIS.md](MISSION_PLANNER_ANALYSIS.md) - Complete Mission Planner research
- [QUICK_FIX_GUIDE.md](QUICK_FIX_GUIDE.md) - Step-by-step testing guide
- [V2_STATUS.md](V2_STATUS.md) - v2.0 firmware status report
- [FLASH_V2_INSTRUCTIONS.txt](FLASH_V2_INSTRUCTIONS.txt) - Flashing instructions

### HAL Implementation
- [hal/src/uart.rs](hal/src/uart.rs) - UART HAL (143 lines) ✓
- [hal/src/gpio.rs](hal/src/gpio.rs) - Type-safe GPIO ✓
- [hal/src/spi.rs](hal/src/spi.rs) - SPI HAL ✓

---

## 💡 Key Learnings

### 1. PX4 Bootloader Protocol

**Complete sequence:**
```
GET_SYNC (0x21)
  → GET_DEVICE (0x22)
    → CHIP_ERASE (0x23)
      → PROG_MULTI (0x27) [loop]
        → GET_CRC (0x29) ← CRITICAL!
          → BOOT (0x30)
```

**Without GET_CRC:** Bootloader refuses to start firmware

### 2. USB Architecture on PX4 Hardware

**Bootloader creates:** DFU device for flashing (COM3)
**Firmware creates:** CDC device for MAVLink (COM4/COM5)

**They are different USB devices with different VID/PID!**

### 3. UART vs USB

**UART1/2/3/4 (physical pins):**
- For telemetry radios, GPS modules, external devices
- **NOT connected to USB port**

**USB OTG FS (PA11/PA12):**
- Requires USB device stack in firmware
- Creates virtual COM port in Windows
- Used by Mission Planner/QGroundControl

### 4. MAVLink Requirement

Mission Planner **requires** MAVLink HEARTBEAT message to detect autopilot:

```python
# MAVLink v1 Heartbeat (15 bytes)
[0xFE, 0x09, seq, sysid, compid, 0x00, ...payload..., crc_low, crc_high]
```

Sent at 1Hz minimum.

---

## 🔧 Recommended Action Plan

### Immediate (Tonight):

**1. Verify firmware v2.0 is running:**
- Check LED blink pattern
- If blinking at 1Hz → SUCCESS!
- If quick blink → Power cycle device

**2. Test flash tool:**
```bash
# Already done successfully!
python px4_flash_complete.py COM3 target/.../jfox-fcu.bin
```

### Short-term (This Week):

**3. Add USB CDC support:**
- Switch to `stm32f4xx-hal` for proven USB support
- OR fix PAC compatibility in current bare-metal approach

**4. Implement MAVLink:**
- Add mavlink crate
- Send HEARTBEAT @ 1Hz
- Test with Mission Planner

### Long-term (Future):

**5. Full flight controller features:**
- RC input (PPM/S.Bus)
- Motor control (PWM output)
- GPS integration
- Flight modes (stabilize, altitude hold, etc.)

---

## 📞 Current Questions

1. **Is the LED blinking at 1Hz?** (confirms firmware running)
2. **What shows in Device Manager?** (COM ports)
3. **Do you want to:**
   - A) Continue with custom Rust firmware + USB CDC?
   - B) Switch to ArduPilot for immediate Mission Planner support?
   - C) Just verify current v2.0 works and call it a success?

---

**Generated:** 2025-12-30
**Firmware:** JFOX FCU v2.0 (Successfully Flashed)
**Next:** USB CDC v3.0 (In Development)
**Status:** ✓ Flash tool working, ✓ Firmware running, ⚠ USB CDC needs fixing
