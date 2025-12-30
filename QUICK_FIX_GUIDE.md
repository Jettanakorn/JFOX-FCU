# Quick Fix Guide - Mission Planner Compatible Firmware

**What I learned from Mission Planner:** Your firmware needs USB CDC + MAVLink!

---

## 🔧 IMMEDIATE FIX: Test Improved Flash Script

### Step 1: Try the Complete Protocol Flash Tool

```bash
# Enter bootloader mode (hold BOOT0, connect USB, release)

# Flash with COMPLETE protocol (includes CRC validation)
python px4_flash_complete.py COM3 target/thumbv7em-none-eabihf/release/jfox-fcu.bin
```

**What's different:**
- ✓ Adds GET_DEVICE command (0x22)
- ✓ Adds GET_CRC verification (0x29) ← **This is critical!**
- ✓ Proper BOOT sequence

**If this works, the device should:**
1. Flash successfully (100%)
2. CRC verification passes ✓
3. Boot into firmware
4. LED pattern changes from "quick blink" to "slow blink" (1Hz)

**If it STILL stays in bootloader:**
→ The firmware needs USB CDC implementation (see below)

---

## 🎯 ROOT CAUSE: Missing USB CDC + MAVLink

**Why Mission Planner works and our method doesn't:**

Mission Planner expects:
1. **USB CDC device** - Virtual COM port created by firmware
2. **MAVLink protocol** - Heartbeat messages at 1Hz
3. **Different COM port** - Firmware creates COM4/COM5, not COM3

Our firmware currently:
- ❌ Uses UART1 (physical pins PA9/PA10) - not connected to USB!
- ❌ Outputs raw text - not MAVLink messages
- ❌ No USB stack - bootloader stays active

**This is why:**
- COM3 = Bootloader only
- Firmware never takes over USB
- Mission Planner can't see the device

---

## 🚀 SOLUTION: Add USB CDC to Firmware

I'll create a minimal USB CDC firmware that works with Mission Planner.

### What needs to be implemented:

1. **USB Device Stack**
   - USB OTG FS peripheral (PA11/PA12)
   - CDC-ACM class (virtual serial port)
   - Proper VID/PID (0x26AC/0x0011 for PX4)

2. **MAVLink Heartbeat**
   - Send HEARTBEAT message @ 1Hz
   - Mission Planner detects this and connects

3. **Replace UART with USB**
   - Remove UART1 debug output
   - Send all output via USB CDC
   - Creates new COM port (COM4/COM5)

---

## 📋 Next Steps

### Option A: Test Current Firmware with Improved Flash Script

**Do this first!** The CRC validation might be all we need:

```bash
python px4_flash_complete.py COM3 target/thumbv7em-none-eabihf/release/jfox-fcu.bin
```

**Watch for:**
- "✓ CRC verification passed!"
- "✓ FIRMWARE FLASHED AND BOOTED SUCCESSFULLY!"
- LED changes from quick blink → slow blink

### Option B: Build USB CDC Firmware (if Option A fails)

I can create a new firmware version with:
- USB CDC virtual serial port
- MAVLink heartbeat messages
- Mission Planner compatible

**This will:**
- Exit bootloader properly
- Create new COM port (not COM3!)
- Work with Mission Planner
- Show as "JFOX FCU" in device list

---

## 🔍 How to Verify Success

### After Flashing:

**1. Check LED Status**
- ❌ Red LED quick blink = Still in bootloader
- ✓ LED slow blink (1Hz) = Firmware running!

**2. Check USB Device**

In Windows Device Manager:
```
Bootloader Mode:
  └─ Ports (COM & LPT)
      └─ STM32 Bootloader (COM3)

Firmware Running:
  └─ Ports (COM & LPT)
      └─ JFOX FCU (COM4)  ← NEW PORT!
```

**3. Check Serial Output**

Without USB CDC (current firmware):
- Connect USB-to-Serial adapter to PA9 (TX) + GND
- Open COM port of adapter @ 115200 baud
- Should see attitude data

With USB CDC (new firmware):
- Device appears as new COM port (COM4/COM5)
- Open that port @ 115200 baud
- Should see MAVLink messages or debug text

**4. Test with Mission Planner**

1. Open Mission Planner
2. Select correct COM port (COM4/COM5, not COM3!)
3. Set baud rate: 115200
4. Click "Connect"
5. Should see MAVLink heartbeat
6. Status shows "CONNECTED"

---

## 📊 Comparison

| Feature | Current Firmware | USB CDC Firmware |
|---------|-----------------|------------------|
| **Flash Tool** | px4_flash_simple.py | px4_flash_complete.py ✓ |
| **CRC Check** | ❌ Missing | ✓ Added |
| **Boot Method** | REBOOT command | BOOT command ✓ |
| **Output** | UART1 (PA9/PA10) | USB CDC ✓ |
| **COM Port** | None (bootloader COM3) | New port (COM4/COM5) ✓ |
| **Protocol** | Raw text | MAVLink ✓ |
| **Mission Planner** | ❌ Can't connect | ✓ Works |
| **LED Verify** | ✓ 1Hz blink | ✓ 1Hz blink |

---

## 💡 What We Learned from Mission Planner

From analyzing Mission Planner and PX4 documentation:

1. **Bootloader Protocol:**
   - Must include GET_CRC (0x29) before BOOT (0x30)
   - CRC validation is REQUIRED for firmware to start
   - Missing this = stuck in bootloader

2. **USB Architecture:**
   - Bootloader creates DFU device (COM3)
   - Firmware creates CDC device (COM4/COM5)
   - They are DIFFERENT USB devices!
   - COM3 is bootloader-only, firmware never uses it

3. **Communication:**
   - Mission Planner uses MAVLink over USB serial
   - UART pins (PA9/PA10) are for telemetry radios, not USB
   - Physical UARTs are NOT connected to USB port

4. **Detection:**
   - Mission Planner listens for MAVLink HEARTBEAT
   - Sent at 1Hz by firmware
   - No heartbeat = no connection

---

## 🎬 Ready to Test?

**Step 1:** Try improved flash script
```bash
python px4_flash_complete.py COM3 jfox-fcu.bin
```

**Step 2:** Check if LED pattern changes

**Step 3:** If still stuck, I'll create USB CDC firmware

**Step 4:** Flash USB CDC firmware and test with Mission Planner

---

**Questions?**
- Need USB CDC firmware? Let me know!
- Flash script not working? Share the output
- Device still in bootloader? We'll implement USB next
