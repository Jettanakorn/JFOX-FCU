#!/usr/bin/env python3
"""Check the JFOX-FMU schematic against the datasheets.

ERC proves a schematic is well-formed. It cannot tell you that AP_CS went to
pin 12 rather than pin 11, because both are electrically plausible. These
assertions come from the verified tables in `PINOUTS.md`, so a wiring slip in
the generator is caught rather than fabricated into a board.

    python hardware/tools/check_fmu_schematic.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCH = REPO / "hardware" / "jfox-fmu-v1" / "sensors.kicad_sch"

CLI_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/bin/kicad-cli.exe",
    Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
]

# (net, ref, pin, why) - every one traceable to a datasheet table.
SIGNALS = [
    ("SPI2_MISO", "U1", "1",  "ICM-42688-P AP_SDO is pin 1 (DS-000347)"),
    ("SPI2_SCK",  "U1", "13", "ICM-42688-P AP_SCLK is pin 13"),
    ("SPI2_MOSI", "U1", "14", "ICM-42688-P AP_SDI is pin 14"),
    ("IMU2_CS",   "U1", "12", "ICM-42688-P AP_CS is pin 12"),
    ("IMU2_DRDY", "U1", "4",  "ICM-42688-P INT1 is pin 4"),
    ("SPI6_MISO", "U2", "1",  "ICM-45686 AP_SDO is pin 1 (DS-000577)"),
    ("IMU3_CS",   "U2", "12", "ICM-45686 AP_CS is pin 12"),
    ("I2C1_SCL",  "U4", "2",  "BMP388 SCK is pin 2 (BST-BMP388-DS001-07)"),
    ("I2C1_SDA",  "U4", "4",  "BMP388 SDI is pin 4"),
    ("BARO1_INT", "U4", "7",  "BMP388 INT is pin 7"),
    ("FRAM_CS",   "U5", "1",  "FM25V02A CS is pin 1 (001-90865)"),
    ("SPI4_MISO", "U5", "2",  "FM25V02A SO is pin 2"),
    ("SPI4_MOSI", "U5", "5",  "FM25V02A SI is pin 5"),
    ("SPI4_SCK",  "U5", "6",  "FM25V02A SCK is pin 6"),
]

# Ties the datasheets require, as opposed to merely permit.
TIES = [
    ("GND",   "U1", "7", "ICM-42688-P pin 7 says Connect to GND, not may"),
    ("GND",   "U1", "9", "ICM-42688-P pin 9 to GND when FSYNC unused"),
    ("+3V3",  "U5", "3", "FM25V02A WP must be tied to VDD if unused"),
    ("+3V3",  "U5", "7", "FM25V02A HOLD tied high when unused"),
]

# Each IMU must sit on its own switchable rail: a wedged sensor has to be
# power-cyclable without disturbing the other two.
RAILS = [("U1", "+3V3_IMU2"), ("U2", "+3V3_IMU3"), ("U3", "+3V3_IMU1")]


def cli():
    found = shutil.which("kicad-cli")
    if found:
        return found
    for c in CLI_CANDIDATES:
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found - see hardware/README.md")


def nets():
    out = Path(tempfile.gettempdir()) / "fmu_check.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"netlist export failed:\n{r.stdout}{r.stderr}")
    txt = out.read_text(encoding="utf-8")
    d = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            d[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))
    return d


def check_power(fails):
    """The power tree's load-bearing properties.

    Each sensor rail must come from its own load switch, or "power-cycle the
    wedged IMU" quietly means "power-cycle two working ones as well". And the
    ORing controller's three inputs must stay distinct, or the redundancy it
    exists to provide is gone.
    """
    out = Path(tempfile.gettempdir()) / "fmu_pwr.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out),
                        str(SCH.parent / "power.kicad_sch")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append("power netlist export failed")
        return
    txt = out.read_text(encoding="utf-8")
    # Keyed by (ref, pin), not ref alone. Comparing bare refs made all three
    # ORing inputs look identical, because on this sheet each touches only
    # U20 - a false alarm from the checker, not a fault in the schematic.
    n = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            n[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))

    def refs(net):
        return {r for r, _ in n.get(net, set())}

    switches = {"+3V3_IMU1": "U23", "+3V3_IMU2": "U24",
                "+3V3_IMU3": "U25", "+3V3_SENS": "U26"}
    for rail, ref in switches.items():
        srcs = refs(rail)
        if ref not in srcs:
            fails.append(f"{rail} does not come from {ref}")
        others = (srcs & set(switches.values())) - {ref}
        if others:
            fails.append(f"{rail} is also fed by {sorted(others)} - "
                         "each rail needs its own switch")

    # The ORing controller's three inputs must be distinct nets reaching
    # distinct pins, or the redundancy it exists to provide is gone.
    ins = ["VDD_BRICK", "VDD_SERVO", "VBUS_USB"]
    for name in ins:
        if name not in n:
            fails.append(f"{name} is not present on the power sheet")
    for a in range(3):
        for b in range(a + 1, 3):
            if ins[a] in n and ins[b] in n and n[ins[a]] & n[ins[b]]:
                fails.append(f"{ins[a]} and {ins[b]} share a pin - "
                             "prioritised ORing needs distinct sources")


def check_mcu(fails):
    """Every allocated signal must reach the pin the allocator chose.

    The netlist names pins by number; the allocation names them by port (PA9).
    The symbol carries both, so the mapping is read from it rather than
    assumed - and that is the whole point, since a schematic with SPI2_SCK on
    the wrong port pin is electrically valid and completely broken.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import gen_fmu_schematic as G
    import plan_pinout as PP

    lib = G.sym_def(G.KICAD_SYMS / "MCU_ST_STM32H7.kicad_sym",
                    "STM32H753IITx", "MCU_ST_STM32H7")
    num_of = {}
    for m in re.finditer(
            r'\(pin\s+\w+\s+\w+\s*\(at[^)]*\)[\s\S]*?\(name\s+"([^"]+)"'
            r'[\s\S]*?\(number\s+"([^"]+)"', lib):
        num_of.setdefault(m.group(1), m.group(2))

    _, table = PP.load()
    assigned, _used, _probs, gpio = PP.allocate(table)

    out = Path(tempfile.gettempdir()) / "fmu_mcu.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out),
                        str(SCH.parent / "mcu.kicad_sch")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append("MCU netlist export failed")
        return 0
    txt = out.read_text(encoding="utf-8")
    n = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            n[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))

    want = [(f"{p}_{s}", pin) for _f, p, s, pin, _a in assigned]
    want += [(net, pin) for net, pin in gpio]
    checked = 0
    for net, port in want:
        num = num_of.get(port)
        if num is None:
            fails.append(f"symbol has no pin named {port}")
            continue
        if ("U10", num) not in n.get(net, set()):
            fails.append(f"{net} is not on U10 pin {num} ({port})")
        checked += 1
    return checked


def main():
    n = nets()
    fails = []

    for net, ref, pin, why in SIGNALS:
        if (ref, pin) not in n.get(net, set()):
            fails.append(f"{net} does not reach {ref}.{pin} - {why}")
    print(f"  [{'PASS' if not fails else 'FAIL'}] "
          f"{len(SIGNALS)} signals land on the datasheet's pins")

    before = len(fails)
    for net, ref, pin, why in TIES:
        if (ref, pin) not in n.get(net, set()):
            fails.append(f"{ref}.{pin} is not on {net} - {why}")
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"{len(TIES)} datasheet-mandated ties are tied")

    before = len(fails)
    seen = {}
    for ref, rail in RAILS:
        if not any(r == ref for r, _ in n.get(rail, set())):
            fails.append(f"{ref} is not powered from {rail}")
        seen.setdefault(rail, []).append(ref)
    for rail, refs in seen.items():
        if len(refs) > 1:
            fails.append(f"{rail} feeds {refs} - each IMU needs its own rail")
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"each IMU is on its own switchable rail")

    before = len(fails)
    check_power(fails)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"power tree: 4 independent sensor rails, ORing intact")

    before = len(fails)
    nchk = check_mcu(fails)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"{nchk} MCU signals reach the pin the allocator chose")

    if fails:
        print("\nFAILURES:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("\nschematic matches the datasheets")


if __name__ == "__main__":
    main()
