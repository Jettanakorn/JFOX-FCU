# Building and flashing JFOX-FCU

The single authoritative source for how to build each firmware binary and
get it onto real PX4FMUv2.4.5 hardware. Supersedes the scattered, partly
outdated 2025-12-30 documents at the repo root (`docs/historical/FLASHING.md`,
`docs/historical/VERIFICATION_STATUS.md`, `docs/historical/V2_STATUS.md`, `docs/historical/PROGRESS_SUMMARY.md`,
`docs/historical/QUICK_FIX_GUIDE.md`, `docs/historical/BUILD_AND_FLASH_SUCCESS.md`,
`docs/historical/FLASH_INSTRUCTIONS.txt`, `docs/historical/FLASH_V2_INSTRUCTIONS.txt`) - those are kept for
their protocol reverse-engineering detail (especially
`docs/MISSION_PLANNER_ANALYSIS.md`, left as reference material, not a status doc)
but are no longer the current build/flash instructions.

## The four firmware binaries

`firmware/Cargo.toml` defines four `[[bin]]` targets. Building without
`--bin` builds all of them:

```bash
cd firmware
cargo build --release            # all four
cargo build --release --bin jfox-fcu-flight   # just one
```

| Binary | Source | What it is |
|---|---|---|
| `jfox-fcu` | `src/main_simple.rs` | No-RTIC bring-up build: IMU read + Madgwick fusion + LED/UART debug output. Simplest thing that proves the board boots and the IMU works. |
| `jfox-fcu-flight` | `src/main.rs` | The real flight application - full RTIC task set (`imu_task`/`control_task`/`motor_task`/`heartbeat_task`), the adaptive-MPC control stack, arming, calibration, BIT. This is what actually flies. |
| `jfox-fcu-usb` | `src/main_usb.rs` | USB-CDC bring-up binary with a real MAVLink v1 bridge (HEARTBEAT/SYS_STATUS/ATTITUDE) for Mission Planner/QGroundControl compatibility testing. Not the flight application - no RTIC, no control loop, no motor output. See "MAVLink / GCS connectivity" below. |
| `jfox-fcu-minimal` | `src/main_minimal_usb.rs` | Minimal USB CDC init whose only job is satisfying the PX4 bootloader's USB timeout so it exits to application code - a bootloader-recovery/diagnostic tool, not something you fly or connect a GCS to. |

## Honest status (as of this writing)

| Binary | Status |
|---|---|
| `jfox-fcu` | **Verified flashed and running on real PX4FMUv2.4.5 hardware** (2025-12-30, via the PX4-bootloader path below - see `docs/historical/VERIFICATION_STATUS.md`/`docs/historical/V2_STATUS.md` for the original verification record). |
| `jfox-fcu-flight` | Builds clean and passes SITL (`sitl/`), but **has never been flashed to real hardware** - `HARDWARE_BRINGUP.md`'s Stage 1 is the runbook for actually doing that, and hasn't been executed yet. |
| `jfox-fcu-usb` | **Verified on real PX4FMUv2.4.5 hardware (2026-08-04): flashed via QGroundControl, enumerates, and QGC connects and holds the link.** Getting here took two fixes. (1) The 180MHz/PLLSAI clock configuration ran USB at ~51.4MHz and failed to enumerate at all (Windows: "Configuration Descriptor Request Failed", null VID/PID); the clock tree was reworked to 168MHz so PLLQ produces exactly 48MHz. (2) The main loop never called `serial.read()`, so the CDC OUT endpoint filled and NAK'd forever, blocking every host-side write and freezing QGC - see the USB-clock section below and commit `63eaee0`. QGC reports the vehicle **"Not Ready"**, which is correct: this binary cannot arm and serves no parameters, so a GCS has nothing to call ready. |
| `jfox-fcu-minimal` | Builds clean; used historically to recover a board stuck in bootloader mode. |

## Flashing: three paths

### Path 1: SWD via a debug probe (ST-Link, J-Link)

No bootloader interaction needed, works for any binary, gives you live
`defmt`/RTT logs.

```bash
cd firmware
cargo flash --chip STM32F427VITx --release --bin jfox-fcu-flight
# or, to also stream logs:
probe-rs run --chip STM32F427VITx target/thumbv7em-none-eabihf/release/jfox-fcu-flight
```

Pin connections: SWDIO→PA13, SWCLK→PA14, GND→GND (see `bsp/src/pins.rs`).

### Path 2: the board's stock PX4 bootloader over USB serial

This board shipped with (or was previously flashed with) a genuine PX4
bootloader (identifies as VID:PID `26AC:0011`, "3D Robotics" - this project
did not write this bootloader, it's pre-existing on the hardware). This is
the path that was actually used to flash `jfox-fcu` onto real hardware.

```bash
# 1. Convert the ELF to a raw binary:
cd firmware
cargo build --release --bin jfox-fcu-flight
cargo objcopy --release --bin jfox-fcu-flight -- -O binary ../target/thumbv7em-none-eabihf/release/jfox-fcu-flight.bin

# 2. Enter bootloader mode (BOOT0 high during power-on/reset - see
#    FLASHING.md's Method 2 for board-specific detail if BOOT0 isn't
#    obviously labeled).

# 3. Flash via the corrected protocol script (includes the GET_CRC
#    verification step the bootloader requires before it will boot the new
#    firmware - see MISSION_PLANNER_ANALYSIS.md for why the original,
#    simpler script didn't work):
cd ..
python px4_flash_complete.py COM3 target/thumbv7em-none-eabihf/release/jfox-fcu-flight.bin
```

### Path 3: QGroundControl's own Firmware Upgrade screen

QGroundControl's built-in uploader talks the same PX4-bootloader protocol
as `px4_flash_complete.py`, but it doesn't accept a raw `.bin` - it needs
the PX4 `.px4` firmware-package format (JSON metadata + zlib-compressed,
base64-encoded image), and it validates the package's `board_id` against
what the bootloader reports before it will flash. This section documents
what's actually been built and verified, and what hasn't.

**Verified in this environment** (no hardware, so this is as far as
verification could go without a board attached):

- `board_id = 9` is the correct value for PX4FMUv2 (this board's family) -
  confirmed against PX4-Autopilot's own `boards/px4/fmu-v2/firmware.prototype`
  at the source, not recalled from memory.
- `px_mkfw.py` (vendored unmodified at the repo root from
  `PX4/PX4-Autopilot/Tools/px_mkfw.py` - see the attribution comment at its
  top) was run against a real release build of `jfox-fcu-flight` and
  produced a `.px4` file whose embedded image was decompressed and compared
  byte-for-byte (SHA-256) against the original `.bin` - identical.
- QGroundControl's own documentation
  (`docs/en/qgc-user-guide/setup_view/firmware.md` in the `qgroundcontrol`
  repo) confirms the relevant UI path: "Check **Advanced settings** to
  select specific developer releases or install firmware from your local
  file system."

**Verified on real hardware (2026-08-04): this path works, and it is now
the recommended one.** QGC accepted a `px_mkfw.py`-generated `.px4` at
`board_id = 9` and completed real flashes of both stock PX4 firmware and
`jfox-fcu-usb`, reporting success and rebooting into the new image.

**Prefer this path over Path 2.** The earlier advice here - use
`px4_flash_complete.py` first as the lower-risk option - turned out to be
wrong in practice, and the reason is worth recording:

> The PX4 bootloader's listen window is only a few seconds, and with a
> valid application present it hands off almost immediately. Windows needs
> 1-3 seconds just to expose the COM port after enumeration, so a Python
> script cannot reliably open the port and sync before the window closes.
> Roughly 5000 sync attempts across several resets produced not one
> `INSYNC`. QGC's native uploader wins that race; `px4_flash_complete.py`
> does not. Worse, each failed attempt leaves a wedged handle that blocks
> the port for minutes, and killing the process does not release it.

Use Path 2 only with a board already held in bootloader mode. For everyday
flashing, use QGC.

**Steps**:

```bash
# 1. Build and convert to a raw binary (same as Path 2, step 1):
cd firmware
cargo build --release --bin jfox-fcu-flight
cargo objcopy --release --bin jfox-fcu-flight -- -O binary ../target/thumbv7em-none-eabihf/release/jfox-fcu-flight.bin
cd ..

# 2. Package into .px4 (run from a POSIX-style shell, e.g. git-bash - a
#    plain PowerShell `>` redirect adds a UTF-8 BOM that breaks the JSON
#    parser reading this file back; git-bash's `>` does not):
python px_mkfw.py --board_id 9 --version "0.1.0" \
  --summary "JFOX-FCU jfox-fcu-flight" \
  --image target/thumbv7em-none-eabihf/release/jfox-fcu-flight.bin \
  > jfox-fcu-flight.px4
```

Requires Python 3 (`python --version` to check; `winget install -e --id
Python.Python.3.12` if missing). No other dependencies - `px_mkfw.py` only
uses the standard library.

3. **Disconnect the board from USB entirely** (QGC's own docs are explicit
   about this - don't have it connected when you open the Firmware page).
4. Open QGroundControl → **Gear icon** (Vehicle Setup) → **Firmware** in
   the sidebar.
5. Connect the board via USB (directly to the machine, not through a hub).
6. Check **Advanced settings**. This reveals the option to select a
   firmware file from your local filesystem instead of the auto-downloaded
   list - browse to `jfox-fcu-flight.px4`.
7. Click **OK** and watch the progress bar. If `board_id` didn't match what
   the bootloader reports, QGC will refuse before writing anything (a safe
   failure, not a bricked board) - if that happens, the board's actual
   reported ID differs from `9` and needs checking against a real RM0090 or
   a bootloader `GET_DEVICE` query, not assumed.

Same caveats as `jfox-fcu-usb` apply if you're packaging that binary
instead of `jfox-fcu-flight`: see the USB-clock note below before trusting
GCS connectivity once it boots.

## MAVLink / GCS connectivity (`jfox-fcu-usb`)

`jfox-fcu-usb` implements USB CDC (a real virtual COM port, not the raw
UART pins - see `docs/MISSION_PLANNER_ANALYSIS.md` for why that distinction
matters) and sends real MAVLink v1: HEARTBEAT (1Hz, reflects
`flight::arming::ArmingFsm`'s actual armed state - always `false` here,
since this binary has no RC/command-link input and can never actually
arm), SYS_STATUS (1Hz, reflects `flight::bit::BitReport`'s real IMU-init
health), and ATTITUDE (~4Hz, `MadgwickFilter`'s real estimate). The
encoder (`telemetry::mavlink`) computes a correct CRC16 and per-message
`CRC_EXTRA` - every constant was sourced from the authoritative
`mavlink/c_library_v2` reference implementation and its output was
cross-checked byte-for-byte against a real `pymavlink` install, not
hand-computed (see `telemetry/src/mavlink.rs`'s doc comment and tests).
This fixes an earlier version of this same binary, which sent a heartbeat
missing its CRC entirely - silently rejected by every real MAVLink parser.

### The USB 48MHz clock, and why SYSCLK is 168MHz

USB Full Speed requires a 48MHz clock accurate to +-0.25%. On
STM32F42x/43x that clock can come **only** from the main PLL's Q-output
(PLL48CK) - unlike the F446/F469 and F412/F413, this part has no
`CK48MSEL` mux, so PLLSAI cannot be used as a USB clock source.

A 180MHz SYSCLK needs a 360MHz VCO, and 360 has no integer PLLQ giving 48
(360/7.5). A 336MHz VCO does: 336/7 = 48 exactly, with PLLP=/2 giving
168MHz. Exact USB and the part's 180MHz maximum are therefore mutually
exclusive on this silicon, and this firmware runs at 168MHz so USB works.
Full reasoning is in `bsp/src/clocks.rs`'s module-level note.

**This is the fix for an observed hardware failure, and it is now
hardware-verified (2026-08-04).** The earlier configuration ran at 180MHz
and attempted to route PLLSAI to USB by writing `CK48MSEL` at RCC offset
0x90 - reserved space on this part, which the PAC's failure to model it
should have been read as a warning about. The write did nothing, USB ran
from PLLQ at 360/7 ~= 51.43MHz (7.1% fast, far outside +-0.25%), and
Windows failed enumeration with "Configuration Descriptor Request Failed"
under a null VID/PID. At 168MHz the device enumerates cleanly and QGC
connects.

### The second USB fault: a CDC OUT endpoint nobody read

Fixing the clock was necessary but not sufficient. The device enumerated,
yet every host-side write still timed out and QGroundControl froze solid
holding the port. Cause: the main loop called `usb_dev.poll()` but never
`serial.read()`. This binary is transmit-only, so received bytes are
genuinely unwanted - but an OUT endpoint that is never read fills after
one packet and NAKs everything after it, the host's driver buffer backs up
behind that, and every write blocks. Fixed in `63eaee0` by reading into a
scratch buffer and discarding.

**Two diagnostic lessons, recorded because this was misdiagnosed as a
clock fault for hours:**

- The device enumerated with `CM_PROB_NONE` the whole time. Full-speed
  enumeration requires 48MHz within +-0.25%, so **a clean enumeration is
  positive evidence the clock is right**, not a neutral observation.
- The failures were **write-only** - reads never hung. A fault with a
  direction is an endpoint problem, not a clock or silicon problem.

Also: `jfox-fcu-usb` declares `UsbVidPid(0x26AC, 0x0011)`, byte-identical
to the PX4 bootloader, so **the enumerated VID/PID cannot tell you which
image is running**. Several wrong conclusions were drawn from that PID
before it was noticed. Giving the application its own PID would make the
question answerable from the host.

One further item worth confirming during that pass: `Clocks::configure()`
never writes `PWR_CR`, so the core runs at its reset-default voltage
scale. That is believed adequate at 168MHz (over-drive mode is only
required above it), which would also mean the old 180MHz configuration was
out of spec on this point independently of the USB problem. This has not
been checked against a real RM0090 copy - do that before relying on it.

Once connected: QGroundControl auto-connects over the enumerated COM port;
Mission Planner needs the COM port selected manually. Confirm live
attitude-indicator movement when the board is tilted by hand, and that the
GCS's armed indicator stays "disarmed" (correctly - this binary cannot
arm).

**Expect QGC to report the vehicle "Not Ready", and do not treat that as a
fault.** A GCS calls a vehicle ready once it can arm it and has pulled a
parameter set. This binary can never arm, and being transmit-only it never
answers `PARAM_REQUEST_LIST` or a capability request, so QGC has nothing
to call ready. A connected link with a moving attitude indicator is the
whole of what this binary is meant to demonstrate; anything more needs
`jfox-fcu-flight` and a command link, neither of which exists yet.

## What's next

See `JFOXGROUNDCONTROL_ROADMAP.md` for where a future custom secure
datalink ("JFOXLink") and companion ground station ("JFOXGroundControl")
fit relative to this MAVLink bridge - planning only, nothing implemented
yet.
