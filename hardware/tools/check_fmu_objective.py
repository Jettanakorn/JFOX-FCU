#!/usr/bin/env python3
"""Check the board against what it is supposed to be, not just against parts.

Every other checker here asks "is this part wired the way its datasheet says?"
All of them can pass on a board that is wired perfectly and is still the wrong
board. That is not hypothetical: `ARCHITECTURE.md` specifies two barometers
from two vendors and an internal magnetometer, and for several commits the
schematic had one barometer and no magnetometer. Every check passed. The nets
for the missing parts existed, correctly named, going nowhere - and "isolated
label" is such ordinary ERC noise that sixty of them hid two absent sensors.

So this file encodes the *design objective* from ARCHITECTURE.md as assertions
against the real netlist. It is the check that answers "is this the aircraft
we meant to build", which is a different question from "is this schematic
self-consistent".

    python hardware/tools/check_fmu_objective.py

Exits non-zero if the board does not meet its own specification.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
SCH = BOARD / "jfox-fmu.kicad_sch"

# ---------------------------------------------------------------------------
# The objective, transcribed from ARCHITECTURE.md "Sensors" and "Why no IO
# co-processor". Each entry names the section it came from, so a spec change
# and a check change stay visibly coupled.
# ---------------------------------------------------------------------------

# part value -> vendor. Vendor diversity is the entire point of the sensor
# selection, so it has to be a fact the checker knows, not an inference.
VENDOR = {
    "BMI088": "Bosch", "BMP388": "Bosch", "BMM150": "Bosch",
    "ICM-42688-P": "TDK", "ICM-45686": "TDK", "ICP-20100": "TDK",
    "FM25V02A": "Infineon",
}

IMUS = ["BMI088", "ICM-42688-P", "ICM-45686"]
BAROS = ["BMP388", "ICP-20100"]
MAGS = ["BMM150"]

# Each IMU's bus and its switchable rail - "one sensor hanging its bus must
# not take the other two with it" only holds if these are genuinely distinct.
IMU_BUSES = {"BMI088": "SPI1", "ICM-42688-P": "SPI2", "ICM-45686": "SPI6"}
IMU_RAILS = {"BMI088": "+3V3_IMU1", "ICM-42688-P": "+3V3_IMU2",
             "ICM-45686": "+3V3_IMU3"}


def cli():
    for c in (Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"),
              Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found")


def netlist():
    out = Path(tempfile.gettempdir()) / "fmu_obj.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"netlist export failed:\n{r.stdout}\n{r.stderr}")
    txt = out.read_text(encoding="utf-8")

    comps = {}
    for b in re.split(r'\n\s*\(comp\b', txt)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', b)
        val = re.search(r'\(value "([^"]*)"\)', b)
        if ref:
            comps[ref.group(1)] = val.group(1) if val else ""

    nets = {}
    for b in re.split(r'\n\s*\(net\b', txt)[1:]:
        nm = re.search(r'\(name "([^"]*)"\)', b)
        if nm:
            nets[nm.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', b))
    return comps, nets


def main():
    comps, nets = netlist()
    present = set(comps.values())
    refof = {}
    for r, v in comps.items():
        refof.setdefault(v, []).append(r)

    fails = []

    def check(label, problems):
        print(f"  [{'PASS' if not problems else 'FAIL'}] {label}")
        fails.extend(problems)

    # --- three IMUs, at least two vendors --------------------------------
    p = [f"{i} is specified but not on the board" for i in IMUS
         if i not in present]
    vendors = {VENDOR[i] for i in IMUS if i in present}
    if not p and len(vendors) < 2:
        p.append(f"all three IMUs are {vendors} - a vendor-wide errata takes "
                 "the whole attitude solution")
    check(f"3 IMUs from {len(vendors)} vendors "
          f"({', '.join(sorted(vendors))})", p)

    # --- each IMU on its own bus and its own rail -------------------------
    p = []
    seen_bus, seen_rail = {}, {}
    for imu in IMUS:
        if imu not in present:
            continue
        ref = refof[imu][0]
        bus, rail = IMU_BUSES[imu], IMU_RAILS[imu]
        on_bus = [n for n in nets if n.startswith(bus + "_")
                  and any(r == ref for r, _ in nets[n])]
        if not on_bus:
            p.append(f"{imu} ({ref}) is not on {bus}")
        if not any(r == ref for r, _ in nets.get(rail, set())):
            p.append(f"{imu} ({ref}) is not powered from {rail}")
        if bus in seen_bus:
            p.append(f"{bus} carries both {seen_bus[bus]} and {imu} - "
                     "one hung bus would take both")
        if rail in seen_rail:
            p.append(f"{rail} feeds both {seen_rail[rail]} and {imu}")
        seen_bus[bus], seen_rail[rail] = imu, imu
    check("each IMU on its own SPI bus and its own switchable rail", p)

    # --- two barometers, two vendors --------------------------------------
    p = [f"{b} is specified but not on the board" for b in BAROS
         if b not in present]
    bv = {VENDOR[b] for b in BAROS if b in present}
    if not p and len(bv) < 2:
        p.append(f"both barometers are {bv} - the second one buys redundancy, "
                 "not diversity")
    check(f"2 barometers from {len(bv)} vendors "
          f"({', '.join(sorted(bv))})", p)

    # --- magnetometer ------------------------------------------------------
    p = [f"{m} is specified but not on the board" for m in MAGS
         if m not in present]
    check("magnetometer present", p)

    # --- shared I2C bus needs pull-ups ------------------------------------
    # Both the ICP-20100 and BMM150 datasheets say so outright. Without them
    # the bus never releases and no sensor on it ever answers.
    p = []
    for line in ("I2C1_SCL", "I2C1_SDA"):
        pulls = [r for r, _ in nets.get(line, set()) if r.startswith("R")]
        if not pulls:
            p.append(f"{line} has no pull-up - the bus cannot idle high")
    check("shared I2C bus has pull-ups", p)

    # --- two CAN buses, both with transceivers ----------------------------
    # v2.4.5 wired CAN2 to the MCU with no transceiver, so it was never a bus.
    p = []
    for n in (1, 2):
        xcv = [r for r, _ in nets.get(f"CAN{n}_H", set()) if r.startswith("U")]
        if not xcv:
            p.append(f"CAN{n} has no transceiver - it is not a bus")
    check("2 CAN buses, both with transceivers", p)

    # --- FRAM for parameters and calibration ------------------------------
    check("FRAM present", ["FM25V02A missing"] if "FM25V02A" not in present
          else [])

    # --- isolated I/O ------------------------------------------------------
    # ARCHITECTURE.md "Isolated I/O": every off-board signal crosses a
    # galvanic barrier, twice, by independent paths; actuator links are
    # fibre. None of it is built yet. These assertions are written now so the
    # gap is measured on every run instead of being remembered, which is what
    # happened to the second barometer and the magnetometer.
    p = []
    isolators = [r for r, v in comps.items()
                 if any(k in v.upper() for k in
                        ("ADUM", "SI86", "ISO10", "ISOW10", "ISO12", "6N137", "HCPL",
                         "TLP", "ISO7", "MAX146"))]
    if not isolators:
        p.append("no isolator parts on the board - every off-board signal "
                 "currently reaches the MCU directly")
    check("off-board I/O crosses a galvanic barrier", p)

    p = []
    fibre = [r for r, v in comps.items()
             if any(k in v.upper() for k in ("HFBR", "AFBR", "SP000", "IF-E"))]
    if not fibre:
        p.append("no fibre-optic transmitters or receivers - actuator links "
                 "are specified as fibre")
    check("actuator links are fibre-optic", p)

    # An isolated barrier is decorative unless the far side has its own
    # supply. Borrowing the digital rail defeats the whole point.
    p = []
    iso_rails = [n for n in nets if re.match(r'^\+?\d*V?\d*_ISO', n, re.I)
                 or n.upper().startswith(("+3V3_ISO", "VISO"))]
    if not iso_rails:
        p.append("no isolated supply rail - the far side of a barrier cannot "
                 "share the digital rail and still be isolated")
    check("isolated side has its own supply", p)

    # --- no IO co-processor, deliberately ---------------------------------
    # Listed so that adding one is a visible decision rather than a drift.
    io = [r for r, v in comps.items() if "STM32F1" in v or "STM32F3" in v]
    check("no IO co-processor (deliberate - see ARCHITECTURE.md)",
          [f"unexpected second MCU: {io}"] if io else [])

    print()
    if fails:
        print("THE BOARD DOES NOT MEET ITS OWN SPECIFICATION:")
        for f in fails:
            print("  -", f)
        return 1
    print("the board matches the objective in ARCHITECTURE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
