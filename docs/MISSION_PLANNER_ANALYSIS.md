# Mission Planner Analysis - What We Learned

**Date:** 2025-12-30
**Issue:** Firmware flashes successfully but device stays in bootloader mode
**User Request:** "use mission planner it can do it. please learning from the mission planner app"

---

## What I Discovered

### 1. Incomplete Bootloader Protocol ❌

**Our original flash script was missing critical commands!**

#### PX4 Bootloader Protocol (Complete Sequence)

According to [PX4-Bootloader source code](https://github.com/PX4/PX4-Bootloader/blob/main/bl.c):

| Step | Command | Opcode | Purpose | Our Script |
|------|---------|--------|---------|------------|
| 1 | GET_SYNC | 0x21 | Verify board present | ✓ Had it |
| 2 | GET_DEVICE | 0x22 | Get device ID | ❌ **MISSING** |
| 3 | CHIP_ERASE | 0x23 | Erase flash | ✓ Had it |
| 4 | PROG_MULTI | 0x27 | Program data (loop) | ✓ Had it |
| 5 | **GET_CRC** | **0x29** | **Verify firmware CRC** | ❌ **MISSING** |
| 6 | BOOT | 0x30 | Start application | ✓ Had it (but called it "REBOOT") |

**The Critical Missing Step: GET_CRC (0x29)**

> The bootloader validates the flashed firmware CRC **before allowing it to boot**!

Without CRC verification, the bootloader may:
- Refuse to start the application
- Stay in bootloader mode as a safety measure
- Wait for a valid firmware to be flashed

**Protocol Response Bytes:**
- `PROTO_INSYNC = 0x12` - "in sync" acknowledgment
- `PROTO_OK = 0x10` - Success
- `PROTO_FAILED = 0x11` - Failure
- `PROTO_INVALID = 0x13` - Invalid command
- `PROTO_EOC = 0x20` - End of command

---

### 2. USB Communication Architecture 🔌

**This is the KEY difference between our firmware and what Mission Planner expects!**

From [ArduPilot forums](https://discuss.ardupilot.org/t/apm-copter-3-0-1-cannot-connect-px4fmu-to-mission-planner/223):

> "The Px4 usb is software driven not a ftdi chip like the APM. When the STM32 bootloader starts it creates a USB port with its own Id and sets up a **DFU device for loading**. If no bootloader request is received it jumps to the code startup and creates a **usb serial port with a different USB Id for a mavlink connection**."

**What this means:**

#### PX4 Hardware USB Behavior

```
┌─────────────────────────────────────────────────────┐
│ POWER ON / USB CONNECT                              │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │  Bootloader Activated  │
         │  (first few seconds)   │
         └────────────────────────┘
                      │
         Creates USB Device:
         VID/PID: Bootloader ID
         Function: DFU/Bootloader Protocol
         Port: COM3 (bootloader commands)
                      │
                      ▼
         ┌────────────────────────┐
         │  Check for bootloader  │
         │  commands (timeout)    │
         └────────────────────────┘
                      │
              No commands received
                      │
                      ▼
         ┌────────────────────────┐
         │   Jump to Firmware     │
         └────────────────────────┘
                      │
         Creates DIFFERENT USB Device:
         VID/PID: Application ID
         Function: CDC Serial (Virtual COM Port)
         Port: COM4/COM5 (new port!)
         Protocol: MAVLink
                      │
                      ▼
         ┌────────────────────────┐
         │ Firmware Running       │
         │ MAVLink Heartbeat      │
         │ Mission Planner Ready  │
         └────────────────────────┘
```

#### COM Port Mapping

**Bootloader Mode:**
- **COM3**: PX4 Bootloader (DFU/flash protocol)
- Purpose: Firmware upload only
- Protocol: PX4 bootloader commands (0x21, 0x23, 0x27, 0x29, 0x30)

**Application Mode (Firmware Running):**
- **COM4/COM5** (NEW PORT!): USB CDC Virtual Serial Port
- Purpose: MAVLink communication
- Protocol: MAVLink messages
- Used by: Mission Planner, QGroundControl

---

### 3. Why Our Firmware Doesn't Work with Mission Planner ❌

**Our current firmware ([main_simple.rs](../firmware/src/main_simple.rs)):**

```rust
// Initialize UART1 for debug output (TX=PA9, RX=PA10)
let mut uart = unsafe { Uart::<1>::new() };
uart.init(115200);
uart.write_str("JFOX FCU v2.0 - Rust Flight Controller\r\n");
```

**Problems:**

1. ❌ **No USB CDC implementation** - firmware doesn't create virtual serial port
2. ❌ **No MAVLink protocol** - outputs raw text, not MAVLink messages
3. ❌ **UART1 on physical pins** (PA9/PA10) - not connected to USB!
4. ❌ **No USB device registration** - bootloader stays active as fallback

**What happens:**
```
User connects USB → Bootloader starts → Waits for firmware
→ Firmware boots BUT doesn't take over USB
→ Bootloader sees no USB device from firmware
→ Bootloader stays active for safety
→ COM3 stays as bootloader port
→ User sees "quick blink" LED (bootloader pattern)
```

---

## What Mission Planner Expects

### 1. USB CDC Virtual Serial Port

The firmware must implement **USB Device CDC (Communication Device Class)** to create a virtual COM port.

**Required:**
- USB device stack (usb-device crate for Rust)
- CDC-ACM class implementation
- Proper USB descriptors (VID/PID, manufacturer, product)
- Endpoint configuration (control + data IN/OUT)

### 2. MAVLink Protocol

Mission Planner communicates via **MAVLink messages**, not raw UART text.

**MAVLink Heartbeat (Required for Detection):**

```rust
// MAVLink v1 Heartbeat message (1Hz)
struct Heartbeat {
    msg_id: 0,              // HEARTBEAT
    type: 6,                // MAV_TYPE_GENERIC
    autopilot: 0,           // MAV_AUTOPILOT_GENERIC
    base_mode: 0,           // No flags
    custom_mode: 0,
    system_status: 4,       // MAV_STATE_ACTIVE
    mavlink_version: 3,
}
```

Mission Planner listens for this heartbeat to detect the autopilot.

### 3. Proper Boot Sequence

After flash:
1. Bootloader validates CRC ✓
2. Bootloader sends BOOT command ✓
3. **Firmware takes over USB peripheral** ❌ (we're missing this!)
4. **Firmware creates new USB CDC device** ❌ (we're missing this!)
5. **Windows detects new COM port** ❌ (never happens)
6. **Firmware sends MAVLink heartbeat** ❌ (we're missing this!)
7. Mission Planner sees heartbeat and connects ✓

---

## Solutions

### Solution 1: Fix Flash Script ✓ DONE

**Created:** [px4_flash_complete.py](../px4_flash_complete.py)

**Changes:**
- ✓ Added GET_DEVICE (0x22) command
- ✓ Added GET_CRC (0x29) verification
- ✓ Improved error handling
- ✓ Better progress reporting
- ✓ Proper BOOT command sequencing

**This should fix the "won't exit bootloader" issue.**

---

### Solution 2: Add USB CDC to Firmware (NEEDED)

**Implementation required:**

#### Add Dependencies

```toml
[dependencies]
usb-device = "0.3"
usbd-serial = "0.2"
stm32f4xx-hal = { version = "0.21", features = ["usb_fs"] }
```

#### USB Initialization

```rust
// In main_simple.rs
use usb_device::prelude::*;
use usbd_serial::{SerialPort, USB_CLASS_CDC};

// Get USB peripheral
let usb = hal::otg_fs::USB {
    usb_global: peripherals.OTG_FS_GLOBAL,
    usb_device: peripherals.OTG_FS_DEVICE,
    usb_pwrclk: peripherals.OTG_FS_PWRCLK,
    pin_dm: gpioa.pa11,
    pin_dp: gpioa.pa12,
    hclk: clocks.hclk(),
};

let usb_bus = UsbBus::new(usb, &mut USB_MEMORY);

let mut serial = SerialPort::new(&usb_bus);

let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x26AC, 0x0011))
    .manufacturer("JFOX")
    .product("FCU v2.0")
    .serial_number("001")
    .device_class(USB_CLASS_CDC)
    .build();

// In main loop
usb_dev.poll(&mut [&mut serial]);
if serial.read(&mut buf) {
    // Handle MAVLink input
}
serial.write(mavlink_heartbeat_bytes);
```

---

### Solution 3: Add MAVLink Protocol (NEEDED)

**Implementation required:**

#### Add Dependency

```toml
[dependencies]
mavlink = { version = "0.13", default-features = false }
```

#### MAVLink Heartbeat

```rust
use mavlink::common::MavMessage;

// Send heartbeat @ 1Hz
let heartbeat = mavlink::common::HEARTBEAT_DATA {
    custom_mode: 0,
    mavtype: mavlink::common::MavType::MAV_TYPE_GENERIC,
    autopilot: mavlink::common::MavAutopilot::MAV_AUTOPILOT_GENERIC,
    base_mode: mavlink::common::MavModeFlag::empty(),
    system_status: mavlink::common::MavState::MAV_STATE_ACTIVE,
    mavlink_version: 3,
};

let msg = MavMessage::HEARTBEAT(heartbeat);
// Serialize and send via USB CDC
```

---

## What to Do Next

### Immediate: Test Improved Flash Script

```bash
# Enter bootloader mode (BOOT0 button)
python px4_flash_complete.py COM3 target/thumbv7em-none-eabihf/release/jfox-fcu.bin
```

**Expected outcome:**
- All 6 steps complete successfully
- CRC verification passes
- Firmware boots
- Device may still stay in bootloader (USB issue)

### Short-term: Minimal USB CDC Firmware

Create a minimal firmware that:
1. Initializes USB CDC
2. Sends "Hello from JFOX FCU" on USB serial
3. No MAVLink yet - just prove USB works

**This will:**
- Exit bootloader (firmware takes over USB)
- Create new COM port (COM4/COM5)
- Allow serial terminal connection
- Prove USB stack works

### Long-term: Full MAVLink Firmware

Add:
1. Complete MAVLink message handling
2. Heartbeat, system status, attitude, GPS, RC input
3. Parameter system
4. Mission Planner/QGroundControl compatibility

---

## References

**Documentation:**
- [PX4 Bootloader Update Guide](https://docs.px4.io/main/en/advanced_config/bootloader_update)
- [Loading Firmware onto Pixhawk](https://ardupilot.org/planner/docs/common-loading-firmware-onto-pixhawk.html)
- [Mission Planner Connection Guide](https://ardupilot.org/planner/docs/common-connect-mission-planner-autopilot.html)

**Source Code:**
- [PX4-Bootloader/bl.c](https://github.com/PX4/PX4-Bootloader/blob/main/bl.c) - Protocol implementation
- [ArduPilot Bootloader Protocol](https://github.com/ArduPilot/ardupilot/blob/master/Tools/AP_Bootloader/bl_protocol.cpp)

**Forum Discussions:**
- [Mission Planner with PX4 firmware](https://discuss.px4.io/t/mission-planner-with-px4-firmware/30132)
- [Cannot connect PX4FMU to Mission Planner](https://discuss.ardupilot.org/t/apm-copter-3-0-1-cannot-connect-px4fmu-to-mission-planner/223)

---

## Summary

**The ROOT CAUSE of "firmware won't boot":**

1. ❌ **Incomplete flash protocol** - Missing GET_CRC validation step
2. ❌ **No USB CDC implementation** - Firmware doesn't create virtual COM port
3. ❌ **Bootloader stays active** - No USB device from firmware = safety fallback

**The ROOT CAUSE of "Mission Planner can't connect":**

1. ❌ **Wrong COM port** - COM3 is bootloader, firmware needs COM4/COM5
2. ❌ **No MAVLink heartbeat** - Mission Planner requires MAVLink messages
3. ❌ **UART vs USB** - Our firmware uses UART1 pins, not USB

**What Mission Planner does differently:**

1. ✓ Uses complete bootloader protocol (GET_SYNC → GET_DEVICE → CHIP_ERASE → PROG_MULTI → GET_CRC → BOOT)
2. ✓ Expects firmware with USB CDC stack
3. ✓ Communicates via MAVLink over USB serial
4. ✓ Detects new COM port after firmware boots
5. ✓ Listens for MAVLink heartbeat messages

---

**Next Action:** Test the improved flash script, then implement USB CDC + MAVLink!
