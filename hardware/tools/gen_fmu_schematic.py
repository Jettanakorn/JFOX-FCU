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
# footprints
# --------------------------------------------------------------------------

# One footprint per part, chosen against the package the datasheet specifies.
# Checked against the installed libraries by check_fmu_footprints.py - a name
# that does not resolve is a board that cannot be laid out, and KiCad reports
# that late and unhelpfully.
FOOTPRINTS = {
    "MCU_ST_STM32H7:STM32H753IITx":
        "Package_QFP:LQFP-176_24x24mm_P0.5mm",

    # Both InvenSense IMUs share one land - their package tables are identical
    # in every dimension that matters. Drawn here, because KiCad ships nothing
    # that fits; see gen_fmu_footprints.py.
    "jfox-fmu:ICM-42688-P": "jfox-fmu:InvenSense_LGA-14_2.5x3mm_P0.5mm",
    "jfox-fmu:ICM-45686":   "jfox-fmu:InvenSense_LGA-14_2.5x3mm_P0.5mm",
    "jfox-fmu:BMP388":      "jfox-fmu:Bosch_LGA-10_2x2mm_P0.5mm_LayoutBorder2x3y",
    # Same body and pin count as the BMP388, entirely different land -
    # three pads top and bottom instead of three left and right.
    "jfox-fmu:ICP-20100":   "jfox-fmu:InvenSense_LGA-10_2x2mm_P0.5mm",
    "Sensor_Magnetic:BMM150": "Package_CSP:WLCSP-12_1.56x1.56mm_P0.4mm",
    "jfox-fmu:FM25V02A":    "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "Sensor_Motion:BMI088":
        "Package_LGA:Bosch_LGA-16_4.5x3mm_P0.5mm_LayoutBorder7x1y_ClockwisePinNumbering",

    # The GN suffix is the 24-lead narrow SSOP, not 16. This was SSOP-16 -
    # eight pads short of the part, which resolves as a name and cannot be
    # built. The datasheet's ordering table lists only I (-40/+85) and H
    # (-40/+125) grades; specify LTC4417IGN or LTC4417HGN when ordering.
    "Power_Management:LTC4417CGN": "Package_SO:SSOP-24_3.9x8.7mm_P0.635mm",
    # RGT is the 3x3 VQFN. TI's land drawing (SLVSAG7F 4222419/E) gives the
    # exposed pad as 1.55 mm; KiCad's 1.6 mm variant is the closest and errs
    # slightly large. Thermal vias, because the datasheet is explicit that the
    # pad must be soldered and that dissipation limits output power.
    "Regulator_Switching:TPS62132":
        "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias",
    "Regulator_Linear:AP2112K-3.3": "Package_TO_SOT_SMD:SOT-23-5",
    "Power_Management:AP22804AW5":  "Package_TO_SOT_SMD:SOT-23-5",
    # DFM0020A is JEDEC MS-013 (datasheet note 5), i.e. a standard wide-body
    # SOIC-20 - the creepage comes from the lead frame, not a wider package.
    "Interface_CAN_LIN:ISOW1044":   "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",

    "Connector:USB_C_Receptacle_USB2.0_14P":
        "Connector_USB:USB_C_Receptacle_GCT_USB4085",
    "Connector:Micro_SD_Card_Det_Hirose_DM3AT":
        "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
    "Jumper:SolderJumper_2_Bridged":
        "Jumper:SolderJumper-2_P1.3mm_Bridged_Pad1.0x1.5mm",

    "Device:Crystal_GND24": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    "Device:R": "Resistor_SMD:R_0402_1005Metric",
    "Device:C": "Capacitor_SMD:C_0402_1005Metric",
    # Generic 1210 land. The 2.2 uH part itself is not chosen yet - saturation
    # current and DCR still have to be picked against the real 550 mA peak -
    # so this is a placeholder land of the right size, not a selected part.
    "Device:L": "Inductor_SMD:L_1210_3225Metric",
    "Device:LED": "LED_SMD:LED_0402_1005Metric",
    "Transistor_FET:Q_PMOS_GSD": "Package_TO_SOT_SMD:SOT-23",

    "power:PWR_FLAG": "",        # virtual - no physical part
}

# Capacitance that will not fit an 0402. Bulk and the buck's output cap need
# the bigger body; assigning every capacitor an 0402 would produce a board
# that cannot be built from the BOM it ships with.
BIG_CAPS = {"4u7", "10u", "22u"}


def footprint(lib_id, ref, value=None):
    fp = FOOTPRINTS.get(lib_id)
    if fp is None:
        raise SystemExit(f"no footprint assigned for {lib_id} ({ref})")
    if lib_id == "Device:C" and value in BIG_CAPS:
        return "Capacitor_SMD:C_0805_2012Metric"
    return fp or None


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


def junction(x, y):
    """An explicit connection dot.

    KiCad does not connect a wire to another wire just because one's endpoint
    lies on the other. Crossings are crossings; a T needs a junction. Drawing
    a rail across fourteen stub ends without these produced a sheet that plots
    as an obviously-connected power rail and whose netlist carried only the
    two pins at the ends of the wire - the other fourteen VDD pins floating on
    a 480 MHz part. It looked right, which is the problem.
    """
    return (f'\t(junction\n\t\t(at {x} {y})\n\t\t(diameter 0)\n'
            f'\t\t(color 0 0 0 0)\n\t\t(uuid "{uid()}")\n\t)')


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


def stub_len(angle, h=7.62, v=7.62):
    """Which way a pin's wire leaves, given the pin's rotation.

    `v` and `h` are separate because the two directions trade against
    different limits. On the MCU sheet the vertical stubs decide whether the
    page fits at all - the symbol's own pins span 231.1 mm and a 7.62 mm stub
    top and bottom pushes that to 246.4 mm against 237 mm of drawable height -
    while the horizontal ones have 90 mm of slack and need the length, because
    at 7.62 mm the net label lands on top of the pin number.
    """
    return {0: (-h, 0), 180: (h, 0), 90: (0, v), 270: (0, -v)}[angle]


def place(lib_id, ref, value, x, y, root_uuid, pins, label_dy=12, fp=None):
    """Place a symbol. `pins` is [(number, dx, dy)] in schematic offsets.

    `label_dy` is how far the reference and value sit above and below the
    origin. The default suits a small part; a tall symbol needs its own value
    or the text lands in the middle of the body. `fp` sets the Footprint
    property - without it the symbol carries whatever its library says, which
    for several parts here is a footprint that does not exist.
    """
    out = [f'\t(symbol',
           f'\t\t(lib_id "{lib_id}")',
           f'\t\t(at {x} {y} 0)',
           '\t\t(unit 1)',
           '\t\t(exclude_from_sim no)(in_bom yes)(on_board yes)(dnp no)',
           f'\t\t(uuid "{uid()}")',
           f'\t\t(property "Reference" "{ref}"\n\t\t\t(at {x} {round(y - label_dy, 2)} 0)\n\t\t\t{eff()}\n\t\t)',
           f'\t\t(property "Value" "{value}"\n\t\t\t(at {x} {round(y + label_dy, 2)} 0)\n\t\t\t{eff()}\n\t\t)']
    if fp is not None:
        out.append(f'\t\t(property "Footprint" "{fp}"\n\t\t\t(at {x} {y} 0)'
                   f'\n\t\t\t(hide yes)\n\t\t\t{eff()}\n\t\t)')
    out += [
           '\t\t(instances',
           f'\t\t\t(project "{PROJECT}"',
           f'\t\t\t\t(path "/{root_uuid}"',
           f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)',
           '\t\t\t\t)\n\t\t\t)\n\t\t)',
           '\t)']
    return "\n".join(out)


# --------------------------------------------------------------------------
# page geometry
# --------------------------------------------------------------------------

COMPANY = "JFOX Aircraft Co., Ltd."
REV = "A"
DATE = "2026-08-03"

# A4 portrait, not landscape, and the reason is not taste. The
# STM32H753IITx symbol is a single unit - KiCad's library gives it only the
# _0_1 body and _1_1 pin sub-symbols, so it cannot be split across pages -
# and its 176 pins span 231.1 mm. A4 landscape leaves about 180 mm of usable
# height, which would cut the MCU in half. Portrait leaves 235 mm, which
# fits it with 4 mm to spare. Every other sheet follows so the set is one
# consistent document.
PAPER, PORTRAIT = "A4", True

# Measured, not assumed: rendered an empty A4 portrait sheet through
# `kicad-cli sch export svg` and read the frame off the output. The drawn
# frame is 12,12 -> 198,285 and the title block occupies x >= 90, y >= 253.
FRAME = (12.0, 12.0, 198.0, 285.0)
TITLE_BLOCK = (90.0, 253.0)
# 2 mm clear of the drawn frame. Not arbitrary-looking but arbitrary-ish: the
# binding constraint is the MCU sheet at 235.1 mm, and 2 mm is the smallest
# round margin that clears it. A larger margin would mean A4 cannot hold this
# part at all, which is a statement about the paper size, not about taste.
MARGIN = 2.0

# Content must live here. The title block takes the bottom right, so the
# usable band stops above it rather than at the frame edge.
SAFE = (FRAME[0] + MARGIN, FRAME[1] + MARGIN,
        FRAME[2] - MARGIN, TITLE_BLOCK[1] - MARGIN)      # 15,15 -> 195,250
SAFE_W = SAFE[2] - SAFE[0]                               # 182 mm
SAFE_H = SAFE[3] - SAFE[1]                               # 237 mm

# KiCad's schematic connection grid. Anything connectable must land on it.
GRID = 1.27


def snap(v):
    return round(round(v / GRID) * GRID, 2)

# Coordinate-bearing s-expressions. Deliberately not a bare number match:
# `(size 1.27 1.27)` and `(offset 1.016)` are lengths, not positions, and
# translating them would rescale the fonts instead of moving the drawing.
_COORD = re.compile(r'\((at|xy) (-?[\d.]+) (-?[\d.]+)')

# A global label is an anchor plus a tag of text that sticks out sideways,
# and the text is usually the larger of the two. Measuring only the anchor
# passed sheets whose right-hand labels ran a centimetre past the frame -
# which the anchor-only check called "inside", because the anchor was.
# 1.27 mm font, ~0.75 mm advance per character in KiCad's stroke font, plus
# the arrow decoration on each end of the tag.
_GLABEL = re.compile(r'\(global_label "([^"]+)"[\s\S]*?\(at '
                     r'(-?[\d.]+) (-?[\d.]+) (\d+)\)')


def label_extent(name, x, y, angle):
    """Where a global label's text actually lands.

    The angle is the direction the label's *connection* faces, not the
    direction the text runs - so the text extends the opposite way. Reading
    it the intuitive way puts every label's estimated extent on the wrong
    side of its anchor, which is worse than not estimating at all: the check
    then reports the sheet as comfortably inside the frame precisely when the
    labels are hanging off the edge of it. That is how the power sheet
    passed while its rightmost label sat 8.6 mm past the border.

    Width calibrated against a rendered sheet: KiCad's stroke font advances
    about 0.86 of the 1.27 mm size per character, plus the tag decoration.
    """
    w = len(name) * 1.27 * 0.9 + 4.0
    if angle == 0:                     # connects rightward, text runs left
        return (x - w, y, x, y)
    if angle == 180:                   # connects leftward, text runs right
        return (x, y, x + w, y)
    if angle == 90:                    # connects upward, text runs down
        return (x, y, x, y + w)
    return (x, y - w, x, y)            # 270


def bbox(body):
    xs, ys = [], []
    blob = "\n".join(body)
    for _kind, x, y in _COORD.findall(blob):
        xs.append(float(x))
        ys.append(float(y))
    for name, x, y, ang in _GLABEL.findall(blob):
        x0, y0, x1, y1 = label_extent(name, float(x), float(y), int(ang))
        xs += [x0, x1]
        ys += [y0, y1]
    return min(xs), min(ys), max(xs), max(ys)


def fit(body, sheet):
    """Translate a sheet's content into the drawable area, or fail loudly.

    Every sheet was previously authored at whatever coordinates were
    convenient, which left all six of them with content at negative x and y -
    outside the page entirely, where KiCad still edits it happily and the
    plotter simply crops it away. Nothing complained, because nothing was
    looking. This looks.

    Translation only. Scaling a schematic is not available: symbol geometry
    is fixed and wires must stay on the 1.27 mm grid, so a sheet that is too
    big has to be re-laid-out, not squeezed. Hence the hard failure - it is a
    design error, and silently cropping it is how the drawing ends up lying
    about the board.
    """
    x0, y0, x1, y1 = bbox(body)
    w, h = x1 - x0, y1 - y0
    if w > SAFE_W or h > SAFE_H:
        raise SystemExit(
            f"{sheet}: content is {w:.1f} x {h:.1f} mm and does not fit the "
            f"{SAFE_W:.0f} x {SAFE_H:.0f} mm drawable area of {PAPER} "
            f"{'portrait' if PORTRAIT else 'landscape'}.\n"
            f"  Re-lay-out the sheet (fewer columns, or split it). "
            f"Scaling is not an option.")
    # Centre horizontally; sit near the top vertically so notes read first.
    # Snapped to the grid, because a translation is not free: KiCad wires
    # connect on a 1.27 mm grid, and shifting a sheet by an arbitrary
    # fraction of a millimetre takes every endpoint off it. Centring the
    # first version of this by (SAFE_W - w) / 2 produced 408 off-grid
    # endpoints - a schematic that plots correctly and that the editor will
    # not reliably let you connect anything to.
    dx = snap(SAFE[0] + (SAFE_W - w) / 2 - x0)
    dy = snap(SAFE[1] - y0)

    def shift(m):
        return (f'({m.group(1)} {round(float(m.group(2)) + dx, 2)} '
                f'{round(float(m.group(3)) + dy, 2)}')
    out = [_COORD.sub(shift, part) for part in body]

    # And having snapped the translation, prove the result is on-grid. A
    # correct shift of an off-grid layout is still off-grid.
    off = set()
    for part in out:
        s = part.lstrip()
        if s.startswith(("(wire", "(global_label", "(symbol")):
            # Only connectable geometry has to land on the grid. A symbol
            # block's FIRST (at ...) is its placement and does; the ones
            # after it are Reference and Value text, which may sit wherever
            # reads best. Checking those too reported the sheet as off-grid
            # because the annotation offset is 12 mm, and 12 is not a
            # multiple of 1.27 - a complaint about nothing electrical.
            found = _COORD.findall(part)
            if s.startswith("(symbol"):
                found = found[:1]
            for _kind, x, y in found:
                for v in (float(x), float(y)):
                    if abs(v / GRID - round(v / GRID)) > 1e-6:
                        off.add(round(v, 3))
    if off:
        raise SystemExit(
            f"{sheet}: {len(off)} coordinate(s) are off the {GRID} mm grid, "
            f"e.g. {sorted(off)[:6]}.\n"
            f"  Placement constants must be multiples of {GRID}.")
    return out


def title_block(title, comments=()):
    o = ['\t(title_block',
         f'\t\t(title "{title}")',
         f'\t\t(date "{DATE}")',
         f'\t\t(rev "{REV}")',
         f'\t\t(company "{COMPANY}")']
    for i, c in enumerate(comments[:9], start=1):
        o.append(f'\t\t(comment {i} "{c}")')
    o.append('\t)')
    return "\n".join(o)


def document(root_uuid, libs, body, title, comments=()):
    paper = f'(paper "{PAPER}"{" portrait" if PORTRAIT else ""})'
    return ('(kicad_sch\n\t(version 20260306)\n\t(generator "jfox gen_fmu_schematic")\n'
            '\t(generator_version "10.0")\n'
            f'\t(uuid "{root_uuid}")\n\t{paper}\n'
            + title_block(title, comments) + '\n'
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
    # Second barometer, second vendor - ARCHITECTURE.md's whole reason for
    # having two. Strapping from DS-000416 rev 1.3 figure 10 (the I2C typical
    # operating circuit): CSB to VDDIO selects I2C, AD0 low gives 0x63, and
    # both RESV pins go to ground.
    dict(ref="U7", lib="jfox-fmu:ICP-20100", val="ICP-20100",
         bus="I2C1", rail="+3V3_SENS",
         nets=[("SCL", "I2C1_SCL"), ("SDA/SDIO/SDI", "I2C1_SDA"),
               ("SDO/AD0", "GND"), ("~{CSB}", "+3V3_SENS"),
               ("INT", "BARO2_INT"), ("RESV", "GND")]),
    # Magnetometer. Strapping from BST-BMM150-DS001-05 rev 1.4 table 32 and
    # section 4.1: PS to VDDIO for reliable I2C protocol selection, CSB and
    # SDO both low for the default address 0x10. That address does not
    # collide with the BMP388's 0x76 or the ICP-20100's 0x63.
    dict(ref="U6", lib="Sensor_Magnetic:BMM150", val="BMM150",
         bus="I2C1", rail="+3V3_SENS",
         nets=[("SCK", "I2C1_SCL"), ("SDI", "I2C1_SDA"),
               ("SDO", "GND"), ("~{CSB}", "GND"), ("PS", "+3V3_SENS"),
               ("DRDY", "MAG_DRDY"), ("INT", "NC")]),
    dict(ref="U5", lib="jfox-fmu:FM25V02A", val="FM25V02A",
         bus="SPI4", rail="+3V3", x=63.5,
         nets=[("SCK", "SPI4_SCK"), ("SI", "SPI4_MOSI"), ("SO", "SPI4_MISO"),
               ("~{CS}", "FRAM_CS"), ("~{WP}", "+3V3"), ("~{HOLD}", "+3V3")]),
]


def build_sensors():
    ru = uid()
    libs = [sym_def(BOARD / "jfox-fmu.kicad_sym", n, "jfox-fmu")
            for n in ("ICM-42688-P", "ICM-45686", "BMP388", "ICP-20100",
                      "FM25V02A")]
    libs.append(sym_def(KICAD_SYMS / "Sensor_Motion.kicad_sym", "BMI088",
                        "Sensor_Motion"))
    libs.append(sym_def(KICAD_SYMS / "Sensor_Magnetic.kicad_sym", "BMM150",
                        "Sensor_Magnetic"))

    body = [text(
        "Three IMUs on three separate SPI buses, each on its own switchable\\n"
        "rail. One sensor hanging its bus must not take the other two with it.\\n"
        "\\n"
        "WARNING - before dropping any +3V3_IMUn rail, firmware must drive that\\n"
        "bus's SCK/MOSI/CS low. Interface pins held high with VDDIO off destroy\\n"
        "these parts through their ESD diodes (BMP388 datasheet 3.2).",
        0, 0, 1.4)]

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

    # Two columns, not three. Each part needs its symbol plus a label on both
    # sides, about 80 mm, and A4 portrait gives 180 mm of width.
    for i, s in enumerate(allparts):
        px = 45.72 + (i % 2) * 88.9
        py = 45.72 + (i // 2) * 55.88
        body.append(place(s["lib"], s["ref"], s["val"], px, py, ru, s["nets"],
                          fp=footprint(s["lib"], s["ref"])))
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
            sx, sy = stub_len(ang, v=3.81)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = ("input" if net.startswith(("+", "GND")) else "bidirectional")
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

        body.append(text(f"{s['ref']}  {s['bus']}  rail {s['rail']}",
                         round(px - 12, 2), round(py - 20.32, 2), 1.2))

    return ru, document(ru, libs, fit(body, "sensors"), "Sensors", (
        "Three IMUs, three separate SPI buses, three switchable rails",
        "Drive a bus low BEFORE dropping its rail - see ARCHITECTURE.md"))


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

    # This sheet carries the symbol and nothing else. The part's 176 pins span
    # 231.1 mm of the 235 mm drawable height, so there is no room for a note
    # block - it lives in the title block and in PINMAP.md instead.
    px, py = 99.06, 124.46
    body = [place("MCU_ST_STM32H7:STM32H753IITx", "U10", "STM32H753IIT6",
                  px, py, ru, [], label_dy=116.84,
                  fp=footprint("MCU_ST_STM32H7:STM32H753IITx", "U10"))]

    # Every PHYSICAL pin, not every pin NAME. pin_positions keys by name, and
    # this part puts 14 pins on VDD, 12 on VSS and 2 on VCAP - so a name-keyed
    # walk wires exactly one of each and silently drops the other 25. The
    # rendered sheet showed it plainly: sixteen power pins along the top edge
    # and a single +3V3 label. This is the third appearance of the same
    # mistake (passives, the power check, here). Key by pin, always.
    allpins = pin_list(lib)
    entries = []
    for num, name, dx, dy, ang in allpins:
        # On this package PC2 and PC3 exist only as PC2_C / PC3_C - the
        # analog-switch-capable balls. The allocator works from the chip's AF
        # table, which calls them PC2 and PC3, so without this alias the pin
        # simply never matched and its signal silently went nowhere.
        alias = name[:-2] if name.endswith("_C") else name
        net = (netof.get(name) or MCU_FIXED.get(name)
               or netof.get(alias) or MCU_FIXED.get(alias))
        if net is None:
            if name.startswith("VDD"):
                net = "+3V3"
            elif name.startswith("VSS"):
                net = "GND"
            else:
                continue          # unallocated GPIO, left for a later revision
        entries.append((net, num, dx, dy, ang))

    # Pins sharing a net along one edge get a rail: stub each pin, join the
    # stub ends, label the rail once. Sixteen individual +3V3 labels stacked
    # along the top edge would overlap into an unreadable smear, and the rail
    # is what a schematic drawn by hand would show anyway.
    groups = {}
    for net, num, dx, dy, ang in entries:
        groups.setdefault((net, ang), []).append((num, dx, dy))

    labelled = 0
    for (net, ang), members in groups.items():
        shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
        ends = []
        for _num, dx, dy in members:
            ax, ay = round(px + dx, 2), round(py + dy, 2)
            sx, sy = stub_len(ang, h=12.7, v=1.27)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            ends.append((bx, by))
            labelled += 1
        if len(ends) == 1:
            bx, by = ends[0]
            # Vertical pins point their label away from the symbol so it does
            # not lie across the rail running beside it.
            angle = (0 if ang in (90, 270) else (0 if ang == 0 else 180))
            body.append(glabel(net, shape, bx, by, angle))
        else:
            ends.sort()
            (x0, y0), (x1, y1) = ends[0], ends[-1]
            body.append(wire(x0, y0, x1, y1))
            # Every tap between the two ends needs a junction, or the rail
            # runs past it without connecting. The endpoints do not: a wire
            # meeting a wire end-to-end joins on its own.
            for bx, by in ends[1:-1]:
                body.append(junction(bx, by))
            body.append(glabel(net, shape, x0, y0, 180 if ang in (90, 270)
                               else (0 if ang == 0 else 180)))

    print(f"  MCU: {labelled} of {len(pins)} pins wired")
    return ru, document(ru, [lib], fit(body, "mcu"), "MCU", (
        "STM32H753IIT6 LQFP176 - 1 MB RAM, 2 MB flash, Cortex-M7 480 MHz",
        "Pins allocated from the part's own AF table - see PINMAP.md",
        "VCAP1/VCAP2 are the internal LDO output. NOT a supply - do not tie to +3V3"))


# Power chain. Each entry places one part and names the net on every pin, so
# nothing is left to be inferred from position.
POWER = [
    # Prioritised ORing between the three sources, keeping v2.4.5's best idea.
    # V1/V2/V3 are the inputs in priority order; VS1..3 sense, G1..3 drive the
    # external PMOS pass devices.
    # U20 (LTC4417) and its six pass FETs have moved to the backplane. The
    # card does not meet the airframe supply any more - it receives an
    # already-ORed, already-fused +5V_CARRIER on three of its gold fingers,
    # and the only power part it still needs is the buck that makes its own
    # core rail.
    dict(ref="U21", lib="Regulator_Switching:TPS62132", val="TPS62132",
         x=125.73, y=69.85,
         nets={"VIN": "+5V", "SW": "SW_3V3", "VOS": "+3V3", "FB": "GND",
               "GND": "GND", "EN": "+5V", "PG": "PG_3V3",
               "FSW": "GND", "DEF": "GND", "SS/TR": "SS_3V3"}),
    # Separate quiet rail for VDDA/VREF+, fed from +3V3 so it cannot pull the
    # digital rail around.
    dict(ref="U22", lib="Regulator_Linear:AP2112K-3.3", val="AP2112K-3.3",
         x=125.73, y=125.73,
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



# --------------------------------------------------------------------------
# LTC4417 pass devices and threshold dividers
# --------------------------------------------------------------------------

# Two back-to-back PMOS per input, sources common, gates both driven from Gn.
# That is what "blocks reverse AND cross conduction" means on the front page of
# the datasheet: one FET's body diode faces each way, so neither an input above
# the output nor an output above an input can push current the wrong way. One
# FET per channel would leave a permanent diode path.
#
# VSn senses the common source node - NOT the input. The design had VS1..VS3
# wired straight to the input rails, which measures the wrong side of a switch
# that did not exist.
#
# Divider per input, from ADI's Figure 1: top resistor from the input to UVn,
# middle from UVn to OVn, bottom from OVn to ground. Both comparators trip at
# 1 V, so with Rtot = Rtop + Rmid + Rbot:
#
#     UV threshold = Rtot / (Rmid + Rbot)
#     OV threshold = Rtot / Rbot
#
# Those equations reproduce the datasheet's own example - 806k/39.2k/60.4k
# gives 9.09 V and 14.99 V on a 12 V adapter, which is what Figure 1 shows.
#
# (channel, input net, Rtop, Rmid, Rbot, UV, OV, why)
ORING = [
    (1, "VDD_BRICK", "787k", "49k9", "174k", 4.52, 5.81,
     "Pixhawk power module, nominally 5.0-5.4 V"),
    (2, "VDD_SERVO", "787k", "68k1", "154k", 4.54, 6.55,
     "servo BECs are commonly 5 V or 6 V, so the window has to hold both"),
    (3, "VBUS_USB", "768k", "45k3", "182k", 4.38, 5.47,
     "USB VBUS is 4.75-5.25 V; a tighter window than the other two"),
]


def build_oring(body, ru, geom_fet, place_fn):
    """Pass FETs, dividers and bypass caps for all three ORing inputs."""
    out = []
    for i, (n, src, rtop, rmid, rbot, _uv, _ov, _why) in enumerate(ORING):
        x = 30.48 + i * 50.8
        y = 195.58
        vs = "VS%d_ORING" % n
        gate = "PGATE%d" % n
        # Input-side FET: drain on the supply, source on the common node.
        for k, (ref, drain) in enumerate(((f"Q{n}A", src), (f"Q{n}B", "+5V"))):
            qx = x + k * 22.86
            out.append(place_fn("Transistor_FET:Q_PMOS_GSD", ref, "PMOS",
                                qx, y, ru, [], label_dy=11.43,
                                fp="Package_TO_SOT_SMD:SOT-23"))
            for num, nm, dx, dy, ang in geom_fet:
                net = {"G": gate, "S": vs, "D": drain}[nm]
                ax, ay = round(qx + dx, 2), round(y + dy, 2)
                sx, sy = stub_len(ang, h=5.08, v=3.81)
                bx, by = round(ax + sx, 2), round(ay + sy, 2)
                out.append(wire(ax, ay, bx, by))
                shape = ("input" if net.startswith(("+", "GND", "VDD", "VBUS"))
                         else "bidirectional")
                out.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))
    body.extend(out)


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
    libs += sym_defs(KICAD_SYMS / "Transistor_FET.kicad_sym",
                     "Q_PMOS_GSD", "Transistor_FET")

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
        "LTC4417 prioritised ORing: brick > servo rail > USB, with under- and\\n"
        "over-voltage lockout per input. This is v2.4.5's arrangement kept,\\n"
        "correctly identified - that board's docs called it a BQ24315 until the\\n"
        "netlist proved otherwise.\\n"
        "\\n"
        "U21 is a BUCK, not an LDO. At 5V in, 3V3 out and the measured ~310 mA\\n"
        "typical load an LDO burns 0.53 W, and 0.94 W at peak, which an SOT-23-5\\n"
        "cannot shed - see POWER_BUDGET.md. U22 stays an LDO because it carries\\n"
        "only VDDA/VREF+, a few mA, and its quietness is the point.\\n"
        "\\n"
        "One load switch per sensor bus, so a wedged IMU can be power-cycled\\n"
        "without disturbing the other two.\\n"
        "\\n"
        "WARNING - firmware must drive a bus's SCK/MOSI/CS low BEFORE clearing\\n"
        "its EN_3V3_* line. Interface pins held high with the rail down destroy\\n"
        "these sensors through their ESD diodes (BMP388 datasheet 3.2).",
        0, 0, 1.4)]

    def wire_part(ref, lib_id, val, x, y, nets):
        body.append(place(lib_id, ref, val, x, y, ru, [],
                          fp=footprint(lib_id, ref)))
        for name, (dx, dy, ang) in geom[lib_id].items():
            net = nets.get(name)
            if net in (None, "NC"):
                continue
            ax, ay = round(x + dx, 2), round(y + dy, 2)
            sx, sy = stub_len(ang, v=3.81)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    for p in POWER:
        wire_part(p["ref"], p["lib"], p["val"], p["x"], p["y"], p["nets"])

    # Two columns of load switches rather than one row of four: a row spans
    # 203 mm and the drawable width is 180.
    FLG_NET = {"+3V3_IMU1": "IMU1_RAIL_FLG", "+3V3_IMU2": "IMU2_RAIL_FLG",
               "+3V3_IMU3": "IMU3_RAIL_FLG", "+3V3_SENS": "SENS_RAIL_FLG"}
    for i, (ref, rail, en) in enumerate(RAIL_SWITCHES):
        flg = FLG_NET[rail]
        sx = 62.23 + (i % 2) * 78.74
        sy = 175.26 + (i // 2) * 44.45
        wire_part(ref, "Power_Management:AP22804AW5", "AP22804AW5", sx, sy,
                  {"IN": "+3V3", "OUT": rail, "EN": en, "GND": "GND",
                   "~{FLG}": flg})
        body.append(text(f"{ref}: {rail}", round(sx - 10, 2),
                         round(sy - 16.51, 2), 1.2))

    # Dividers and sense capacitors live here, next to U20, not on the
    # passives sheet: they are part of the ORing network, and the passives
    # sheet had also simply run out of A4.
    dgeom = {}
    for nm in ("R", "C"):
        dl = sym_defs(KICAD_SYMS / "Device.kicad_sym", nm, "Device")[-1]
        dgeom["Device:" + nm] = pin_list(dl)
        if not any('"Device:%s"' % nm in L for L in libs):
            libs.append(dl)
    dparts = []
    for i, (n, src, rtop, rmid, rbot, _uv, _ov, _why) in enumerate(ORING):
        b = 20 + i * 3
        dparts += [("R%d" % b, rtop, src, "UV%d_SET" % n),
                   ("R%d" % (b + 1), rmid, "UV%d_SET" % n, "OV%d_SET" % n),
                   ("R%d" % (b + 2), rbot, "OV%d_SET" % n, "GND")]
    # The ORing threshold dividers and sense caps moved to the backplane
    # with U20. They set the under- and over-voltage windows the controller
    # compares against, so they are only meaningful next to it - left here
    # they drove VS1..VS3_ORING, three nets with nothing on the far end.
    _ = dparts

    _ = (lambda *a: None)(pin_list(
        sym_defs(KICAD_SYMS / "Transistor_FET.kicad_sym",
                 "Q_PMOS_GSD", "Transistor_FET")[-1]), place)

    return ru, document(ru, libs, fit(body, "power"), "Power", (
        "LTC4417 prioritised ORing: brick > servo > USB",
        "U21 is a buck (POWER_BUDGET.md); U22 is an LDO for the analog rail",
        "One switchable rail per sensor bus"))


def two_pin(ref, lib_id, value, x, y, a_net, b_net, root_uuid, geom, vertical=True):
    """Place an R/C/L and wire both ends.

    Uses pin_list, not pin_positions: passives name both pins "~", so a
    name-keyed lookup would wire only one end.
    """
    out = [place(lib_id, ref, value, x, y, root_uuid, [],
                 fp=footprint(lib_id, ref, value))]
    # Split the two pins along whichever axis actually separates them.
    # Deciding on dy alone assumes a vertically drawn part: Device:LED is
    # horizontal, both its pins sit at dy = 0, so both took b_net and the LED
    # shorted its own anode to its cathode while the anode net kept only the
    # series resistor. It looked wired and was a short.
    pins = geom[lib_id]
    vertical = len({round(p[3], 3) for p in pins}) > 1
    for _num, _name, dx, dy, ang in pins:
        first = (dy < 0) if vertical else (dx < 0)
        net = a_net if first else b_net
        ax, ay = round(x + dx, 2), round(y + dy, 2)
        # Short vertical stubs. A two-pin part is stacked vertically and its
        # stubs are pure page height - 52 of them at the default 7.62 mm push
        # the passives sheet off A4 on their own, and nothing is gained by the
        # extra length because both labels are short rail names.
        sx, sy = stub_len(ang, v=3.81)
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
    for nm in ("R", "C", "L", "LED", "Crystal_GND24"):
        lib = "Device"
        libs += sym_defs(KICAD_SYMS / f"{lib}.kicad_sym", nm, lib)
    libs += sym_defs(KICAD_SYMS / "power.kicad_sym", "PWR_FLAG", "power")

    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_list(lib)

    body = [text(
        "Decoupling: one 100n per MCU VDD pin (14), plus 4u7 bulk per rail.\\n"
        "VCAP1/VCAP2 get 2u2 each - the internal LDO's output, not a supply.\\n"
        "\\n"
        "16 MHz HSE divides exactly to 48 MHz for USB. The old board's 24 MHz\\n"
        "could not, which left its USB clock at 51.4 MHz.\\n"
        "\\n"
        "CAN terminators are HERE, in series with the comms-sheet jumpers.",
        0, 0, 1.4)]

    n = 0
    # Ten columns at 15.24 mm is 137 mm, inside the 180 mm drawable width.
    # The old layout stepped until x > 240, which put the last capacitor of
    # every row about 60 mm off the right-hand edge of any page this design
    # was ever going to be printed on.
    COLS, DX, DY = 12, 13.97, 19.05

    def row(y, items):
        """Place a row of two-pin parts, wrapping at COLS."""
        nonlocal n
        for i, (ref, lib, val, a, b) in enumerate(items):
            body.extend(two_pin(ref, lib, val, (i % COLS) * DX,
                                y + (i // COLS) * DY, a, b, ru, geom))
            n += 1
        return y + ((len(items) - 1) // COLS + 1) * DY

    y = 40.64
    # MCU decoupling - one per VDD pin, plus bulk per rail
    y = row(y, [(f"C{i+1}", "Device:C", "100n", "+3V3", "GND")
                for i in range(14)]
             + [("C15", "Device:C", "4u7", "+3V3", "GND"),
                ("C16", "Device:C", "4u7", "+3V3A", "GND"),
                ("C17", "Device:C", "4u7", "+5V", "GND")])

    # VCAP, analog rail, and the sensor/transceiver decoupling
    y = row(y, [("C18", "Device:C", "2u2", "VCAP", "GND"),
                ("C19", "Device:C", "2u2", "VCAP", "GND"),
                # The MCU's VDDA pin is on +3V3A (MCU_FIXED). This capacitor was
                # on a net called "VDDA" that nothing else joined, so it
                # decoupled nothing at all.
                ("C20", "Device:C", "100n", "+3V3A", "GND"),
                ("C21", "Device:C", "1u", "+3V3A", "GND"),
                ("C30", "Device:C", "100n", "+3V3_IMU1", "GND"),
                ("C31", "Device:C", "100n", "+3V3_IMU2", "GND"),
                ("C32", "Device:C", "100n", "+3V3_IMU3", "GND"),
                ("C33", "Device:C", "100n", "+3V3_SENS", "GND")])

    # Buck network and the CAN terminators
    y = row(y, [("L1", "Device:L", "2u2", "SW_3V3", "+3V3"),
                ("C26", "Device:C", "10u", "+5V", "GND"),
                ("C27", "Device:C", "22u", "+3V3", "GND"),
                # No feedback divider - U21 is the fixed 3.3 V TPS62132.
                # C28 is the AVIN bypass and C29 the soft-start capacitor,
                # both from the datasheet's own typical application (figure
                # 9-1); R3 pulls up PG, which is open drain and was
                # previously wired to a net nothing could ever drive.
                ("C28", "Device:C", "100n", "+5V", "GND"),
                # NRST and BOOT0 had no circuit at all - both were inputs
                # with nothing driving them. NRST carries an internal
                # 30-50k pull-up (DM00388325 s6.3.16 table 54), so it needs
                # only the external capacitor of figure 22 "Recommended
                # NRST pin protection". BOOT0 has no internal pull and must
                # be held low, or the part may boot the system bootloader
                # instead of flash on a marginal power-up.
                ("C34", "Device:C", "100n", "NRST", "GND"),
                ("R6", "Device:R", "10k", "BOOT0", "GND"),
                ("C29", "Device:C", "3n3", "SS_3V3", "GND"),
                ("R3", "Device:R", "100k", "+3V3", "PG_3V3"),
                # ISOW1044 bypassing, SLLSFF7A s10.3: 10u + 1u + 10n on BOTH
                # the VDD side and the isolated VISO side, per transceiver.
                # The 10n must sit within 1 mm of the pin for the radiated
                # emissions figure to mean anything - a layout constraint, not
                # just a BOM line.
                ("C35", "Device:C", "10u",  "+5V", "GND"),
                ("C36", "Device:C", "1u",   "+5V", "GND"),
                ("C37", "Device:C", "10n",  "+5V", "GND"),
                ("C38", "Device:C", "10u",  "VISO1", "GND_ISO1"),
                ("C39", "Device:C", "1u",   "VISO1", "GND_ISO1"),
                ("C40", "Device:C", "10n",  "VISO1", "GND_ISO1"),
                ("C41", "Device:C", "10u",  "VISO2", "GND_ISO2"),
                ("C42", "Device:C", "1u",   "VISO2", "GND_ISO2"),
                ("C43", "Device:C", "10n",  "VISO2", "GND_ISO2"),
                # EN/FLT is used as the fault output, which needs >=5k to VIO.
                # Worth having: it is how firmware learns an isolated supply
                # has failed, and a redundant link whose failure is silent is
                # not redundant.
                ("R7", "Device:R", "10k", "+3V3", "CAN1_FLT"),
                ("R8", "Device:R", "10k", "+3V3", "CAN2_FLT"),
                # USB-C sink termination. Without 5.1k on each CC pin the
                # port is not a sink and a host will never enumerate it - the
                # CC pins reached the connector and nothing else.
                ("R9",  "Device:R", "5k1", "USB_CC1", "GND"),
                ("R10", "Device:R", "5k1", "USB_CC2", "GND"),
                # VBUS sense divider. VBUS_SENSE reached an ADC pin with
                # nothing driving it; 10k/10k puts 5.25 V at 2.63 V, inside
                # the 3.3 V reference with margin.
                ("R11", "Device:R", "10k", "VBUS_USB", "VBUS_SENSE"),
                ("R12", "Device:R", "10k", "VBUS_SENSE", "GND"),
                # Load-switch fault outputs are open drain and need pull-ups
                # to be readable at all.
                # Status LEDs. LED_R/G/B were allocated MCU pins and drove
                # nothing; the board had no way to say anything. Common anode
                # so the MCU sinks, 1k for ~1.5 mA per colour.
                # SD bus pull-ups. The SD specification requires CMD and
                # DAT0-3 pulled high; DAT3 doubles as the card's own detect
                # pin, so it must not float during initialisation. The STM32
                # has internal pull-ups but they are weak and only enabled
                # after GPIO configuration, which is after the card has
                # already sampled the bus.
                ("R30", "Device:R", "10k", "+3V3", "SDMMC1_CMD"),
                ("R31", "Device:R", "10k", "+3V3", "SDMMC1_D0"),
                ("R32", "Device:R", "10k", "+3V3", "SDMMC1_D1"),
                ("R33", "Device:R", "10k", "+3V3", "SDMMC1_D2"),
                ("R34", "Device:R", "10k", "+3V3", "SDMMC1_D3"),
                ("R35", "Device:R", "10k", "+3V3", "SD_DETECT"),
                ("R17", "Device:R", "1k", "+3V3", "LED_R_A"),
                ("R18", "Device:R", "1k", "+3V3", "LED_G_A"),
                ("R19", "Device:R", "1k", "+3V3", "LED_B_A"),
                # Power lamp: cathode to GND, not to an MCU pin, so
                # it lights on rail-up with no firmware running. A
                # power lamp the MCU drives tells you the MCU is
                # alive, which is not what anyone reads it for.
                ("D1", "Device:LED", "PWR-GRN", "LED_R_A", "GND"),
                ("D2", "Device:LED", "HB-BLU", "LED_G_A", "LED_G"),
                ("D3", "Device:LED", "BLU", "LED_B_A", "LED_B"),
                ("R13", "Device:R", "10k", "+3V3", "IMU1_RAIL_FLG"),
                ("R14", "Device:R", "10k", "+3V3", "IMU2_RAIL_FLG"),
                ("R15", "Device:R", "10k", "+3V3", "IMU3_RAIL_FLG"),
                ("R16", "Device:R", "10k", "+3V3", "SENS_RAIL_FLG"),
                # I2C1 is open drain and has no other pull-up. Both the
                # ICP-20100 (DS-000416 fig 10 note) and the BMM150
                # (BST-BMM150 s6.2) say so outright; without these the
                # bus never leaves the low state and no sensor answers.
                ("R4", "Device:R", "4k7", "+3V3_SENS", "I2C1_SCL"),
                ("R5", "Device:R", "4k7", "+3V3_SENS", "I2C1_SDA"),
                ("R41", "Device:R", "120", "CAN1_H", "CAN1_TERM"),
                ("R42", "Device:R", "120", "CAN2_H", "CAN2_TERM")])
    body.append(text(
        "L1 2u2 + C27 22u is the TPS6213x datasheet's own recommended "
        "standard LC filter (table 9-2). Output is fixed by the part.",
        0, round(y - DY - 20.32, 2), 1.1))

    # Crystals with their load capacitors, each beside its own crystal
    body.append(place("Device:Crystal_GND24", "X1", "16MHz", 7 * DX, y, ru, [],
                      fp=footprint("Device:Crystal_GND24", "X1")))
    y2 = row(y, [("C22", "Device:C", "12p", "OSC_IN", "GND"),
                 ("C23", "Device:C", "12p", "OSC_OUT", "GND")])
    body.append(place("Device:Crystal_GND24", "X2", "32.768kHz", 9 * DX, y,
                      ru, [], fp=footprint("Device:Crystal_GND24", "X2")))
    for i, (ref, net) in enumerate((("C24", "OSC32_IN"), ("C25", "OSC32_OUT"))):
        body.extend(two_pin(ref, "Device:C", "6p8", (4 + i) * DX, y,
                            net, "GND", ru, geom))
        n += 1
    body.append(text("X1 16 MHz HSE.   X2 32.768 kHz LSE.",
                     0, round(y - 17.78, 2), 1.1))
    y = y2
    yflag = y

    # PWR_FLAG so ERC can see the rails as driven
    FLAG_COLS = 7          # 9 flags in one row spans 203 mm; the page is 182
    # VDD_BRICK, VDD_SERVO and VBUS_USB left with the ORing controller - the
    # card no longer sees any of the three airframe sources. What arrives on
    # the gold fingers is +5V_CARRIER, already selected and already fused, so
    # that is the rail ERC has to be told is driven.
    for i, rail in enumerate(("+5V", "+5V_CARRIER", "+3V3", "+3V3A", "GND",
                              "GND_ISO1", "GND_ISO2")):
        fx = (i % FLAG_COLS) * 25.4
        y = yflag + (i // FLAG_COLS) * DY
        body.append(place("power:PWR_FLAG", f"#FLG{i+1}", "PWR_FLAG",
                          fx, y, ru, []))
        for _num, _nm, dx, dy, ang in geom["power:PWR_FLAG"]:
            ax, ay = round(fx + dx, 2), round(y + dy, 2)
            sx, sy = stub_len(ang, v=3.81)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            body.append(glabel(rail, "input", bx, by, 0 if sx < 0 else 180))
    body.append(text("PWR_FLAG marks each rail as driven, so ERC's "
                     "power-pin check means something.",
                     0, round(yflag - 16.51, 2), 1.1))

    print(f"  passives: {n} two-pin parts, 2 crystals, 7 power flags")
    return ru, document(ru, libs, fit(body, "passives"),
                        "Passives and Clocks", (
        "One 100n per MCU VDD pin, 2u2 per VCAP, bulk per rail",
        "CAN terminators R41/R42 live here, not on the comms sheet"))


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
                     "ISOW1044", "Interface_CAN_LIN")
    libs += sym_defs(KICAD_SYMS / "Jumper.kicad_sym",
                     "SolderJumper_2_Bridged", "Jumper")
    libs += sym_defs(KICAD_SYMS / "Connector.kicad_sym",
                     "USB_C_Receptacle_USB2.0_14P", "Connector")
    libs += sym_defs(KICAD_SYMS / "Connector.kicad_sym",
                     "Micro_SD_Card_Det_Hirose_DM3AT", "Connector")

    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_positions(lib)

    body = [text(
        "TWO CAN FD BUSES, BOTH WITH TRANSCEIVERS. v2.4.5 wired CAN2 to the MCU\\n"
        "with no transceiver at all, so it was never usable as a bus.\\n"
        "\\n"
        "TERMINATION IS SWITCHABLE. 120 ohm in series with a solder jumper,\\n"
        "FITTED by default. On a three-board TMR chain the electrically middle\\n"
        "module clears JP1 - it does not get R409 desoldered, which is what the\\n"
        "old board required. Verify ~60 ohm across CAN_H/CAN_L, bus unpowered,\\n"
        "before trusting it.",
        0, 0, 1.4)]

    def wire_part(ref, lib_id, val, x, y, nets):
        body.append(place(lib_id, ref, val, x, y, ru, [],
                          fp=footprint(lib_id, ref)))
        for name, (dx, dy, ang) in geom[lib_id].items():
            net = nets.get(name)
            if net in (None, "NC"):
                continue
            ax, ay = round(x + dx, 2), round(y + dy, 2)
            sx, sy = stub_len(ang, v=3.81)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = "input" if net.startswith(("+", "GND")) else "bidirectional"
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    for i, (ref, bus) in enumerate((("U30", "FDCAN1"), ("U31", "FDCAN2"))):
        n = i + 1
        y = 60.96 + i * 55.88
        # Isolated CAN FD with its own integrated isolated DC-DC. Datasheet
        # SLLSFF7A table 7-1. Two shorts there are easy to miss and both are
        # mandatory: GNDIO and GND1 are NOT internally connected, and
        # VISOOUT/VSIN/VISOIN are one node. STB must go to GNDIO or the
        # driver sits in standby and the bus looks dead.
        wire_part(ref, "Interface_CAN_LIN:ISOW1044", "ISOW1044", 30.48, y,
                  {"TXD": f"{bus}_TX", "RXD": f"{bus}_RX",
                   "VIO": "+3V3", "VDD": "+5V",
                   "GNDIO": "GND", "GND1": "GND",
                   "STB": "GND", "IN": "GND",
                   "EN/FLT": f"CAN{n}_FLT",
                   "VISOOUT": f"VISO{n}", "VSIN": f"VISO{n}",
                   "VISOIN": f"VISO{n}",
                   "GND2": f"GND_ISO{n}", "GISOIN": f"GND_ISO{n}",
                   "CANH": f"CAN{n}_H", "CANL": f"CAN{n}_L"})
        # 120R in series with the jumper, across the pair
        body.append(text(
            f"CAN{n}: R{40+n} 120R + JP{n} (fitted by default)\\n"
            f"clear JP{n} on the middle module of a 3-board chain",
            74.93, round(y - 12.7, 2), 1.1))
        wire_part(f"JP{n}", "Jumper:SolderJumper_2_Bridged",
                  "SolderJumper_2_Bridged", 129.54, y,
                  {"A": f"CAN{n}_TERM", "B": f"CAN{n}_L"})

    wire_part("J30", "Connector:USB_C_Receptacle_USB2.0_14P", "USB-C",
              35.56, 165.1,
              {"VBUS": "VBUS_USB", "GND": "GND", "CC1": "USB_CC1",
               "CC2": "USB_CC2", "D+": "USB_DP_RAW",
               "D-": "USB_DM_RAW", "SHIELD": "GND"})

    # Micro_SD_Card_Det_Hirose_DM3AT, not SD_Card_Device: same socket, but
    # this symbol exposes the DET_A/DET_B mechanical switch and the shield.
    # SD_Card_Device has neither, which is why SD_DETECT had no source and
    # the shield floated.
    #
    # DET_A/DET_B close when a card is seated. DET_B to ground, DET_A pulled
    # up and read by the MCU, so firmware can tell "no card" from "card
    # present but failing" - which matter differently: the first is a
    # pre-flight nag, the second is a logging fault.
    wire_part("J31", "Connector:Micro_SD_Card_Det_Hirose_DM3AT", "microSD",
              129.54, 165.1,
              {"CLK": "SDMMC1_CK", "CMD": "SDMMC1_CMD",
               "DAT0": "SDMMC1_D0", "DAT1": "SDMMC1_D1",
               "DAT2": "SDMMC1_D2", "DAT3/CD": "SDMMC1_D3",
               "DET_A": "SD_DETECT", "DET_B": "GND",
               "SHIELD": "GND",
               "VDD": "+3V3", "VSS": "GND"})

    return ru, document(ru, libs, fit(body, "comms"), "Comms and Storage", (
        "Two CAN FD buses, both with transceivers - v2.4.5 had only one",
        "Termination is jumpered: clear JPn on the middle module of a chain"))



# --------------------------------------------------------------------------
# the connector sheet
# --------------------------------------------------------------------------

# Pinouts follow the Pixhawk connector standard where one exists, because the
# ecosystem's GPS units, telemetry radios and power modules are built to it -
# a novel pinout here means a custom loom for every peripheral.
#
# (ref, ways, value, description, nets from pin 1)
CONNECTORS = [
    # --- stays on the module ------------------------------------------------
    # Used at the module, not through the airframe: a bench console, a card
    # slot and a programmer. Putting these on the carrier would mean
    # unbolting the aircraft to read a log.
    # J6 has moved to the backplane (J52). One debug port serves the set, and
    # a header on a card you have to extract to reach is not a debug port.
    # SWD reaches each card through its gold fingers instead.
    # --- isolated, and deliberately NOT on the mezzanine --------------------
    # 0.5 mm pitch gives ~0.5 mm creepage. Running these beside
    # board-referenced signals would reduce the isolation barrier to that gap
    # and undo the ISOW1044. Separate connectors keep the barrier intact.
    ("J12", 5, "CAN1", "Isolated CAN1 - GND_ISO1, not GND",
     ["GND_ISO1", "CAN1_H_C", "CAN1_L_C", "NC", "GND_ISO1"]),
    ("J13", 5, "CAN2", "Isolated CAN2 - GND_ISO2, not GND",
     ["GND_ISO2", "CAN2_H_C", "CAN2_L_C", "NC", "GND_ISO2"]),
]

# Everything else reaches the carrier through one 60-way 0.5 mm mezzanine
# instead of ten looms. See MEZZ_PINS for the pinout; grounds are interleaved
# between signal groups rather than grouped at one end, because a 60-pin
# connector with no local return is the worst discontinuity on the board.
MEZZ_REF = "J40"
# Not a connector any more - gold fingers on the board's own rear edge, so
# the card slides into a socket on the backplane. 2x30 at 1.27 mm is exactly
# the 60 contacts MEZZ_PINS already defines.
MEZZ_FP = ("Connector_PCBEdge:"
           "Samtec_MECF-30-0_-L-DV_2x30_P1.27mm_Polarized_Edge")
# Debug, console and the three power-source valid flags now cross
# here rather than on their own connectors. VDD_BRICK and
# VDD_SERVO left: the card never sees either rail now, because
# servo power runs from the backplane straight to the actuator
# headers and never passes through a card.
MEZZ_PINS = ['GND', 'SWDIO', 'SWCLK', 'GND', 'NRST', 'USART1_TX', 'GND', '+5V_CARRIER', '+5V_CARRIER', 'GND', 'TIM1_CH1', 'TIM1_CH2', 'GND', 'TIM1_CH3', 'TIM1_CH4', 'GND', 'TIM4_CH1', 'TIM4_CH2', 'GND', 'TIM4_CH3', 'KEY', 'KEY', 'USART2_TX', 'USART2_RX', 'GND', 'USART2_CTS', 'USART2_RTS', 'GND', 'USART3_TX', 'USART3_RX', 'GND', 'USART3_CTS', 'USART3_RTS', 'GND', 'UART4_TX', 'UART4_RX', 'GND', 'I2C2_SCL', 'I2C2_SDA', 'GND', 'UART7_TX', 'UART7_RX', 'GND', 'UART8_RX', 'UART8_TX', 'GND', 'SAFETY_SW', 'SAFETY_LED', 'GND', 'SPI5_SCK', 'SPI5_MISO', 'SPI5_MOSI', 'GND', 'USART1_RX', 'BRICK_VALID', 'GND', 'SERVO_VALID', 'USB_VALID', 'TIM4_CH4', 'GND']

CONN_FP = {
    5:  "Connector_JST:JST_GH_SM05B-GHS-TB_1x05-1MP_P1.25mm_Horizontal",
    6:  "Connector_JST:JST_GH_SM06B-GHS-TB_1x06-1MP_P1.25mm_Horizontal",
    10: "Connector_JST:JST_GH_SM10B-GHS-TB_1x10-1MP_P1.25mm_Horizontal",
}


# The note KiCad renders. Line breaks must be the two-character escape
# \n, not a real newline - a real one inside the quoted string makes the
# file unloadable, and KiCad's response is to draw a blank page rather
# than complain, so the sheet looks merely empty.
NOTE = (
    "Pinouts follow the Pixhawk connector standard where one exists.\\n"
    "The ecosystem's GPS units, telemetry radios and power modules are\\n"
    "built to it; a novel pinout here means a custom loom for every\\n"
    "peripheral.\\n"
    "\\n"
    "JST-GH 1.25 mm throughout - the same family Pixhawk uses, chosen\\n"
    "for its positive latch rather than its size.")


def build_connectors():
    """Everything that leaves the board.

    Until this sheet, 48 nets terminated at a single pin - eight PWM channels,
    sixteen serial lines, the debug port, both power inputs. The schematic was
    complete in the sense that the parts were wired to each other, and useless
    in the sense that nothing could be plugged into it.
    """
    ru = uid()
    libs, seen = [], set()
    for _ref, n, *_rest in CONNECTORS:
        nm = "Conn_01x%02d" % n
        if nm not in seen:
            seen.add(nm)
            libs += sym_defs(KICAD_SYMS / "Connector_Generic.kicad_sym",
                             nm, "Connector_Generic")
    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_list(lib)

    body = [text(NOTE, 0, 0, 1.4)]

    for i, (ref, n, val, _descr, nets) in enumerate(CONNECTORS):
        lib_id = "Connector_Generic:Conn_01x%02d" % n
        cx = 33.02 + (i % 3) * 57.15
        cy = 50.8 + (i // 3) * 48.26
        body.append(place(lib_id, ref, val, cx, cy, ru, [],
                          label_dy=round(n * 1.27 + 6.35, 2),
                          fp=CONN_FP[n]))
        for (num, _nm, dx, dy, ang), net in zip(geom[lib_id], nets):
            if net == "NC":
                continue
            ax, ay = round(cx + dx, 2), round(cy + dy, 2)
            sx, sy = stub_len(ang, h=5.08)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = ("input" if net.startswith(("+", "GND", "VDD"))
                     else "bidirectional")
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    # --- the mezzanine ----------------------------------------------------
    mlib = sym_defs(KICAD_SYMS / "Connector_Generic.kicad_sym",
                    "Conn_02x30_Odd_Even", "Connector_Generic")
    libs.extend(mlib)
    mgeom = pin_list(mlib[-1])
    mx, my = 45.72, 165.1
    body.append(place("Connector_Generic:Conn_02x30_Odd_Even", MEZZ_REF,
                      "CARD EDGE 2x30 P1.27 (no part)", mx, my, ru, [],
                      label_dy=43.18, fp=MEZZ_FP))
    for (num, _nm, dx, dy, ang), net in zip(
            sorted(mgeom, key=lambda p: int(p[0])), MEZZ_PINS):
        if net in ("NC", "KEY"):
            # KEY is the polarizing moulding: the footprint has
            # no pad at contacts 21/22 because the connector
            # body occupies them.
            continue
        ax, ay = round(mx + dx, 2), round(my + dy, 2)
        sx, sy = stub_len(ang, h=3.81)
        bx, by = round(ax + sx, 2), round(ay + sy, 2)
        body.append(wire(ax, ay, bx, by))
        shape = ("input" if net.startswith(("+", "GND", "VDD"))
                 else "bidirectional")
        body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    print("  connectors: %d headers plus a %d-way mezzanine"
          % (len(CONNECTORS), len(MEZZ_PINS)))
    return ru, document(ru, libs, fit(body, "connectors"), "Connectors", (
        "Pixhawk-standard pinouts on JST-GH 1.25 mm",
        "TELEM x2, GPS x2, RC, debug, external SPI, 2 power inputs, 8 PWM"))



# --------------------------------------------------------------------------
# the EMI/EMC protection sheet
# --------------------------------------------------------------------------

PROT_NOTE = (
    "DO-160G s17 voltage spike, s25 ESD, s21 radiated emissions.\\n"
    "\\n"
    "Every off-board harness is an antenna bonded to a board carrying two\\n"
    "deliberate switching sources - U21 at 2.5 MHz and each ISOW1044's\\n"
    "internal converter at 25 MHz. Suppression at the connector is the\\n"
    "only place it works: past it the harness is already radiating.\\n"
    "\\n"
    "Placement is the requirement, not the part. Each device belongs AT\\n"
    "its connector, ahead of everything it protects, with the shortest\\n"
    "return to ground. A TVS 30 mm downstream of the connector protects\\n"
    "the last 30 mm of track and nothing else.")

# Transient suppression on every power input. DO-160G s17.
# 5 V nominal rails, so a 6 V standoff clamps well above the 5.5 V a valid
# supply reaches and well below anything the LTC4417 or the buck will
# tolerate. Unidirectional: these rails are never driven negative in normal
# use, and a reverse-battery event is the LTC4417's job, not the TVS's.
TVS = [
    # One TVS, on the rail the card actually receives. D4/D5/D6 clamped the
    # three airframe sources, which the card no longer sees - those moved to
    # the backplane with the ORing controller that selected between them.
    ("D4", "+5V_CARRIER", "carrier feed, the card's only power input"),
]

# Common-mode chokes. These do nothing for signal integrity and everything
# for emissions: the differential signal passes, the common-mode current that
# actually radiates from the harness does not.
#
# Both CAN pairs sit on the ISOLATED side of their ISOW1044, so their chokes
# and TVS reference GND_ISOn - not GND. Referencing them to board ground
# would bridge the isolation barrier and undo the reason the ISOW1044 is
# there at all.
CHOKES = [
    ("L3", "CAN1_H", "CAN1_L", "CAN1_H_C", "CAN1_L_C", "GND_ISO1", "CAN1"),
    ("L4", "CAN2_H", "CAN2_L", "CAN2_H_C", "CAN2_L_C", "GND_ISO2", "CAN2"),
]


def build_protection():
    """Transient, ESD and emissions control at the board boundary."""
    ru = uid()
    libs = []
    libs += sym_defs(KICAD_SYMS / "Device.kicad_sym", "D_TVS", "Device")
    libs += sym_defs(KICAD_SYMS / "Device.kicad_sym", "FerriteBead", "Device")
    libs += sym_defs(KICAD_SYMS / "Filter.kicad_sym",
                     "Choke_CommonMode_FerriteCore_1234", "Filter")
    libs += sym_defs(KICAD_SYMS / "Power_Protection.kicad_sym",
                     "USBLC6-2SC6", "Power_Protection")
    geom = {}
    for lib in libs:
        m = re.search(r'\(symbol "([^"]+)"', lib)
        geom[m.group(1)] = pin_list(lib)

    body = [text(PROT_NOTE, 0, 0, 1.35)]

    def part(lib_id, ref, val, x, y, nets, fp, dy=11.43):
        body.append(place(lib_id, ref, val, x, y, ru, [], label_dy=dy, fp=fp))
        for num, nm, dx, dyy, ang in geom[lib_id]:
            net = nets.get(num) or nets.get(nm)
            if net in (None, "NC"):
                continue
            ax, ay = round(x + dx, 2), round(y + dyy, 2)
            sx, sy = stub_len(ang, h=5.08, v=3.81)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(wire(ax, ay, bx, by))
            shape = ("input" if net.startswith(("+", "GND", "VDD", "VBUS"))
                     else "bidirectional")
            body.append(glabel(net, shape, bx, by, 0 if sx < 0 else 180))

    # --- power input transient suppression -------------------------------
    for i, (ref, net, _why) in enumerate(TVS):
        part("Device:D_TVS", ref, "SMAJ6.0A",
             round(25.4 + i * 45.72, 2), 66.04,
             {"A1": net, "A2": "GND"}, "Diode_SMD:D_SMA")

    # --- USB: ESD array then common-mode choke ---------------------------
    # The ESD array goes FIRST, closest to the connector, so it protects the
    # choke too. USBLC6-2SC6 is the standard part for this and its two pins
    # per channel are one node - route in one, out the other.
    part("Power_Protection:USBLC6-2SC6", "U40", "USBLC6-2SC6", 25.4, 154.94,
         {"1": "USB_DP_RAW", "6": "USB_DP_RAW",
          "3": "USB_DM_RAW", "4": "USB_DM_RAW",
          "5": "VBUS_USB", "2": "GND"},
         "Package_TO_SOT_SMD:SOT-23-6", dy=13.97)
    part("Filter:Choke_CommonMode_FerriteCore_1234", "L5", "90R@100MHz",
         99.06, 154.94,
         {"1": "USB_DP_RAW", "2": "USB_OTG_FS_DP",
          "3": "USB_DM_RAW", "4": "USB_OTG_FS_DM"},
         "Inductor_SMD:L_CommonModeChoke_Coilank_ACM1608")

    # --- CAN: common-mode choke per bus, on the isolated side ------------
    for i, (ref, hin, lin, hout, lout, gnd, name) in enumerate(CHOKES):
        y = 190.5 + i * 30.48
        part("Filter:Choke_CommonMode_FerriteCore_1234", ref, "51uH CM",
             30.48, y, {"1": hin, "2": hout, "3": lin, "4": lout},
             "Inductor_SMD:L_CommonModeChoke_Coilank_ACM1608")
        part("Device:D_TVS", "D%d" % (7 + i), "PESD2CAN",
             104.14, y, {"A1": hout, "A2": lout}, "Diode_SMD:D_SOD-323")

    # --- ferrites on the 5 V feed to the external harnesses --------------
    # Conducted emissions leave on the power wire as readily as on the
    # signal wires, and the servo harness is the longest thing attached to
    # this board.
    # One ferrite, not three. Every harness now leaves through the mezzanine,
    # so there is one 5 V feed to filter instead of three separate ones - and
    # three ferrites feeding nets nothing connects to is worse than none.
    for i, (ref, net) in enumerate((("FB1", "+5V_CARRIER"),)):
        part("Device:FerriteBead", ref, "600R@100MHz",
             round(20.32 + i * 45.72, 2), 116.84,
             {"1": "+5V", "2": net}, "Inductor_SMD:L_0805_2012Metric")

    print("  protection: %d TVS, 3 chokes, 1 ESD array, 3 ferrites"
          % (len(TVS) + len(CHOKES)))
    return ru, document(ru, libs, fit(body, "protection"),
                        "EMI / EMC Protection", (
        "DO-160G s17 voltage spike, s25 ESD, s21 radiated emissions",
        "CAN protection references GND_ISO, not GND - it is past the barrier"))


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
        0, 0, 1.5)]
    for i, (nm, fn) in enumerate([("MCU", "mcu.kicad_sch"),
                                  ("SENSORS", "sensors.kicad_sch"),
                                  ("POWER", "power.kicad_sch"),
                                  ("COMMS", "comms.kicad_sch"),
                                  ("PASSIVES", "passives.kicad_sch"),
                                  ("CONNECTORS", "connectors.kicad_sch"),
                                  ("PROTECTION", "protection.kicad_sch")]):
        # One column, tighter pitch. Two columns fit the anchors but not
        # the Sheetfile text, which fit() does not measure - the render
        # ran 15 mm past the frame.
        body.append(sheet_block(nm, fn, 20.32, 45.72 + i * 25.4,
                                ru, i + 2))
    return ru, document(ru, [], fit(body, "root"), "JFOX-FMU v1", (
        "STM32H753IIT6 - 3 IMUs, 2 barometers, magnetometer, CAN FD",
        "Generated by hardware/tools/gen_fmu_schematic.py - regenerate, do not edit",
        "Sheet 1 of 8"))


def build_stub(title, note):
    ru = uid()
    return ru, document(ru, [], [text(title + "\\n\\n" + note, 20, 20, 1.6)],
                        title)


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
    _, connectors = build_connectors()
    _, protection = build_protection()
    _, root = build_root()
    files = {BOARD / "comms.kicad_sch": comms,
             BOARD / "passives.kicad_sch": passives,
             BOARD / "connectors.kicad_sch": connectors,
             BOARD / "protection.kicad_sch": protection,
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

    # The footprint table is not optional and was missing. Symbols resolved
    # because sym-lib-table named the symbol library; the project's own
    # footprints resolved for nothing, because no table named jfox-fmu.pretty.
    # KiCad reports this as footprint_link_issues at ERC time, and the board
    # simply cannot place those four parts.
    (BOARD / "fp-lib-table").write_text(
        '(fp_lib_table\n  (version 7)\n'
        '  (lib (name "jfox-fmu")(type "KiCad")'
        '(uri "${KIPRJMOD}/jfox-fmu.pretty")(options "")'
        '(descr "JFOX-FMU footprints with no stock equivalent"))\n)\n',
        encoding="utf-8")

    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    upgrade(list(files))
    for p in files:
        print(f"  wrote {p.relative_to(REPO)} ({p.stat().st_size} bytes)")
    print(f"  wrote {PROJECT}.kicad_pro, sym-lib-table")


if __name__ == "__main__":
    main()
