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
    """A symbol's cache entry, plus its parent if it derives from one.

    Many KiCad symbols are `(extends ...)` a base part - AP2112K-3.3 extends
    AP2204K-1.5, AP22804AW5 extends AP2171W - and carry no geometry of their
    own. Embedding only the derived symbol leaves KiCad with nothing to draw
    and reports lib_symbol_mismatch; embedding only the parent silently
    substitutes the wrong part number. Both are needed.
    """
    s = lib_path.read_text(encoding="utf-8")
    blk = _one_sym(s, name, lib_nick)
    m = re.search(r'\(extends "([^"]+)"', blk)
    if not m:
        return [blk]
    return [_one_sym(s, m.group(1), lib_nick), blk]


def sym_def(lib_path, name, lib_nick):
    """Single-block form, for symbols known not to derive from another."""
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
            r'[\s\S]*?\(name\s+"([^"]+)"', sym_block):
        x, y, ang, name = m.groups()
        out.setdefault(name, (float(x), -float(y), int(ang)))
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
    # Main 3V3. See the note on the sheet about dissipation.
    dict(ref="U21", lib="Regulator_Linear:AP2112K-3.3", val="AP2112K-3.3",
         x=177.8, y=63.5,
         nets={"VIN": "+5V", "VOUT": "+3V3", "GND": "GND", "EN": "+5V",
               "NC": "NC"}),
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
    files = {BOARD / "sensors.kicad_sch": sensors,
             BOARD / "mcu.kicad_sch": mcu,
             BOARD / "power.kicad_sch": power}

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
