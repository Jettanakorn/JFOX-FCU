# Building and flashing JFOX-FCU

The single authoritative source for how to build each firmware binary and
get it onto real PX4FMUv2.4.5 hardware. Supersedes the scattered, partly
outdated 2025-12-30 documents at the repo root (`FLASHING.md`,
`VERIFICATION_STATUS.md`, `V2_STATUS.md`, `PROGRESS_SUMMARY.md`,
`QUICK_FIX_GUIDE.md`, `BUILD_AND_FLASH_SUCCESS.md`,
`FLASH_INSTRUCTIONS.txt`, `FLASH_V2_INSTRUCTIONS.txt`) - those are kept for
their protocol reverse-engineering detail (especially
`MISSION_PLANNER_ANALYSIS.md`, left as reference material, not a status doc)
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
| `jfox-fcu` | **Verified flashed and running on real PX4FMUv2.4.5 hardware** (2025-12-30, via the PX4-bootloader path below - see `VERIFICATION_STATUS.md`/`V2_STATUS.md` for the original verification record). |
| `jfox-fcu-flight` | Builds clean and passes SITL (`sitl/`), but **has never been flashed to real hardware** - `HARDWARE_BRINGUP.md`'s Stage 1 is the runbook for actually doing that, and hasn't been executed yet. |
| `jfox-fcu-usb` | Builds clean, has a real (CRC-correct, pymavlink-cross-checked) MAVLink v1 implementation - see below. **Never yet connected to a real GCS on real hardware** - the USB-clock fix it depends on (see below) is itself unverified on real silicon. |
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

**Not verified** (needs real hardware): that QGC actually accepts this
`.px4` file and completes a real flash. `jfox-fcu-flight` has never been
flashed by *any* method yet (see the status table above) - using QGC's
uploader would be the first attempt by this path specifically, stacked on
top of that. If you want the lowest-risk first flash, use Path 2
(`px4_flash_complete.py`) first to confirm the board and binary work at
all, then treat this path as a convenience once that's established -
don't make this the first time you're finding out both things at once.

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
UART pins - see `MISSION_PLANNER_ANALYSIS.md` for why that distinction
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

**One real caveat before this can be trusted on hardware**: USB Full Speed
requires a 48MHz clock accurate to +-0.25%. This firmware's main PLL cannot
produce that exactly (see `bsp/src/clocks.rs`'s PLLSAI step for the full
explanation), so a second PLL (PLLSAI) is configured to generate it
instead. Most of that fix is cross-checked against this project's `stm32f4`
PAC crate, but the final piece - the `CK48MSEL` register that actually
routes PLLSAI's output to the USB peripheral - is **not modeled by this
project's PAC at all**, and its exact register offset/bit position is
sourced from reference-manual knowledge with no independent verification
possible in the environment this was written in. It's flagged loudly in
`bsp/src/clocks.rs`'s own comments. **Confirm real USB enumeration behavior
on actual hardware, or check the address against a real RM0090 copy, before
trusting this.**

Once connected: QGroundControl should auto-connect over the enumerated COM
port; Mission Planner needs the COM port selected manually. Confirm a
correct autopilot icon and live attitude-indicator movement when the board
is tilted by hand, and that the GCS's armed indicator stays "disarmed"
(correctly - this binary cannot arm).

## What's next

See `JFOXGROUNDCONTROL_ROADMAP.md` for where a future custom secure
datalink ("JFOXLink") and companion ground station ("JFOXGroundControl")
fit relative to this MAVLink bridge - planning only, nothing implemented
yet.
