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


# Nets that must span two sheets, with the parts they have to join. This is
# what proves the design is one circuit rather than four drawings that happen
# to use similar label names.
CROSS_SHEET = [
    ("FDCAN1_TX",     {"U10", "U30"}, "MCU to CAN1 transceiver"),
    ("FDCAN1_RX",     {"U10", "U30"}, "CAN1 transceiver back to MCU"),
    ("FDCAN2_TX",     {"U10", "U31"}, "MCU to CAN2 transceiver"),
    ("USB_OTG_FS_DP", {"U10", "J30"}, "MCU to USB-C"),
    ("USB_OTG_FS_DM", {"U10", "J30"}, "MCU to USB-C"),
    ("SDMMC1_CK",     {"U10", "J31"}, "MCU to microSD"),
    ("SDMMC1_CMD",    {"U10", "J31"}, "MCU to microSD"),
    ("SPI2_SCK",      {"U10", "U1"},  "MCU to IMU2"),
    ("IMU2_CS",       {"U10", "U1"},  "MCU chip-selects IMU2"),
    ("SPI6_SCK",      {"U10", "U2"},  "MCU to IMU3"),
    ("SPI4_SCK",      {"U10", "U5"},  "MCU to FRAM"),
    ("I2C1_SCL",      {"U10", "U4"},  "MCU to barometer"),
    ("EN_3V3_IMU1",   {"U10", "U23"}, "MCU controls IMU1's rail"),
    ("EN_3V3_IMU2",   {"U10", "U24"}, "MCU controls IMU2's rail"),
    ("EN_3V3_IMU3",   {"U10", "U25"}, "MCU controls IMU3's rail"),
    ("+3V3_IMU2",     {"U24", "U1"},  "IMU2 powered from its own switch"),
]


def check_cross_sheet(fails):
    """Every sheet is one circuit, not four drawings with similar labels.

    Cross-sheet nets here are global labels, which connect only once the
    sheets are children of a common root. Before that root existed these all
    read as isolated on both ends - the nets were right and the project was
    not assembled - so this asserts the assembly, not just the naming.
    """
    out = Path(tempfile.gettempdir()) / "fmu_proj.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out),
                        str(SCH.parent / "jfox-fmu.kicad_sch")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append("project netlist export failed")
        return 0
    txt = out.read_text(encoding="utf-8")
    n = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            n[m.group(1).lstrip("/")] = set(re.findall(r'\(ref "([^"]+)"\)', blk))
    for net, want, why in CROSS_SHEET:
        got = n.get(net, set())
        if not want <= got:
            fails.append(f"{net} joins {sorted(got)}, needs {sorted(want)} - {why}")
    return len(CROSS_SHEET)


def check_passives(fails):
    """The parts whose absence is invisible until the board misbehaves.

    A missing decoupling capacitor does not fail ERC, does not fail DRC, and
    does not stop a board being fabricated. It shows up as an MCU that resets
    under load. So the count is asserted, along with the two CAN terminators
    that existed only as a note on the comms sheet until this sheet was drawn.
    """
    out = Path(tempfile.gettempdir()) / "fmu_proj.net"
    if not out.exists():
        return
    txt = out.read_text(encoding="utf-8")
    comps = dict(re.findall(
        r'\(comp\s*\n\s*\(ref "([^"]+)"\)\s*\n\s*\(value "([^"]+)"\)', txt))

    caps = [r for r, v in comps.items() if r.startswith("C")]
    if len(caps) < 20:
        fails.append(f"only {len(caps)} capacitors - the MCU alone has 14 VDD "
                     "pins and each wants its own 100n")

    # Keyed by (ref, pin). Comparing bare reference designators gives false
    # alarms whenever one part sits on both nets - and U10 legitimately has
    # VCAP pins and VDD pins, so a ref-level comparison "proves" VCAP is
    # shorted to +3V3 on a perfectly good schematic. This is the second time
    # that mistake has been made here; compare pins, not parts.
    nets = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            nets[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))

    def refs(net):
        return {r for r, _ in nets.get(net, set())}

    # VCAP is the internal LDO's output - it needs its own capacitors and
    # must not share a node with any supply rail.
    if not {"C18", "C19"} <= refs("VCAP"):
        fails.append("VCAP is missing its 2.2 uF capacitors (C18/C19)")
    for rail in ("+3V3", "+5V", "+3V3A"):
        shared = nets.get("VCAP", set()) & nets.get(rail, set())
        if shared:
            fails.append(f"VCAP shares {sorted(shared)} with {rail} - "
                         "that destroys the internal regulator")

    for term, bus in (("R41", "CAN1_H"), ("R42", "CAN2_H")):
        if term not in refs(bus):
            fails.append(f"{bus} has no terminator - {term} missing")

    for xtal, net in (("X1", "OSC_IN"), ("X2", "OSC32_IN")):
        if xtal not in comps:
            fails.append(f"{xtal} crystal missing")


# Every rail this board generates, and what actually sets its voltage.
# `fixed` parts encode the output in the ordering code; `divider` parts need
# the resistors checked against the part's own feedback reference.
REGULATORS = [
    # ref, part, rail, expected volts, how it is set
    ("U21", "TPS62132", "+3V3",  3.3, ("fixed",)),
    ("U22", "AP2112K-3.3", "+3V3A", 3.3, ("fixed",)),
]

# Parts whose output is set by a divider, and the feedback voltage they
# regulate that divider's tap to. From the part's own datasheet.
FEEDBACK_REF = {
    "TPS62130": 0.800,      # SLVSAG7F table 6-1 / equation 6
    "TPS62130A": 0.800,
}

VOLTAGE_TOLERANCE = 0.05    # 5%: covers 1% resistors and reference spread


# Every supply pin the STM32H753IIT6 has, from the part's own symbol, and the
# rail it must land on. Counts are from MCU_ST_STM32H7:STM32H753IITx.
MCU_SUPPLY = [
    ("+3V3", ["15", "23", "36", "49", "62", "72", "82", "91", "103", "127",
              "136", "149", "159", "172"], "VDD"),
    ("GND",  ["14", "22", "48", "61", "71", "90", "102", "113", "126", "135",
              "148", "158"], "VSS"),
]


# Rails that must never share a node with each other. Shorting any pair is
# not a subtle fault - it is a board that destroys itself at power-up.
DISTINCT_RAILS = ["+5V", "+3V3", "+3V3A", "GND", "VCAP",
                  "+3V3_IMU1", "+3V3_IMU2", "+3V3_IMU3", "+3V3_SENS",
                  "VISO1", "VISO2", "GND_ISO1", "GND_ISO2"]


def check_rails_distinct(fails):
    """Are the supply rails still separate nets?

    Two symbols placed on top of each other, or a row pitch smaller than the
    parts in it, merges everything their pins touch - silently, because the
    result is a perfectly valid schematic that simply describes a different
    circuit. A re-flow of the passives sheet did exactly that here and shorted
    +3V3 to GND across the whole board: one net with 171 pins, and GND with
    none at all.

    Nothing else noticed. ERC was happy - a short is well-formed. The
    footprint and page-fit checks were happy. Even "all MCU supply pins sit on
    their rail" passed for +3V3, because the pins were all on it; they were
    just on GND too.

    So: assert the rails are pairwise disjoint, and that each one still has
    pins. An empty GND is the signature of a merge.
    """
    proj = Path(tempfile.gettempdir()) / "fmu_proj.net"
    if not proj.exists():
        fails.append("project netlist missing - cannot check rail separation")
        return 0
    txt = proj.read_text(encoding="utf-8")
    nets = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            nets[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))

    # A merged rail does not appear as an empty net - it does not appear AT
    # ALL, because KiCad names the surviving net after one of them and the
    # others simply cease to exist. The first version of this check said
    # `for r in DISTINCT_RAILS if r in nets`, so the loudest possible signal -
    # GND gone from a flight controller - was the one case it skipped, and it
    # printed "10 supply rails are separate nets" on a board whose ground was
    # shorted to +3V3. That is the third self-concealing check in this file's
    # history. Absence must be an error, never a skip.
    missing = [r for r in DISTINCT_RAILS if r not in nets]
    if missing:
        fails.append(f"rail(s) absent from the netlist entirely: "
                     f"{', '.join(missing)} - a rail that vanishes has been "
                     f"merged into another net, not deleted")
    present = [r for r in DISTINCT_RAILS if r in nets]
    for r in present:
        if not nets[r]:
            fails.append(f"{r} exists but has no pins")
    # A merge shows up as one rail's pins appearing on another rail's net.
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            both = nets[a] & nets[b]
            if both:
                ex = ", ".join(f"{r}.{p}" for r, p in sorted(both)[:4])
                fails.append(
                    f"{a} and {b} share {len(both)} pin(s) - they are shorted "
                    f"({ex})")
    return len(present)


def check_mcu_power(fails, n):
    """Is every MCU supply pin actually ON its rail, in the netlist?

    Not "is there a wire drawn to it" - the netlist, which is what gets built.
    This check exists because the schematic passed every other check while
    thirteen of fourteen VDD pins were floating.

    The cause is worth keeping: the sheet draws a rail across the fourteen VDD
    stubs, and KiCad does not connect a wire to another wire merely because
    one's endpoint lies on it. A T needs an explicit junction. Without them
    the rail joined only the two pins at the very ends of the wire and ran
    straight past the other fourteen - while plotting as an unmistakably
    connected power rail. It looked right in the PDF, it looked right in the
    editor, and the netlist said otherwise.

    Drawings can lie. Netlists are what the board is made from.
    """
    # The PROJECT netlist, not the sensor sheet's. `nets()` exports
    # sensors.kicad_sch alone, which does not contain U10 at all - so reading
    # it here would report all 26 pins missing on a perfectly good board, and
    # the check would be permanently, uselessly red.
    proj = Path(tempfile.gettempdir()) / "fmu_proj.net"
    if not proj.exists():
        fails.append("project netlist missing - cannot check MCU supply pins")
        return 0
    txt = proj.read_text(encoding="utf-8")
    n = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            n[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))

    for rail, pins, what in MCU_SUPPLY:
        on = {p for r, p in n.get(rail, set()) if r == "U10"}
        missing = sorted(set(pins) - on, key=int)
        if missing:
            fails.append(
                f"U10 has {len(missing)} {what} pin(s) not on {rail}: "
                f"{', '.join(missing)} - floating supply pins")
    return sum(len(p) for _r, p, _w in MCU_SUPPLY)


def check_regulators(fails, comps, n):
    """Does each rail's regulator actually produce the voltage its name claims?

    This check exists because it was missing. U21 was an adjustable TPS62130
    with a 180k/100k feedback divider, carried as "a starting point from the
    datasheet's 3V3 example". The TPS62130 regulates FB to 800 mV, so that
    divider sets 0.8 x (1 + 180/100) = 2.24 V onto a net called +3V3.

    Nothing caught it. ERC checks connectivity, not arithmetic; the net was
    named +3V3 and every part was dutifully connected to it, so every
    structural check passed on a board that would have browned out an
    STM32H753 and undervolted all three IMUs. The error was pure numbers,
    and numbers are what nothing was looking at.

    A rail's name is a claim about its voltage. This makes the claim testable.
    """
    for ref, part, rail, want, how in REGULATORS:
        if ref not in comps:
            fails.append(f"{ref} ({part}) is missing")
            continue
        got = comps[ref]
        if got != part:
            fails.append(f"{ref} is a {got}, but {rail} needs a {part}")
            continue
        if how[0] == "fixed":
            # The part number is the guarantee. Assert it is genuinely a
            # fixed part - an adjustable one here would need a divider.
            if part in FEEDBACK_REF:
                fails.append(
                    f"{ref} is {part}, an ADJUSTABLE part, but is treated as "
                    f"fixed {want} V - it needs a checked feedback divider")
            continue

        vfb = FEEDBACK_REF[part]
        top, bot = how[1], how[2]
        if top not in comps or bot not in comps:
            fails.append(f"{ref}: divider {top}/{bot} missing")
            continue
        try:
            rt, rb = ohms(comps[top]), ohms(comps[bot])
        except ValueError as e:
            fails.append(f"{ref}: {e}")
            continue
        vout = vfb * (1 + rt / rb)
        if abs(vout - want) / want > VOLTAGE_TOLERANCE:
            fails.append(
                f"{ref}: {top}={comps[top]} over {bot}={comps[bot]} sets "
                f"{vout:.2f} V on {rail}, not {want} V "
                f"(Vfb={vfb} V, Vout = Vfb x (1 + Rtop/Rbot))")


def ohms(v):
    """'180k' -> 180000.0. Values are written the way a BOM writes them."""
    m = re.fullmatch(r'([\d.]+)([kKmMrR]?)', v.strip())
    if not m:
        raise ValueError(f"cannot read resistance {v!r}")
    scale = {"": 1, "r": 1, "R": 1, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6}
    return float(m.group(1)) * scale[m.group(2)]


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
    ncross = check_cross_sheet(fails)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"{ncross} nets span sheets - the design is one circuit")

    before = len(fails)
    check_passives(fails)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"decoupling, VCAP caps, crystals and CAN terminators present")

    before = len(fails)
    check_power(fails)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"power tree: 4 independent sensor rails, ORing intact")

    before = len(fails)
    nrails = check_rails_distinct(fails)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"{nrails} supply rails are separate nets")

    before = len(fails)
    nsupply = check_mcu_power(fails, n)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"all {nsupply} MCU supply pins sit on their rail")

    before = len(fails)
    projnet = Path(tempfile.gettempdir()) / "fmu_proj.net"
    comps = dict(re.findall(
        r'\(comp\s*\n\s*\(ref "([^"]+)"\)\s*\n\s*\(value "([^"]+)"\)',
        projnet.read_text(encoding="utf-8"))) if projnet.exists() else {}
    check_regulators(fails, comps, n)
    print(f"  [{'PASS' if len(fails) == before else 'FAIL'}] "
          f"{len(REGULATORS)} rails produce the voltage their name claims")

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
