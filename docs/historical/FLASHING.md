# JFOX FCU Firmware Flashing Guide

> **Historical (2025-12-30).** Superseded by [`BUILD_AND_FLASH.md`](../../BUILD_AND_FLASH.md)
> at the repo root for current build/flash instructions. Kept for its
> protocol reverse-engineering detail.

## Current Status

✅ **Firmware Built Successfully**
- Binary location: `target/thumbv7em-none-eabihf/release/jfox-fcu.bin`
- Size: 16,732 bytes (17 KB)
- ELF file: `target/thumbv7em-none-eabihf/release/jfox-fcu`

✅ **Tools Installed**
- probe-rs v0.30.0 (for SWD/JTAG flashing)
- PX4 bootloader upload script ([px4_upload.py](px4_upload.py))
- cargo-binutils (for binary conversion)

✅ **Hardware Detected**
- Device: USB Serial Device (COM3)
- VID:PID: 26AC:0011 (3D Robotics)
- Status: Device is running existing firmware

## Flashing Methods

### Method 1: SWD Debug Probe (Recommended for Development)

**Hardware Required:**
- ST-Link V2, J-Link, or compatible debug probe
- Connection to SWD pins on JFOX FCU

**Pin Connections:**
Based on [pins.rs](bsp/src/pins.rs:159-162):
- SWDIO → PA13
- SWCLK → PA14
- GND → GND
- VCC → 3.3V (optional, if powering from probe)

**Flashing Command:**
```bash
cd firmware
cargo flash --chip STM32F427VITx --release
```

**Advantages:**
- Fast flashing
- Supports debugging with breakpoints
- Can read/write memory
- No need to enter bootloader mode

---

### Method 2: PX4 Bootloader via USB Serial (Current Attempt)

**Current Issue:**
The device is detected on COM3 but is running existing firmware that sends telemetry data. It's not responding to bootloader commands.

**Solution - Enter Bootloader Mode:**

1. **Locate BOOT0 Pin** on the JFOX FCU board
   - May be labeled as "BOOT0", "BL", or "BOOTLOADER"
   - Might be a button, jumper, or test pad

2. **Enter Bootloader Mode:**
   ```
   a. Power off the board (disconnect USB)
   b. Set BOOT0 to HIGH (3.3V):
      - If button: Hold the boot button
      - If jumper: Install jumper to 3.3V position
      - If test pad: Connect to 3.3V with wire
   c. Power on the board (connect USB) while holding BOOT0 HIGH
   d. Release BOOT0 after ~1 second
   ```

3. **Verify Bootloader Mode:**
   ```bash
   probe-rs list
   # OR check if COM3 device changes
   ```

4. **Flash Firmware:**
   ```bash
   python px4_upload.py COM3 target/thumbv7em-none-eabihf/release/jfox-fcu.bin
   ```

**Expected Output:**
```
Opening port COM3 at 115200 baud...
Sync attempt 1...
Bootloader synced!
Getting device info...
Device ID: 0x04190415 (or similar)
Erasing flash...
Flash erased
Programming 16732 bytes...
Progress: 100%
Programming complete
Rebooting...
✓ Upload successful!
```

---

### Method 3: DFU Mode via USB (Alternative)

**Requirements:**
- Device must support USB DFU mode
- BOOT0 set HIGH during reset
- dfu-util tool installed

**Steps:**
1. Enter DFU mode (same as bootloader above)
2. Verify DFU device:
   ```bash
   dfu-util --list
   ```
3. Flash firmware:
   ```bash
   dfu-util -a 0 -D target/thumbv7em-none-eabihf/release/jfox-fcu.bin -s 0x08000000
   ```

---

## Troubleshooting

### COM3 Sends Random Data
**Symptom:** Device responds but sends binary data instead of bootloader protocol
**Cause:** Existing firmware is running
**Solution:** Enter bootloader mode (Method 2, step 2)

### No Debug Probe Found
**Symptom:** `probe-rs list` shows no probes
**Cause:** No SWD/JTAG adapter connected
**Solution:** Use Method 2 (USB Serial) or connect ST-Link

### Bootloader Not Syncing
**Symptom:** `Failed to sync with bootloader` after 10 attempts
**Causes:**
1. Wrong baud rate → Try 57600, 115200
2. Not in bootloader mode → Check BOOT0 pin
3. Wrong protocol → Device may not have PX4 bootloader

**Debug Steps:**
```bash
# Test all baud rates
python -c "
import serial
for baud in [115200, 57600, 38400, 9600]:
    ser = serial.Serial('COM3', baud, timeout=0.5)
    ser.write(b'\x21\x20')
    resp = ser.read(10)
    print(f'{baud}: {resp.hex()}')
    ser.close()
"
```

### Permission Denied on COM3
**Symptom:** `PermissionError: [Errno 13] Permission denied: 'COM3'`
**Cause:** Another program is using the port
**Solution:**
```bash
# Close QGroundControl, Mission Planner, or other serial terminals
# Check with Task Manager → Details tab
```

---

## Firmware Details

**Target MCU:** STM32F427VIT6
- Flash: 2MB (0x08000000 - 0x081FFFFF)
- RAM: 192KB (0x20000000 - 0x2002FFFF)
- Architecture: ARM Cortex-M4F @ 180MHz

**Firmware Features:**
- Bare-metal Rust (no_std)
- MPU-6000 IMU driver @ 1kHz
- Madgwick sensor fusion
- Direct register access HAL
- defmt logging via RTT

**Build Configuration:**
- Target: thumbv7em-none-eabihf
- Optimization: release (--release)
- Linker script: [memory.x](../../memory.x)

---

## Next Steps

1. **Determine Available Hardware:**
   - [ ] Check if you have an ST-Link or J-Link probe
   - [ ] Locate BOOT0 pin/button on JFOX FCU board
   - [ ] Check board documentation for bootloader entry method

2. **Choose Flashing Method:**
   - If ST-Link available → Use Method 1 (SWD)
   - If BOOT0 accessible → Use Method 2 (USB Serial)
   - If USB DFU supported → Use Method 3 (DFU)

3. **Flash and Verify:**
   - Follow chosen method above
   - Connect defmt-rtt to view logs:
     ```bash
     probe-rs run --chip STM32F427VITx target/thumbv7em-none-eabihf/release/jfox-fcu
     ```
   - Verify IMU initialization and attitude output

---

## Additional Resources

- **PX4 Bootloader Protocol:** https://github.com/PX4/Bootloader
- **STM32F427 Datasheet:** https://www.st.com/resource/en/reference_manual/dm00031020.pdf
- **probe-rs Documentation:** https://probe.rs/
- **defmt Book:** https://defmt.ferrous-systems.com/

---

**Generated:** 2025-12-30
**Firmware Version:** jfox-fcu (bare-metal Rust)
**Hardware:** PX4FMUv2.4.5 (STM32F427VIT6)
