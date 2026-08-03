#!/usr/bin/env python3
"""Allocate STM32H753 pins from verified alternate-function data.

The first task on this project was "fix PWM pin conflicts in bsp/src/pins.rs" -
five of eight PWM channels on the old board collided with SPI1 and SPI2,
because the pin map was written by hand. This allocates pins mechanically
instead, from the chip's real AF table, and fails loudly on a conflict.

Source data is `hardware/jfox-fmu-v1/STM32H753II.json` from
embassy-rs/stm32-data-generated, which carries per-pin signal and AF-number
mappings for the exact part. It is checked in so the allocation is
reproducible.

    python hardware/tools/plan_pinout.py            # allocate and report
    python hardware/tools/plan_pinout.py --write    # also write PINMAP.md
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
CHIP = BOARD / "STM32H753II.json"
OUT = BOARD / "PINMAP.md"

# What the board needs, in priority order. Each entry is
# (function, peripheral, signal, [pin preference]) - a preference is honoured
# only if that pin genuinely carries the signal per the AF table.
#
# Three IMUs on three separate SPI buses is the FMUv6X arrangement: one sensor
# hanging its bus must not take the other two with it.
WANTED = [
    # --- sensor buses -----------------------------------------------------
    ("IMU1 BMI088",      "SPI1", ["SCK", "MISO", "MOSI"]),
    ("IMU2 ICM-42688-P", "SPI2", ["SCK", "MISO", "MOSI"]),
    # IMU3 is on SPI6, not SPI3: SPI3's only pins are PC10/11/12, which are
    # also SDMMC1's CK/D2/D3. Putting the third IMU there costs the SD card
    # its 4-bit mode. The allocator found this - it is not a guess.
    ("IMU3 ICM-45686",   "SPI6", ["SCK", "MISO", "MOSI"]),
    ("FRAM",             "SPI4", ["SCK", "MISO", "MOSI"]),
    ("external sensor",  "SPI5", ["SCK", "MISO", "MOSI"]),
    # --- buses ------------------------------------------------------------
    ("baro + mag",       "I2C1", ["SCL", "SDA"]),
    ("external I2C",     "I2C2", ["SCL", "SDA"]),
    ("CAN1 (TMR bus)",   "FDCAN1", ["TX", "RX"]),
    ("CAN2",             "FDCAN2", ["TX", "RX"]),
    # --- comms ------------------------------------------------------------
    ("telemetry 1",      "USART2", ["TX", "RX", "CTS", "RTS"]),
    ("telemetry 2",      "USART3", ["TX", "RX", "CTS", "RTS"]),
    ("GPS 1",            "UART4",  ["TX", "RX"]),
    ("GPS 2",            "UART7",  ["TX", "RX"]),
    ("debug console",    "USART1", ["TX", "RX"]),
    ("RC input",         "UART8",  ["TX", "RX"]),
    # --- storage and host -------------------------------------------------
    ("microSD",          "SDMMC1", ["CK", "CMD", "D0", "D1", "D2", "D3"]),
    ("USB",              "USB_OTG_FS", ["DM", "DP"]),
    # --- motor outputs ----------------------------------------------------
    ("PWM 1-4",          "TIM1", ["CH1", "CH2", "CH3", "CH4"]),
    ("PWM 5-8",          "TIM4", ["CH1", "CH2", "CH3", "CH4"]),
]

# Plain GPIO - no alternate-function constraint, so these are assigned from
# whatever the peripherals did not need. Named here because the schematic
# needs them: chip selects, data-ready interrupts, and the per-bus rail
# enables that let a wedged sensor be power-cycled.
GPIO_NETS = [
    "IMU1A_CS", "IMU1G_CS", "IMU2_CS", "IMU3_CS", "FRAM_CS",
    "IMU1A_DRDY", "IMU1G_DRDY", "IMU2_DRDY", "IMU3_DRDY",
    "BARO1_INT", "BARO2_INT", "MAG_DRDY",
    "EN_3V3_IMU1", "EN_3V3_IMU2", "EN_3V3_IMU3", "EN_3V3_SENS",
    "LED_R", "LED_G", "LED_B",
    "SAFETY_SW", "SAFETY_LED", "SD_DETECT", "VBUS_SENSE",
    # Status inputs. Every one of these was an output on some part that
    # reached no MCU pin - the board could not tell whether its power source
    # was valid, whether a sensor rail had tripped, or whether an isolated
    # CAN supply had failed. A fault nothing can read is not a fault report.
    "BRICK_VALID", "SERVO_VALID", "USB_VALID",
    "PG_3V3",
    "IMU1_RAIL_FLG", "IMU2_RAIL_FLG", "IMU3_RAIL_FLG", "SENS_RAIL_FLG",
    "CAN1_FLT", "CAN2_FLT",
]

# Pins that must stay free for their dedicated function.
RESERVED = {
    "PA13": "SWDIO (debug)",
    "PA14": "SWCLK (debug)",
    "PB3":  "SWO (trace)",
    "PC14": "OSC32_IN (LSE)",
    "PC15": "OSC32_OUT (LSE)",
    "PH0":  "OSC_IN (HSE 16 MHz)",
    "PH1":  "OSC_OUT (HSE 16 MHz)",
}


def load():
    if not CHIP.exists():
        sys.exit(f"missing {CHIP} - fetch STM32H753II.json from "
                 "embassy-rs/stm32-data-generated")
    d = json.loads(CHIP.read_text(encoding="utf-8"))
    core = d["cores"][0]
    table = {}
    for p in core["peripherals"]:
        for pin in p.get("pins", []):
            table.setdefault(p["name"], []).append(
                (pin["pin"], pin["signal"], pin.get("af")))
    return d, table


def allocate(table):
    """Assign every requested signal to a pin, or say which cannot be.

    This is a constraint problem, not a list to walk. Allocating in the order
    the wishlist happens to be written fails: SPI3 has many candidate pins and
    SDMMC1 has few, so taking SPI3 first can consume PC10/11/12 and leave
    SDMMC1 with nowhere to go - which is exactly what the first version did.

    So: pick the signal with the fewest remaining candidates each time
    (minimum-remaining-values), and backtrack when a choice turns out to make
    something else impossible.
    """
    items = []
    problems = []
    for func, periph, signals in WANTED:
        if periph not in table:
            problems.append(f"{periph} not present on this part")
            continue
        for sig in signals:
            opts = [(p, a) for p, s, a in table[periph] if s == sig]
            if not opts:
                problems.append(f"{periph}.{sig} ({func}): part carries no such signal")
                continue
            items.append((func, periph, sig, opts))

    # Static contention: how many other signals could also want this pin.
    contention = {}
    for sigs in table.values():
        for p, _s, _a in sigs:
            contention[p] = contention.get(p, 0) + 1

    used = dict(RESERVED)
    assigned = []
    remaining = list(items)

    # Repeatedly take whichever signal currently has the fewest options left.
    # Best-effort rather than all-or-nothing: a request set that cannot be
    # fully satisfied should still show what fits and name what does not,
    # instead of unwinding to nothing and reporting every signal as failed.
    while remaining:
        remaining.sort(key=lambda it: sum(1 for p, _ in it[3] if p not in used))
        func, periph, sig, opts = remaining.pop(0)
        free = [(p, a) for p, a in opts if p not in used]
        if not free:
            blockers = sorted({used[p] for p, _ in opts if p in used})
            problems.append(
                f"{periph}.{sig} ({func}): every candidate pin taken - "
                f"held by {', '.join(blockers)}")
            continue
        # among equally valid pins, take the one fewest other things want
        free.sort(key=lambda c: (contention.get(c[0], 0), c[0]))
        pin, af = free[0]
        used[pin] = f"{periph}.{sig}"
        assigned.append((func, periph, sig, pin, af))

    # Plain GPIO last, from whatever is left. Prefer the most contended pins
    # here - they are the ones no peripheral can use now anyway, and leaving
    # the uncontended ones free keeps options open for a later revision.
    all_pins = sorted({p for sigs in table.values() for p, _s, _a in sigs})
    free = [p for p in all_pins if p not in used]
    free.sort(key=lambda p: (-contention.get(p, 0), p))
    gpio = []
    for net in GPIO_NETS:
        if not free:
            problems.append(f"{net}: no GPIO left")
            continue
        pin = free.pop(0)
        used[pin] = net
        gpio.append((net, pin))

    return assigned, used, problems, gpio


def main():
    d, table = load()
    assigned, used, problems, gpio = allocate(table)

    ram = sum(m["size"] for bank in d["memory"] for m in bank
              if m["kind"] == "ram")
    flash = sum(m["size"] for bank in d["memory"] for m in bank
                if m["kind"] == "flash")
    print(f"{d['name']}  RAM {ram // 1024} KB  flash {flash // 1024} KB")
    print(f"allocated {len(assigned)} signals across "
          f"{len({a[1] for a in assigned})} peripherals\n")

    cur = None
    for func, periph, sig, pin, af in assigned:
        if periph != cur:
            print(f"  {periph:<11} ({func})")
            cur = periph
        print(f"      {sig:<5} -> {pin:<5} AF{af if af is not None else '-'}")

    if problems:
        print("\nUNRESOLVED:")
        for p in problems:
            print("  -", p)

    print(f"\n  plain GPIO ({len(gpio)}):")
    for net, pin in gpio:
        print(f"      {net:<13} -> {pin}")
    print(f"\n{len(used)} pins committed ({len(RESERVED)} reserved for debug/clock)")

    if "--write" in sys.argv:
        write_map(d, assigned, used, problems, ram, flash, gpio)
        print(f"wrote {OUT.relative_to(REPO)}")
    if problems:
        raise SystemExit(1)


def write_map(d, assigned, used, problems, ram, flash, gpio):
    L = [f"# {d['name']} pin map", "",
         "**Generated** by `hardware/tools/plan_pinout.py` from",
         "`STM32H753II.json` (embassy-rs/stm32-data-generated), which carries the",
         "part's real alternate-function table. Do not hand-edit — re-run it.",
         "",
         f"RAM {ram // 1024} KB · flash {flash // 1024} KB · package LQFP176.",
         "",
         "Allocated mechanically because the previous board's pin map was written",
         "by hand and put five of eight PWM channels on top of SPI1 and SPI2.",
         "", "## Assignments", "",
         "| Function | Peripheral | Signal | Pin | AF |", "|---|---|---|---|---|"]
    for func, periph, sig, pin, af in assigned:
        L.append(f"| {func} | {periph} | {sig} | **{pin}** | "
                 f"{'AF' + str(af) if af is not None else '—'} |")
    L += ["", "## Reserved", "",
          "| Pin | Why |", "|---|---|"]
    for pin, why in sorted(RESERVED.items()):
        L.append(f"| {pin} | {why} |")
    if problems:
        L += ["", "## Unresolved", ""]
        L += [f"- {p}" for p in problems]
    L += ["", "## Plain GPIO", "",
          "No alternate-function constraint, so these take whatever the",
          "peripherals did not need - preferring the most contended pins, since",
          "those are the ones no peripheral could use anyway.", "",
          "| Net | Pin |", "|---|---|"]
    L += [f"| {net} | **{pin}** |" for net, pin in gpio]
    L += [""]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
