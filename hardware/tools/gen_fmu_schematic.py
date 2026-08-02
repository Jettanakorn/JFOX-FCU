#!/usr/bin/env python3
"""Capture the JFOX-FMU v1 schematic.

Generated rather than drawn, for the same reason everything else here is: the
pin assignments come from `plan_pinout.py`'s allocation and the sensor pinouts
from `gen_fmu_symbols.py`'s verified tables, so the schematic cannot quietly
disagree with either.

Sheets:
  sensors   three IMUs on three buses, two barometers, magnetometer, FRAM
  mcu       STM32H753IIT6 with every allocated pin labelled
  power     (next)
  comms     (next)

Inter-sheet nets are **global labels**. That is safe here and was not on the
TMR project: this is one board, so there is no second instance for a global to
short against.

    python hardware/tools/gen_fmu_schematic.py
"""

import re
import subprocess
import sys
import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
KICAD_SYMS = Path(
    r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0\share\kicad\symbols")
PROJECT = "jfox-fmu"
MM = 2.54

sys.path.insert(0, str(Path(__file__).parent))


def uid():
    return str(_uuid.uuid4())


# --------------------------------------------------------------------------
# pulling symbol definitions into a schematic's lib_symbols cache
# --------------------------------------------------------------------------

def sym_defs(lib_path, name, lib_nick):
    """A symbol's schematic cache entry, flattened if it derives from another.

    Many KiCad symbols `(extends ...)` a base part - AP2112K-3.3 extends
    AP2204K-1.5, AP22804AW5 extends AP2171W - and carry no geometry of their
    own. A schematic's lib_symbols cache cannot hold that relationship: the
    parent would have to be cached under its prefixed name while the child
    still refers to it by its bare one, so the reference dangles, KiCad finds
    no pins, and every wire drawn to where the pins should be reports as an
    unconnected endpoint. The geometry was right all along - the cache was
    unresolvable.

    So flatten, the way KiCad itself does when it caches: keep the derived
    symbol's own properties (its part number matters), and graft in the
    parent's graphics and pins.
    """
    s = lib_path.read_text(encoding="utf-8")
    blk = _one_sym(s, name, lib_nick)
    m = re.search(r'\(extends "([^"]+)"', blk)
    if not m:
        return [blk]

    parent = _one_sym(s, m.group(1), lib_nick)
    # The parent's drawing units, renamed to belong to the derived symbol.
    # Indent-agnostic and paren-counted: _one_sym re-indents by a tab, so
    # anything anchored on a fixed depth silently matches nothing.
    units = []
    for um in re.finditer(r'\(symbol "[^"]+_\d+_\d+"', parent):
        depth, j, instr, esc = 0, um.start(), False, False
        while j < len(parent):
            c = parent[j]
            if esc:
                esc = False
            elif c == "\\" and instr:
                esc = True
            elif c == '"':
                instr = not instr
            elif not instr:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        unit = parent[um.start():j + 1]
        units.append(re.sub(r'\(symbol "[^"]+?_(\d+_\d+)"',
                            lambda mm: f'(symbol "{name}_{mm.group(1)}"',
                            unit, count=1))
    if not units:
        raise SystemExit(f"{name}: parent {m.group(1)} has no drawing units")

    out = re.sub(r'\n\s*\(extends "[^"]+"\)', "", blk).rstrip()
    assert out.endswith(")"), "unexpected symbol block layout"
    body = "\n".join("\t\t" + u for u in units)
    return [out[:-1].rstrip() + "\n" + body + "\n\t)"]


def sym_def(lib_path, name, lib_nick):
    """Single-block form; identical now that derived symbols are flattened."""
    return sym_defs(lib_path, name, lib_nick)[-1]


def _one_sym(s, name, lib_nick):
    i = s.index(f'(symbol "{name}"')
    depth, j, instr, esc = 0, i, False, False
    while j < len(s):
        c = s[j]
        if esc:
            esc = False
        elif c == "\\" and instr:
            esc = True
        elif c == '"':
            instr = not instr
        elif not instr:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
        j += 1
    blk = s[i:j + 1]
    blk = blk.replace(f'(symbol "{name}"', f'(symbol "{lib_nick}:{name}"', 1)
    # inner unit symbols keep their bare names; only the outer id is prefixed
    return "\n".join("\t" + ln for ln in blk.splitlines())


# --------------------------------------------------------------------------
# schematic primitives
# --------------------------------------------------------------------------

def eff(justify=None):
    j = f"\n\t\t\t(justify {justify})" if justify else ""
    return f"(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t){j}\n\t\t)"


def glabel(name, shape, x, y, angle=0):
    return (f'\t(global_label "{name}"\n\t\t(shape {shape})\n'
            f'\t\t(at {x} {y} {angle})\n\t\t(fields_autoplaced yes)\n'
            f'\t\t{eff("left")}\n\t\t(uuid "{uid()}")\n\t)')


def wire(x1, y1, x2, y2):
    return (f'\t(wire\n\t\t(pts\n\t\t\t(xy {x1} {y1}) (xy {x2} {y2})\n\t\t)\n'
            f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
            f'\t\t(uuid "{uid()}")\n\t)')


def text(body, x, y, size=1.27):
    return (f'\t(text "{body}"\n\t\t(at {x} {y} 0)\n'
            f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {size} {size})\n\t\t\t)\n'
            f'\t\t\t(justify left top)\n\t\t)\n\t\t(uuid "{uid()}")\n\t)')


def pin_positions(sym_block):
    """{pin name: (dx, dy, angle)} in schematic offsets, from a symbol def.

    Library Y is up, schematic Y is down, so the sign flips. Getting that
    backwards puts every label on the wrong pin while still looking tidy - the
    same trap as the carrier connectors.
    """
    out = {}
    # Whitespace-agnostic: KiCad writes `(at ...)` on its own line, this
    # project's own generator writes it inline. A regex that assumed one
    # layout silently returned zero pins for the other.
    for m in re.finditer(
            r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)'
            r'[\s\S]*?\(name\s+"([^"]*)"', sym_block):
        x, y, ang, name = m.groups()
        out.setdefault(name, (float(x), -float(y), int(ang)))
    return out


def pin_list(sym_block):
    """[(number, name, dx, dy, angle)] - every pin, keyed by nothing.

    `pin_positions` keys by name, which is right for an MCU and wrong for a
    passive: Device:C and Device:R name both pins "~", so a name-keyed dict
    keeps one of them and the other silently never gets wired. That produced
    84 unconnected pins the moment passives were added.
    """
    out = []
    for m in re.finditer(
            r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)'
            r'[\s\S]*?\(name\s+"([^"]*)"[\s\S]*?\(number\s+"([^"]+)"', sym_block):
        x, y, ang, name, num = m.groups()
        out.append((num, name, float(x), -float(y), int(ang)))
    return out


def stub_len(angle):
    """Which way a pin's wire leaves, given the pin's rotation."""
    return {0: (-7.62, 0), 180: (7.62, 0), 90: (0, 7.62), 270: (0, -7.62)}[angle]


def place(lib_id, ref, value, x, y, root_uuid, pins):
    """Place a symbol. `pins` is [(number, dx, dy)] in schematic offsets."""
    out = [f'\t(symbol',
           f'\t\t(lib_id "{lib_id}")',
           f'\t\t(at {x} {y} 0)',
           '\t\t(unit 1)',
           '\t\t(exclude_from_sim no)(in_bom yes)(on_board yes)(dnp no)',
           f'\t\t(uuid "{uid()}")',
           f'\t\t(property "Reference" "{ref}"\n\t\t\t(at {x} {round(y - 12, 2)} 0)\n\t\t\t{eff()}\n\t\t)',
           f'\t\t(property "Value" "{value}"\n\t\t\t(at {x} {round(y + 12, 2)} 0)\n\t\t\t{eff()}\n\t\t)',
           '\t\t(instances',
           f'\t\t\t(project "{PROJECT}"',
           f'\t\t\t\t(path "/{root_uuid}"',
           f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)',
           '\t\t\t\t)\n\t\t\t)\n\t\t)',
           '\t)']
    return "\n".join(out)


def document(root_uuid, libs, body, paper="A3"):
    return ('(kicad_sch\n\t(version 20260306)\n\t(generator "jfox gen_fmu_schematic")\n'
            '\t(generator_version "10.0")\n'
            f'\t(uuid "{root_uuid}")\n\t(paper "{paper}")\n'
            '\t(lib_symbols\n' + "\n".join(libs) + '\n\t)\n'
            + "\n".join(body) + '\n'
            '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n'
            '\t(embedded_fonts no)\n)\n')


# --------------------------------------------------------------------------
# the sensor sheet
# --------------------------------------------------------------------------

# Each IMU on its own bus with its own switchable rail - the FMUv6X
# arrangement. The rail names matter: firmware must drive a bus low before
# dropping its rail (see ARCHITECTURE.md).
SENSORS = [
    dict(ref="U1", lib="jfox-fmu:ICM-42688-P", val="ICM-42688-P",
         bus="SPI2", rail="+3V3_IMU2", x=63.5,
         nets=[("AP_SCLK", "SPI2_SCK"), ("AP_SDI", "SPI2_MOSI"),
               ("AP_SDO", "SPI2_MISO"), ("~{AP_CS}", "IMU2_CS"),
               ("INT1", "IMU2_DRDY"), ("INT2/FSYNC", "GND")]),
    dict(ref="U2", lib="jfox-fmu:ICM-45686", val="ICM-45686",
         bus="SPI6", rail="+3V3_IMU3", x=139.7,
         nets=[("AP_SCLK", "SPI6_SCK"), ("AP_SDI", "SPI6_MOSI"),
               ("AP_SDO", "SPI6_MISO"), ("~{AP_CS}", "IMU3_CS"),
               ("INT1", "IMU3_DRDY"), ("INT2/FSYNC", "GND")]),
    dict(ref="U4", lib="jfox-fmu:BMP388", val="BMP388",
         bus="I2C1", rail="+3V3_SENS", x=215.9,
         nets=[("SCK", "I2C1_SCL"), ("SDI", "I2C1_SDA"),
               ("SDO", "GND"), ("~{CSB}", "+3V3_SENS"),
               ("INT", "BARO1_INT")]),
    dict(ref="U5", lib="jfox-fmu:FM25V02A", val="FM25V02A",
         bus="SPI4", rail="+3V3", x=63.5,
         nets=[("SCK", "SPI4_SCK"), ("SI", "SPI4_MOSI"), ("SO", "SPI4_MISO"),
               ("~{CS}", "FRAM_CS"), ("~{WP}", "+3V3"), ("~{HOLD}", "+3V3")]),
]


def build_sensors():
    ru = uid()
    libs = [sym_def(BOARD / "jfox-fmu.kicad_sym", n, "jfox-fmu")
            for n in ("ICM-42688-P", "ICM-45686", "BMP388", "FM25V02A")]
    libs.append(sym_def(KICAD_SYMS / "Sensor_Motion.kicad_sym", "BMI088",
                        "Sensor_Motion"))
    libs.append(sym_def(KICAD_SYMS / "Sensor_Magnetic.kicad_sym", "BMM150",
                        "Sensor_Magnetic"))

    body = [text(
        "JFOX-FMU v1 - SENSORS\\n"
        "Three IMUs on three separate SPI buses, each on its own switchable rail.\\n"
        "One sensor hanging its bus must not take the other two with it.\\n"
        "\\n"
        "WARNING - before dropping any +3V3_IMUn rail, firmware must drive that\\n"
        "bus's SCK/MOSI/CS low. Interface pins held high with VDDIO off destroy\\n"
        "these parts through their ESD diodes (BMP388 datasheet 3.2).",
        25.4, 20.32, 1.6)]

    # BMI088 shares one bus with two chip selects: accel and gyro are separate
    # SPI devices inside one package, which is why FMUv6X gives it two CS.
    allparts = SENSORS + [dict(
        ref="U3", lib="Sensor_Motion:BMI088", val="BMI088",
        bus="SPI1", rail="+3V3_IMU1", x=139.7,
        nets=[("SCK/SCL", "SPI1_SCK"), ("SDI/SDA", "SPI1_MOSI"),
              ("SDO1", "SPI1_MISO"), ("SDO2", "SPI1_MISO"),
              ("~{CSB1}", "IMU1A_CS"), ("~{CSB2}", "IMU1G_CS"),
              ("INT1", "IMU1A_DRDY"), ("INT3", "IMU1G_DRDY"),
              ("PS", "GND"), ("INT2", "NC"), ("INT4", "NC")])]

    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_positions(lib)

    # power pin names, per part, so rails get wired rather than left floating
    RAILS = {"VDD": "rail", "VDDIO": "rail", "GND": "GND", "VSS": "GND",
             "GNDA": "GND", "GNDIO": "GND", "RESV_GND": "GND"}

    y = 63.5
    for s in allparts:
        px, py = s["x"], y
        body.append(place(s["lib"], s["ref"], s["val"], px, py, ru, s["nets"]))
        pins = geom[s["lib"]]
        wanted = dict(s["nets"])

        for name, (dx, dy, ang) in pins.items():
            net = wanted.get(name)
            if net is None:
                if name in RAILS:
                    net = s["rail"] if RAILS[name] == "rail" else "GND"
                elif name.startswith("RESV"):
                    net = "GND"          # datasheet: no connect OR ground
                else:
                    continue
            if net == "NC":
                continue
            ax, ay = round(px + dx, 2), round(py + dy, 2)
            sx, sy = stub_len(ang)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = ("input" if net.startswith(("+", "GND")) else "bidirectional")
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

        body.append(text(f"{s['ref']}  {s['bus']}  rail {s['rail']}",
                         round(px - 12, 2), round(py - 22, 2), 1.2))
        y += 76.2
        if y > 190:
            y = 63.5

    return ru, document(ru, libs, body, paper="A2")


# MCU pins whose net is fixed by the part rather than by allocation.
MCU_FIXED = {
    "VBAT": "+3V3", "VDDA": "+3V3A", "VREF+": "+3V3A", "VSSA": "GND",
    "VDD33_USB": "+3V3", "VSS": "GND", "PDR_ON": "+3V3",
    "NRST": "NRST", "BOOT0": "BOOT0",
    "PH0": "OSC_IN", "PH1": "OSC_OUT",
    "PC14": "OSC32_IN", "PC15": "OSC32_OUT",
    "PA13": "SWDIO", "PA14": "SWCLK", "PB3": "SWO",
    # VCAP is the internal LDO's output; each needs its own 2.2 uF and they
    # are NOT a supply rail - shorting them to 3V3 destroys the regulator.
    "VCAP": "VCAP",
}


def build_mcu():
    """The STM32H753IIT6, with every allocated pin labelled.

    Net names come straight from plan_pinout's allocation, so this sheet and
    the pin map cannot disagree: `SPI2.SCK` on PA12 becomes the net `SPI2_SCK`
    on pin PA12, and the sensor sheet's `SPI2_SCK` finds it.
    """
    import plan_pinout as PP

    d, table = PP.load()
    assigned, used, problems, gpio = PP.allocate(table)
    if problems:
        print("  pin allocation problems:", *problems, sep="\n    ")

    netof = {pin: f"{periph}_{sig}" for _f, periph, sig, pin, _af in assigned}
    netof.update({pin: net for net, pin in gpio})

    ru = uid()
    lib = sym_def(KICAD_SYMS / "MCU_ST_STM32H7.kicad_sym",
                  "STM32H753IITx", "MCU_ST_STM32H7")
    pins = pin_positions(lib)

    px, py = 190.5, 165.1
    body = [text(
        "JFOX-FMU v1 - MCU\\n"
        "STM32H753IIT6, LQFP176. 1 MB RAM, 2 MB flash, Cortex-M7 @480 MHz.\\n"
        "\\n"
        "Pin assignment is generated from the part's own alternate-function\\n"
        "table - see PINMAP.md. Not hand-written: the previous board's hand-\\n"
        "written map put five of eight PWM channels on top of SPI1 and SPI2.\\n"
        "\\n"
        "VCAP1/VCAP2 are the internal LDO's output. Each needs its own 2.2 uF\\n"
        "close to the pin. They are NOT a supply input - do not tie to +3V3.",
        20.32, 20.32, 1.6)]
    body.append(place("MCU_ST_STM32H7:STM32H753IITx", "U10", "STM32H753IIT6",
                      px, py, ru, []))

    labelled = 0
    for name, (dx, dy, ang) in pins.items():
        net = netof.get(name) or MCU_FIXED.get(name)
        if net is None:
            if name.startswith("VDD"):
                net = "+3V3"
            elif name.startswith("VSS"):
                net = "GND"
            else:
                continue          # unallocated GPIO, left for a later revision
        ax, ay = round(px + dx, 2), round(py + dy, 2)
        sx, sy = stub_len(ang)
        bx, by = round(ax + sx, 2), round(ay + sy, 2)
        body.append(wire(ax, ay, bx, by))
        shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
        body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))
        labelled += 1

    print(f"  MCU: {labelled} of {len(pins)} pins wired")
    return ru, document(ru, [lib], body, paper="A1")


# Power chain. Each entry places one part and names the net on every pin, so
# nothing is left to be inferred from position.
POWER = [
    # Prioritised ORing between the three sources, keeping v2.4.5's best idea.
    # V1/V2/V3 are the inputs in priority order; VS1..3 sense, G1..3 drive the
    # external PMOS pass devices.
    dict(ref="U20", lib="Power_Management:LTC4417CGN", val="LTC4417CGN",
         x=76.2, y=88.9,
         nets={"V1": "VDD_BRICK", "V2": "VDD_SERVO", "V3": "VBUS_USB",
               "VS1": "VDD_BRICK", "VS2": "VDD_SERVO", "VS3": "VBUS_USB",
               "G1": "PGATE1", "G2": "PGATE2", "G3": "PGATE3",
               "VOUT": "+5V", "GND": "GND", "EN": "+5V",
               "~{SHDN}": "+5V", "HYS": "GND", "CAS": "GND",
               "UV1": "UV1_SET", "OV1": "OV1_SET",
               "UV2": "UV2_SET", "OV2": "OV2_SET",
               "UV3": "UV3_SET", "OV3": "OV3_SET",
               "~{VALID1}": "BRICK_VALID", "~{VALID2}": "SERVO_VALID",
               "~{VALID3}": "USB_VALID"}),
    # Main 3V3: a buck, not an LDO. At 5 V in, 3V3 out and the measured load
    # an LDO burns over half a watt - see POWER_BUDGET.md. SW/VOS/FB need the
    # inductor and feedback network, which are not on the sheet yet.
    dict(ref="U21", lib="Regulator_Switching:TPS62130", val="TPS62130",
         x=177.8, y=63.5,
         nets={"VIN": "+5V", "SW": "SW_3V3", "VOS": "+3V3", "FB": "FB_3V3",
               "GND": "GND", "EN": "+5V", "PG": "PG_3V3",
               "FSW": "GND", "DEF": "GND", "SS/TR": "NC"}),
    # Separate quiet rail for VDDA/VREF+, fed from +3V3 so it cannot pull the
    # digital rail around.
    dict(ref="U22", lib="Regulator_Linear:AP2112K-3.3", val="AP2112K-3.3",
         x=177.8, y=114.3,
         nets={"VIN": "+3V3", "VOUT": "+3V3A", "GND": "GND", "EN": "+5V",
               "NC": "NC"}),
]

# One load switch per sensor bus. This is what makes a wedged IMU
# recoverable - and what the firmware must sequence carefully, because
# holding interface pins high with the rail down destroys these parts.
RAIL_SWITCHES = [
    ("U23", "+3V3_IMU1", "EN_3V3_IMU1"),
    ("U24", "+3V3_IMU2", "EN_3V3_IMU2"),
    ("U25", "+3V3_IMU3", "EN_3V3_IMU3"),
    ("U26", "+3V3_SENS", "EN_3V3_SENS"),
]


def build_power():
    ru = uid()
    libs, seen = [], set()
    for p in POWER:
        lib_nick, name = p["lib"].split(":")
        if p["lib"] not in seen:
            seen.add(p["lib"])
            libs += sym_defs(KICAD_SYMS / f"{lib_nick}.kicad_sym", name, lib_nick)
    libs += sym_defs(KICAD_SYMS / "Power_Management.kicad_sym",
                     "AP22804AW5", "Power_Management")

    geom, parent_geom = {}, {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        pp = pin_positions(lib)
        ext = re.search(r'\(extends "([^"]+)"', lib)
        if ext:
            # a derived symbol inherits its parent's pins
            pp = parent_geom.get(f"{m.group(1).split(':')[0]}:{ext.group(1)}", {})
        else:
            parent_geom[m.group(1)] = pp
        geom[m.group(1)] = pp

    body = [text(
        "JFOX-FMU v1 - POWER\\n"
        "\\n"
        "LTC4417 prioritised ORing: brick > servo rail > USB, with under- and\\n"
        "over-voltage lockout per input. This is v2.4.5's arrangement kept,\\n"
        "correctly identified - that board's docs called it a BQ24315 until the\\n"
        "netlist proved otherwise.\\n"
        "\\n"
        "One load switch per sensor bus, so a wedged IMU can be power-cycled\\n"
        "without disturbing the other two.\\n"
        "\\n"
        "WARNING - firmware must drive a bus's SCK/MOSI/CS low BEFORE clearing\\n"
        "its EN_3V3_* line. Interface pins held high with the rail down destroy\\n"
        "these sensors through their ESD diodes (BMP388 datasheet 3.2).\\n"
        "\\n"
        "OPEN: dissipation in U21. At 5V in, 3V3 out and ~500 mA the drop burns\\n"
        "0.85 W, which an SOT-25 will not shed. Either budget the real current\\n"
        "and size the package, or make U21 a buck. Do not fabricate before this\\n"
        "is settled.",
        20.32, 20.32, 1.5)]

    def wire_part(ref, lib_id, val, x, y, nets):
        body.append(place(lib_id, ref, val, x, y, ru, []))
        for name, (dx, dy, ang) in geom[lib_id].items():
            net = nets.get(name)
            if net in (None, "NC"):
                continue
            ax, ay = round(x + dx, 2), round(y + dy, 2)
            sx, sy = stub_len(ang)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    for p in POWER:
        wire_part(p["ref"], p["lib"], p["val"], p["x"], p["y"], p["nets"])

    x = 76.2
    for ref, rail, en in RAIL_SWITCHES:
        wire_part(ref, "Power_Management:AP22804AW5", "AP22804AW5", x, 190.5,
                  {"IN": "+3V3", "OUT": rail, "EN": en, "GND": "GND",
                   "~{FLG}": f"{rail}_FLG"})
        body.append(text(f"{ref}: {rail}", round(x - 10, 2), 168, 1.2))
        x += 50.8

    return ru, document(ru, libs, body, paper="A2")


def two_pin(ref, lib_id, value, x, y, a_net, b_net, root_uuid, geom, vertical=True):
    """Place an R/C/L and wire both ends.

    Uses pin_list, not pin_positions: passives name both pins "~", so a
    name-keyed lookup would wire only one end.
    """
    out = [place(lib_id, ref, value, x, y, root_uuid, [])]
    for _num, _name, dx, dy, ang in geom[lib_id]:
        net = a_net if dy < 0 else b_net
        ax, ay = round(x + dx, 2), round(y + dy, 2)
        sx, sy = stub_len(ang)
        bx, by = round(ax + sx, 2), round(ay + sy, 2)
        out.append(wire(ax, ay, bx, by))
        shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
        out.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))
    return out


def build_passives():
    """The parts a board cannot be built without.

    Decoupling, the LDO's VCAP capacitors, both crystals, the buck's inductor
    and feedback divider, and the CAN terminators - which until now existed
    only as text on the comms sheet, which is to say not at all.

    Kept on its own sheet because it is a long list of small things, and
    burying them among the ICs makes it hard to see whether any are missing.
    """
    ru = uid()
    libs = []
    for nm in ("R", "C", "L", "Crystal_GND24"):
        lib = "Device"
        libs += sym_defs(KICAD_SYMS / f"{lib}.kicad_sym", nm, lib)
    libs += sym_defs(KICAD_SYMS / "power.kicad_sym", "PWR_FLAG", "power")

    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_list(lib)

    body = [text(
        "JFOX-FMU v1 - PASSIVES AND CLOCKS\\n"
        "\\n"
        "Decoupling: one 100n per MCU VDD pin (14), plus 4u7 bulk per rail.\\n"
        "VCAP1/VCAP2 get 2u2 each - these are the internal LDO's output, not a\\n"
        "supply input.\\n"
        "\\n"
        "16 MHz HSE divides exactly to 48 MHz for USB. The old board's 24 MHz\\n"
        "could not, which left its USB clock at 51.4 MHz and forced a second PLL\\n"
        "onto an unverifiable register write.\\n"
        "\\n"
        "CAN terminators are HERE, in series with the jumpers on the comms\\n"
        "sheet. Until now they existed only as a note, which is to say not at\\n"
        "all.",
        20.32, 20.32, 1.5)]

    n = 0
    def add(ref, lib, val, x, y, a, b):
        nonlocal n
        body.extend(two_pin(ref, lib, val, x, y, a, b, ru, geom))
        n += 1

    # MCU decoupling - one per VDD pin, plus bulk
    x, y = 50.8, 76.2
    for i in range(14):
        add(f"C{i+1}", "Device:C", "100n", x, y, "+3V3", "GND")
        x += 15.24
        if x > 240:
            x, y = 50.8, y + 30.48
    add("C15", "Device:C", "4u7", x, y, "+3V3", "GND")
    add("C16", "Device:C", "4u7", x + 15.24, y, "+3V3A", "GND")
    add("C17", "Device:C", "4u7", x + 30.48, y, "+5V", "GND")

    # VCAP - the internal LDO's decoupling
    y += 30.48
    add("C18", "Device:C", "2u2", 50.8, y, "VCAP", "GND")
    add("C19", "Device:C", "2u2", 66.04, y, "VCAP", "GND")
    add("C20", "Device:C", "100n", 81.28, y, "VDDA", "GND")
    add("C21", "Device:C", "1u", 96.52, y, "+3V3A", "GND")

    # Crystals
    body.append(place("Device:Crystal_GND24", "X1", "16MHz", 137.16, y, ru, []))
    body.append(text("X1 16 MHz HSE -> OSC_IN/OSC_OUT, C22/C23 load",
                     121.92, round(y - 20, 2), 1.1))
    add("C22", "Device:C", "12p", 160.02, y, "OSC_IN", "GND")
    add("C23", "Device:C", "12p", 175.26, y, "OSC_OUT", "GND")
    body.append(place("Device:Crystal_GND24", "X2", "32.768kHz", 205.74, y, ru, []))
    add("C24", "Device:C", "6p8", 228.6, y, "OSC32_IN", "GND")
    add("C25", "Device:C", "6p8", 243.84, y, "OSC32_OUT", "GND")

    # Buck: inductor, feedback divider, input and output capacitors
    y += 38.1
    add("L1", "Device:L", "2u2", 50.8, y, "SW_3V3", "+3V3")
    add("C26", "Device:C", "10u", 66.04, y, "+5V", "GND")
    add("C27", "Device:C", "22u", 81.28, y, "+3V3", "GND")
    add("R1", "Device:R", "180k", 96.52, y, "+3V3", "FB_3V3")
    add("R2", "Device:R", "100k", 111.76, y, "FB_3V3", "GND")
    body.append(text(
        "L1/C26/C27 + R1/R2 divider set the TPS62130's output.\\n"
        "Values are a starting point from the datasheet's 3V3 example -\\n"
        "recompute against the final load before fabricating.",
        50.8, round(y - 22, 2), 1.1))

    # CAN terminators, in series with JP1/JP2 on the comms sheet
    y += 30.48
    add("R41", "Device:R", "120", 50.8, y, "CAN1_H", "CAN1_TERM")
    add("R42", "Device:R", "120", 66.04, y, "CAN2_H", "CAN2_TERM")

    # Sensor and transceiver decoupling
    for i, rail in enumerate(("+3V3_IMU1", "+3V3_IMU2", "+3V3_IMU3",
                              "+3V3_SENS")):
        add(f"C{30+i}", "Device:C", "100n", 96.52 + i * 15.24, y, rail, "GND")

    # PWR_FLAG so ERC can see the rails as driven
    y += 30.48
    for i, rail in enumerate(("+5V", "+3V3", "+3V3A", "GND",
                              "VDD_BRICK", "VDD_SERVO", "VBUS_USB")):
        fx = 50.8 + i * 25.4
        body.append(place("power:PWR_FLAG", f"#FLG{i+1}", "PWR_FLAG",
                          fx, y, ru, []))
        for _num, _nm, dx, dy, ang in geom["power:PWR_FLAG"]:
            ax, ay = round(fx + dx, 2), round(y + dy, 2)
            sx, sy = stub_len(ang)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            body.append(glabel(rail, "input", bx, by, 0 if sx < 0 else 180))
    body.append(text("PWR_FLAG marks each rail as driven, so ERC's "
                     "power-pin check means something.",
                     50.8, round(y - 18, 2), 1.1))

    print(f"  passives: {n} two-pin parts, 2 crystals, 7 power flags")
    return ru, document(ru, libs, body, paper="A1")


def build_comms():
    """CAN, USB and the SD card.

    The CAN termination is the point of this sheet. Every PX4FMUv2.4.5 carries
    R409, 120 ohm hard across CAN_H/CAN_L with no way to remove it short of a
    soldering iron, so a three-board bus needs the middle module desoldered -
    a fact recorded across HARDWARE_BRINGUP.md, the carrier silkscreen and the
    TMR checker. Here each bus gets 120 ohm in series with a solder jumper,
    fitted by default. The middle module clears a jumper instead.
    """
    ru = uid()
    libs = []
    libs += sym_defs(KICAD_SYMS / "Interface_CAN_LIN.kicad_sym",
                     "TCAN332", "Interface_CAN_LIN")
    libs += sym_defs(KICAD_SYMS / "Jumper.kicad_sym",
                     "SolderJumper_2_Bridged", "Jumper")
    libs += sym_defs(KICAD_SYMS / "Connector.kicad_sym",
                     "USB_C_Receptacle_USB2.0_14P", "Connector")
    libs += sym_defs(KICAD_SYMS / "Connector.kicad_sym",
                     "SD_Card_Device", "Connector")

    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_positions(lib)

    body = [text(
        "JFOX-FMU v1 - COMMS\\n"
        "\\n"
        "TWO CAN FD BUSES, BOTH WITH TRANSCEIVERS. v2.4.5 wired CAN2 to the MCU\\n"
        "with no transceiver at all, so it was never usable as a bus.\\n"
        "\\n"
        "TERMINATION IS SWITCHABLE. 120 ohm in series with a solder jumper,\\n"
        "FITTED by default. On a three-board TMR chain the electrically middle\\n"
        "module clears JP1 - it does not get R409 desoldered, which is what the\\n"
        "old board required. Verify ~60 ohm across CAN_H/CAN_L, bus unpowered,\\n"
        "before trusting it.",
        20.32, 20.32, 1.5)]

    def wire_part(ref, lib_id, val, x, y, nets):
        body.append(place(lib_id, ref, val, x, y, ru, []))
        for name, (dx, dy, ang) in geom[lib_id].items():
            net = nets.get(name)
            if net in (None, "NC"):
                continue
            ax, ay = round(x + dx, 2), round(y + dy, 2)
            sx, sy = stub_len(ang)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    for i, (ref, bus, y) in enumerate((("U30", "FDCAN1", 76.2),
                                       ("U31", "FDCAN2", 139.7))):
        n = i + 1
        wire_part(ref, "Interface_CAN_LIN:TCAN332", "TCAN332", 76.2, y,
                  {"TXD": f"{bus}_TX", "RXD": f"{bus}_RX",
                   "VCC": "+3V3", "GND": "GND",
                   "CANH": f"CAN{n}_H", "CANL": f"CAN{n}_L"})
        # 120R in series with the jumper, across the pair
        body.append(text(
            f"CAN{n}: R{40+n} 120R + JP{n} (fitted by default)\\n"
            f"clear JP{n} on the middle module of a 3-board chain",
            127.0, round(y - 12, 2), 1.1))
        wire_part(f"JP{n}", "Jumper:SolderJumper_2_Bridged",
                  "SolderJumper_2_Bridged", 190.5, y,
                  {"A": f"CAN{n}_TERM", "B": f"CAN{n}_L"})

    wire_part("J30", "Connector:USB_C_Receptacle_USB2.0_14P", "USB-C",
              76.2, 215.9,
              {"VBUS": "VBUS_USB", "GND": "GND", "CC1": "USB_CC1",
               "CC2": "USB_CC2", "D+": "USB_OTG_FS_DP",
               "D-": "USB_OTG_FS_DM", "SBU1": "NC", "SBU2": "NC",
               "SHIELD": "GND"})

    wire_part("J31", "Connector:SD_Card_Device", "microSD", 215.9, 215.9,
              {"CLK": "SDMMC1_CK", "CMD": "SDMMC1_CMD",
               "DAT0": "SDMMC1_D0", "DAT1": "SDMMC1_D1",
               "DAT2": "SDMMC1_D2", "DAT3/CS": "SDMMC1_D3",
               "VDD": "+3V3", "VSS": "GND", "VSS2": "GND",
               "DET": "SD_DETECT"})

    return ru, document(ru, libs, body, paper="A2")


def sheet_block(name, filename, x, y, root_uuid, page):
    """A hierarchical sheet with no pins: every cross-sheet net here is a
    global label, so the sheets need only be *in* the project, not wired
    through an interface."""
    return "\n".join([
        '\t(sheet',
        f'\t\t(at {x} {y})',
        '\t\t(size 60.96 25.4)',
        '\t\t(fields_autoplaced yes)',
        '\t\t(stroke (width 0.1524)(type solid))',
        '\t\t(fill (color 0 0 0 0.0000))',
        f'\t\t(uuid "{uid()}")',
        f'\t\t(property "Sheetname" "{name}"\n\t\t\t(at {x} {round(y - 0.71, 2)} 0)\n'
        f'\t\t\t(effects (font (size 1.27 1.27))(justify left bottom))\n\t\t)',
        f'\t\t(property "Sheetfile" "{filename}"\n\t\t\t(at {x} {round(y + 26, 2)} 0)\n'
        f'\t\t\t(effects (font (size 1.27 1.27))(justify left top))\n\t\t)',
        '\t\t(instances',
        f'\t\t\t(project "{PROJECT}"',
        f'\t\t\t\t(path "/{root_uuid}"\n\t\t\t\t\t(page "{page}")\n\t\t\t\t)',
        '\t\t\t)\n\t\t)',
        '\t)'])


def build_root():
    """The project root, so the three sheets are one design.

    Until this existed each sheet was a separate project as far as KiCad was
    concerned, so a global label on the power sheet could not reach the MCU
    sheet and ERC reported both ends as isolated. The nets were right; the
    project was not assembled.
    """
    ru = uid()
    body = [text(
        "JFOX-FMU v1\\n"
        "STM32H753IIT6 flight controller - three IMUs, two barometers,\\n"
        "CAN FD with jumpered termination, 1 MB RAM.\\n"
        "\\n"
        "Generated by hardware/tools/gen_fmu_schematic.py - do not hand-edit,\\n"
        "regenerate. Pin assignment comes from the part's own alternate-function\\n"
        "table (PINMAP.md); sensor pinouts from the datasheets (PINOUTS.md).\\n"
        "\\n"
        "Cross-sheet nets are global labels, which is safe here because this is\\n"
        "one board - unlike the 3-board TMR project, where a global would short\\n"
        "all three instances together.",
        25.4, 20.32, 1.6)]
    for i, (nm, fn) in enumerate([("MCU", "mcu.kicad_sch"),
                                  ("SENSORS", "sensors.kicad_sch"),
                                  ("POWER", "power.kicad_sch"),
                                  ("COMMS", "comms.kicad_sch"),
                                  ("PASSIVES", "passives.kicad_sch")]):
        body.append(sheet_block(nm, fn, 38.1, 88.9 + i * 38.1, ru, i + 2))
    return ru, document(ru, [], body)


def build_stub(title, note):
    ru = uid()
    return ru, document(ru, [], [text(title + "\\n\\n" + note, 25.4, 25.4, 1.6)])


def upgrade(paths):
    cli = next((str(c) for c in (
        Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"),
        Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")) if c.exists()), None)
    if not cli:
        return
    for p in paths:
        subprocess.run([cli, "sch", "upgrade", str(p)],
                       capture_output=True, text=True)


def main():
    if not (BOARD / "jfox-fmu.kicad_sym").exists():
        sys.exit("run gen_fmu_symbols.py first")

    _, sensors = build_sensors()
    _, mcu = build_mcu()
    _, power = build_power()
    _, comms = build_comms()
    _, passives = build_passives()
    _, root = build_root()
    files = {BOARD / "comms.kicad_sch": comms,
             BOARD / "passives.kicad_sch": passives,
             BOARD / "sensors.kicad_sch": sensors,
             BOARD / "mcu.kicad_sch": mcu,
             BOARD / "power.kicad_sch": power,
             BOARD / f"{PROJECT}.kicad_sch": root}

    (BOARD / f"{PROJECT}.kicad_pro").write_text(
        '{\n  "meta": {"filename": "jfox-fmu.kicad_pro", "version": 1},\n'
        '  "schematic": {},\n  "sheets": [],\n  "text_variables": {}\n}\n',
        encoding="utf-8")
    (BOARD / "sym-lib-table").write_text(
        '(sym_lib_table\n  (version 7)\n'
        '  (lib (name "jfox-fmu")(type "KiCad")'
        '(uri "${KIPRJMOD}/jfox-fmu.kicad_sym")(options "")'
        '(descr "JFOX-FMU parts with no stock symbol"))\n)\n', encoding="utf-8")

    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    upgrade(list(files))
    for p in files:
        print(f"  wrote {p.relative_to(REPO)} ({p.stat().st_size} bytes)")
    print(f"  wrote {PROJECT}.kicad_pro, sym-lib-table")


if __name__ == "__main__":
    main()
