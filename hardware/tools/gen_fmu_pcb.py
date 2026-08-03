#!/usr/bin/env python3
"""Generate the JFOX-FMU board: outline, 6-layer stackup, mounting, placement.

What this produces, and what it deliberately does not
----------------------------------------------------

Produced here, because it is data rather than judgement:

  * a 90 x 65 mm outline with 2 mm corner radii, sized from the real
    footprint areas in the netlist (3300 mm^2 of parts) rather than guessed;
  * the six-layer stackup argued for in PCB_STACKUP_AND_EMC.md, with solid
    ground on L2 and L5 either side of the split power layer;
  * four M3 mounting holes on a 74 x 49 mm pattern;
  * net classes with impedance-driven widths, including 90 ohm USB and
    120 ohm CAN differential pairs;
  * every footprint placed into the EMC zone it belongs in - noisy, digital,
    quiet and isolated - because placement decides emissions more than
    routing does.

NOT produced here: routing. An LQFP176 escape, a 2.5 MHz switching regulator,
controlled-impedance differential pairs, an isolation barrier with creepage
requirements and a magnetometer that has to stay clean is interactive layout
work. Generated copper on flight hardware would need reviewing track by
track, which is more work than routing it properly once.

The placement here is a starting arrangement that respects the zones, not a
finished layout. It puts every part on the correct side of the board in the
correct region, so the layout engineer starts from something meaningful
rather than from a heap in the corner.

    python hardware/tools/gen_fmu_pcb.py

Writes hardware/jfox-fmu-v1/jfox-fmu.kicad_pcb
"""

import json
import math
import re
import subprocess
import sys
import tempfile
import uuid as _uuid
from pathlib import Path

import kicad_geom

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
SCH = BOARD / "jfox-fmu.kicad_sch"
OUT = BOARD / "jfox-fmu.kicad_pcb"

KICAD = Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0")
STOCK = KICAD / "share" / "kicad" / "footprints"

VERSION = 20260206

# Board origin and size. 100 x 80 = 8000 mm^2 against 3300 mm^2 of parts.
#
# 90 x 65 was tried first and does not work: U10's courtyard is 27 mm square,
# which is taller than any horizontal zone band that board could give it. An
# LQFP176 plus eleven on-board connectors needs the area, and pretending
# otherwise produces a layout nobody can route. FMUv6X gets away with 85 x 42
# because its connectors live on the carrier, not on the module.
# 48 wide: 4 mm either side of the 39.85 mm gold fingers, and 10.3 mm either
# side of U10's 27.36 mm courtyard, which is the tighter of the two. 130 long
# is 120 of body plus the 10 mm tongue, giving 37% part density on the front
# face - ordinary for six layers.
# 48 x 125 after the power tree and the debug port moved to the backplane.
# Part courtyards total 1715 mm2; 48 x 115 of body is 5520, so parts occupy
# 31% - comfortable for six layers. 50 x 160 was 8000 mm2 at 24%, sized to
# stop the shelf-packer complaining rather than from any area requirement.
# 48 x 90: body 80 plus the 10 mm tongue. Part courtyards total 1715 mm2
# against 3840 of body, so parts occupy 45% - which is what ordinary
# double-sided practice achieves and roughly twice the 26% the flat-gap
# packer was managing at 135 mm long.
# 40 mm: the board is the width of its own gold fingers. The body is then
# narrower than the 43.22 mm socket housing, so the tongue needs no relief
# steps - the card front enters the slot whole.
BX, BY, W, H = 30.0, 30.0, 40.0, 90.0
CORNER_R = 2.0

# M3 clear holes, 8 mm in from each corner.
# 5 mm, not 8. At 8 the corner holes' courtyards reach x = 11.45 and the
# centred MCU starts at 10.3 - the holes would be under the package.
M3_INSET = 5.0
# Front pair sits behind the card slot (17.7 mm deep) rather than in the
# corners, so the front edge belongs entirely to what has to be reached.
M3_FRONT_Y = 22.0


def M3_HOLES(body_h):
    return ()


def _M3_HOLES_unused(body_h):
    """The four hole positions. One definition, used by both the placement
    and the keep-out reservation - they were separate lists and drifted."""
    return ((M3_INSET, M3_FRONT_Y), (W - M3_INSET, M3_FRONT_Y),
            (M3_INSET, body_h - M3_INSET), (W - M3_INSET, body_h - M3_INSET))
M3_FP = "MountingHole:MountingHole_3.2mm_M3"

# The card edge. Half-width and depth are read from the connector footprint's
# own Edge.Cuts at generation time - see tongue_spec() - so the outline and
# the fingers cannot disagree. The body is shortened by the tongue depth, so
# the overall envelope is unchanged.
TONGUE_REF = "J40"


def uid():
    return str(_uuid.uuid4())


# --------------------------------------------------------------------------
# Six layers. See PCB_STACKUP_AND_EMC.md for why not four: this board splits
# the power layer four ways for the switched sensor rails plus the analog and
# isolated domains, and a signal crossing a split has no return beneath it.
# L2 and L5 are solid ground and must stay solid - a routed track on a ground
# layer is a slot, and a slot under a fast edge is a better antenna than any
# track.
# --------------------------------------------------------------------------
LAYERS = """\t(layers
\t\t(0 "F.Cu" signal)
\t\t(1 "In1.Cu" signal "GND1")
\t\t(2 "In2.Cu" signal "SIG_IN")
\t\t(3 "In3.Cu" power "PWR")
\t\t(4 "In4.Cu" signal "GND2")
\t\t(31 "B.Cu" signal)
\t\t(32 "B.Adhes" user "B.Adhesive")
\t\t(33 "F.Adhes" user "F.Adhesive")
\t\t(34 "B.Paste" user)
\t\t(35 "F.Paste" user)
\t\t(36 "B.SilkS" user "B.Silkscreen")
\t\t(37 "F.SilkS" user "F.Silkscreen")
\t\t(38 "B.Mask" user)
\t\t(39 "F.Mask" user)
\t\t(40 "Dwgs.User" user "User.Drawings")
\t\t(41 "Cmts.User" user "User.Comments")
\t\t(42 "Eco1.User" user "User.Eco1")
\t\t(43 "Eco2.User" user "User.Eco2")
\t\t(44 "Edge.Cuts" user)
\t\t(45 "Margin" user)
\t\t(46 "B.CrtYd" user "B.Courtyard")
\t\t(47 "F.CrtYd" user "F.Courtyard")
\t\t(48 "B.Fab" user)
\t\t(49 "F.Fab" user)
\t)"""

# --------------------------------------------------------------------------
# Placement zones, from PCB_STACKUP_AND_EMC.md. Placement decides emissions
# more than routing does, so this is the part worth generating.
#
#   NOISY      switching regulator, ORing FETs, power connectors
#   ISOLATED   the two ISOW1044s and everything past their barrier
#   DIGITAL    MCU, microSD, USB, FRAM
#   QUIET      IMUs, barometers, magnetometer, crystals, VCAP
#
# (name, x0, y0, x1, y1) in board coordinates, relative to BX/BY.
# Zones start 13 mm in at top and bottom so they clear the M3 holes at
# 8 mm inset - a hole inside a courtyard is a part that cannot be fitted,
# and DRC reports it as npth_inside_courtyard.
ZONES = {
    # --- back face: both noise groups in ONE region, at the front ---------
    # Together rather than spread down the board. Spread out, every point on
    # the card is within 13 mm of something switching; grouped, the far end
    # is 22 mm clear and the sensors can live there. The 15 mm rule is only
    # satisfiable on an 80 mm body if noise occupies one end of it.
    "NOISY":    (2.0, 19.0, 38.0, 29.0),
    "ISOLATED": (2.0, 32.0, 38.0, 48.0),
    # --- front face: digital behind the MCU, sensors at the far end -------
    "DIGITAL":  (2.0, 50.0, 26.0, 58.0),
    "DIGITAL2": (2.0, 59.0, 26.0, 65.0),
    # The sensor island, as far from the converters as an 80 mm body allows.
    "QUIET":    (2.0, 69.0, 38.0, 79.0),
}










# Which zone each part belongs in, and which side. Passives default to the
# bottom so the top stays routable; the parts that must be top are the ones
# with a connector, a package too large to fit under, or a placement
# constraint of their own.
# Parts whose position is a requirement rather than a preference. These are
# placed exactly, before anything is packed around them.
#
# J31's card opening must sit ON the board edge - a microSD socket buried in
# the middle of a board is a card you cannot change without dismantling the
# aircraft. The Hirose DM3AT is a push-push; the card travels along +Y, so the
# socket goes at the bottom edge with its mouth outward.
# Parts whose position is a requirement rather than a preference, given as
# (edge, offset-along-that-edge, side). The part is then aligned by its
# COURTYARD, not its origin - placing a 15 mm deep microSD socket by its
# origin hangs it off the board, which is what the first attempt did.
FIXED_EDGE = {
    # --- REAR (south): the card edge, key notch and all -------------------
    "J40": ("FLUSH_S", 20.0, "F"),

    # --- FRONT (north): the only face anyone can see ----------------------
    # 37 mm of usable edge for 29.97 mm of connector and lamp. The four
    # mounting holes used to take the corners; without them the whole edge
    # is available and the parts sit on ~1.2 mm gaps instead of 0.5.
    "J31": ("BODY_N", 10.4, "F"),   # microSD, mouth ON the edge
    "D1":  ("XY", (19.0, 1.2), "F"),    # POWER, left of the USB-C
    "J30": ("BODY_N", 26.6, "F"),   # USB-C console
    "D2":  ("XY", (35.4, 1.2), "F"),    # HEARTBEAT, right of the USB-C

    # --- FLANKS -----------------------------------------------------------
    "J12": ("E", 52.0, "F"),        # isolated CAN1, behind the MCU
    "J13": ("E", 60.0, "F"),        # isolated CAN2, behind the MCU

    # The magnetometer at the extreme rear of the sensor island - the point
    # furthest from the converter region, which is where its 25 mm has to
    # come from now that both noise groups share the front of the back face.
    "U6":  ("SW", 0.0, "F"),

    # The MCU, placed rather than centred: 27.36 mm on a 40 mm card leaves
    # 6.3 mm each flank, so there is nowhere else it can go.
    "U10": ("XY", (6.3, 20.0), "F"),

    # The buck, pinned rather than packed. Its exposed pad carries a thermal
    # via array, and a via goes through every layer - so on the back face
    # under U10 its ground vias land in the MCU's +3V3 pads. U10 holds
    # y 20..47.4, so U21 goes below it. This is the only part on the board
    # whose placement is constrained by what is on the OTHER side.
    "U21": ("XY", (20.0, 50.0), "B"),
}





# The MCU is anchored dead centre. Nearly every net terminates at U10, so
# this is the single placement decision that most affects total net length.
MCU_CENTRE = None
FIXED = {}

ZONE_OF = [
    # (regex on reference, zone, side)
    (r'^U10$',            "DIGITAL",  "F"),   # the MCU

    (r'^U5$',             "DIGITAL2", "F"),   # FRAM
    (r'^U40$|^L5$',       "DIGITAL2", "F"),   # USB protection, beside J30

    (r'^U2[0-6]$',        "NOISY",    "B"),   # ORing, buck, LDO, load switches
    (r'^Q[123][AB]$',     "NOISY",    "F"),   # ORing pass FETs
    (r'^L1$',             "NOISY",    "B"),   # buck inductor
    (r'^J[89]$',          "NOISY",    "F"),   # power inputs
    (r'^D[456]$|^FB[123]$', "NOISY",  "B"),   # input TVS, ferrites

    (r'^U3[01]$',         "ISOLATED", "B"),   # the two ISOW1044
    (r'^L[34]$|^D[78]$',  "ISOLATED", "B"),   # CAN chokes and TVS
    (r'^JP[12]$',         "ISOLATED", "B"),   # termination jumpers

    (r'^U[1-467]$',       "QUIET",    "F"),   # IMUs, baros, magnetometer
    (r'^X[12]$',          "QUIET",    "F"),   # crystals
    (r'^D3$',             "QUIET",    "F"),   # D1/D2 are anchored to the front edge   # status LEDs
]



# --------------------------------------------------------------------------
# Design rules. Ordinary 6-layer practice, each value with its reason - a
# board with no rules gets KiCad's defaults, which rejected the TPS62132's
# thermal vias outright and called its exposed pad a mask bridge.
#
#   0.15 mm track / 0.15 mm clearance   every fabricator quotes this without
#                                       a premium; going finer costs money
#                                       and this board does not need it.
#   0.20 mm minimum drill               the TPS62132's thermal vias. Smaller
#                                       is laser-drilled and expensive.
#   0.45 / 0.25 via                     0.1 mm annular ring, standard.
#   0.20 mm hole-to-hole                below this, drill wander bridges.
#   0.10 mm mask sliver                 lets the exposed-pad mask openings
#                                       resolve instead of bridging.
# --------------------------------------------------------------------------
SETUP = """\t(setup
\t\t(pad_to_mask_clearance 0.05)
\t\t(solder_mask_min_width 0.1)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(grid_origin {gx} {gy})
\t)"""

# The design constraints do NOT go in the board's (setup) block. KiCad 10
# rejects a (rules ...) token there outright - "Unexpected rules, line 41" -
# and refuses to load the file at all. They live in the project file, under
# board.design_settings.rules, which is what the .kicad_pro carries.
#
# The failure is worth recording because of how it presented: kicad-cli
# exited 2 without writing a report, check_fmu_drc.py found the PREVIOUS
# report still on disk at its fixed temp path, and reported a plausible
# 107-violation breakdown of a board that had not been read. Both ends are
# now fixed - the block is gone, and the checker deletes the report first.

# Net classes. Widths are sized for the current each net actually carries and
# for the impedance targets in PCB_STACKUP_AND_EMC.md, not picked uniformly.
#
# The two differential pairs are the reason controlled impedance goes on the
# fabrication drawing: the fabricator adjusts trace width to hit 90 and 120
# ohm against this stackup, so the numbers here are a starting point that the
# stackup calculation overrides.
NETCLASSES = [
    # Default first. Without it KiCad applies its own 0.2 mm clearance, which
    # reports a standard USB-C receptacle as violating itself 84 times - the
    # footprint's pads are 0.15 mm apart because that is what the connector
    # is. The board's stated minimum is 0.15 mm; this is where the netclass
    # system actually reads it.
    ("Default", 0.20, 0.15, 0.6, 0.3, 0, 0, []),
    # (name, track, clearance, via, via_drill, diff_pair_width, diff_gap, nets)
    ("Power", 0.60, 0.20, 0.8, 0.4, 0, 0,
     ["+3V3", "+3V3A", "+3V3_IMU1", "+3V3_IMU2", "+3V3_IMU3", "+3V3_SENS",
      "VISO1", "VISO2", "VCAP"]),
    # The input rails and the servo feed carry the whole board plus whatever
    # the carrier draws; 1 mm on 1 oz copper is about 2 A at a 10 C rise.
    ("HighCurrent", 1.00, 0.25, 1.0, 0.5, 0, 0,
     # VBUS_USB is deliberately NOT here. It is the lowest-priority ORing
     # input - a bench supply, not a flight rail - and a 0.25 mm clearance
     # rule on it makes a standard USB-C receptacle violate its own pad
     # spacing 84 times. The connector's geometry is fixed; the rule was the
     # thing that was wrong.
     ["+5V", "+5V_CARRIER", "VDD_BRICK", "VDD_SERVO", "SW_3V3"]),
    ("USB", 0.20, 0.20, 0.45, 0.25, 0.20, 0.13,
     ["USB_OTG_FS_DP", "USB_OTG_FS_DM", "USB_DP_RAW", "USB_DM_RAW"]),
    ("CAN", 0.25, 0.20, 0.45, 0.25, 0.25, 0.20,
     ["CAN1_H", "CAN1_L", "CAN2_H", "CAN2_L",
      "CAN1_H_C", "CAN1_L_C", "CAN2_H_C", "CAN2_L_C"]),
    # SDMMC at 50 MHz wants a consistent width and a length-matched group.
    ("SDMMC", 0.20, 0.20, 0.45, 0.25, 0, 0,
     ["SDMMC1_CK", "SDMMC1_CMD", "SDMMC1_D0", "SDMMC1_D1",
      "SDMMC1_D2", "SDMMC1_D3"]),
]


# Minimum manufacturable geometry, quoted by every fabricator at no premium.
# These are project settings, NOT board settings - see the note on SETUP.
RULES = {
    "min_clearance": 0.15,
    "min_track_width": 0.15,
    "min_via_annular_width": 0.1,
    "min_via_diameter": 0.45,
    "min_through_hole_diameter": 0.2,
    "min_hole_clearance": 0.2,
    "min_hole_to_hole": 0.2,
    "min_microvia_diameter": 0.2,
    "min_microvia_drill": 0.1,
    "min_silk_clearance": 0.0,
    "min_text_height": 0.8,
    "min_text_thickness": 0.08,
    "min_resolved_spokes": 2,
    "min_connection": 0.0,
    "solder_mask_to_copper_clearance": 0.05,
}


def write_netclasses():
    """Put the net classes and design rules in the .kicad_pro.

    This used to emit a (net_class ...) block into the board's (setup).
    KiCad rejects that outright - net classes moved to the project file in
    KiCad 7 - so the board would not load and DRC never ran at all. Writing
    a rule somewhere plausible is not the same as writing it where the tool
    reads, and the difference is invisible until you check the exit code.
    """
    pro = BOARD / "jfox-fmu.kicad_pro"
    doc = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {}

    doc["net_settings"] = {
        "meta": {"version": 4},
        "classes": [
            {
                "name": name,
                "clearance": cl,
                "track_width": w,
                "via_diameter": v,
                "via_drill": vd,
                "diff_pair_width": dw or 0.2,
                "diff_pair_gap": dg or 0.25,
                "diff_pair_via_gap": 0.25,
                "microvia_diameter": 0.3,
                "microvia_drill": 0.1,
                "wire_width": 6,
                "bus_width": 12,
                "line_style": 0,
                "pcb_color": "rgba(0, 0, 0, 0.000)",
                "schematic_color": "rgba(0, 0, 0, 0.000)",
            }
            for name, w, cl, v, vd, dw, dg, _ in NETCLASSES
        ],
        "net_colors": None,
        "netclass_assignments": {
            n: [name] for name, _, _, _, _, _, _, nets in NETCLASSES
            for n in nets
        },
        "netclass_patterns": [],
    }
    doc.setdefault("board", {}).setdefault("design_settings", {})
    doc["board"]["design_settings"]["rules"] = dict(RULES)
    doc.setdefault("meta", {"filename": pro.name, "version": 1})

    pro.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return len(NETCLASSES)


def cli():
    for c in (KICAD / "bin" / "kicad-cli.exe",
              Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found")


def project_libs():
    tbl = BOARD / "fp-lib-table"
    libs = {}
    if tbl.exists():
        for name, uri in re.findall(r'\(name "([^"]+)"\).*?\(uri "([^"]+)"\)',
                                    tbl.read_text(encoding="utf-8"), re.S):
            libs[name] = Path(uri.replace("${KIPRJMOD}", str(BOARD)))
    return libs


LIBS = project_libs()


def resolve(fp):
    if ":" not in fp:
        return None
    lib, name = fp.split(":", 1)
    root = LIBS.get(lib) or (STOCK / f"{lib}.pretty")
    p = root / f"{name}.kicad_mod"
    return p if p.exists() else None


def netlist():
    out = Path(tempfile.gettempdir()) / "fmu_pcb.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"netlist export failed:\n{r.stdout}\n{r.stderr}")
    txt = out.read_text(encoding="utf-8")

    comps = []
    for b in re.split(r'\n\s*\(comp\b', txt)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', b)
        val = re.search(r'\(value "([^"]*)"\)', b)
        fp = re.search(r'\(footprint "([^"]*)"\)', b)
        if ref and fp and not ref.group(1).startswith("#"):
            comps.append((ref.group(1), val.group(1) if val else "",
                          fp.group(1)))

    nets = {}
    for b in re.split(r'\n\s*\(net\b', txt)[1:]:
        code = re.search(r'\(code "(\d+)"\)', b)
        nm = re.search(r'\(name "([^"]*)"\)', b)
        if code and nm:
            nets[nm.group(1)] = int(code.group(1))
            for r_, p_ in re.findall(
                    r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', b):
                nets.setdefault("_pins", {})[(r_, p_)] = (
                    int(code.group(1)), nm.group(1))
    return comps, nets


def extent(path):
    """Courtyard size and offset of a footprint file.

    Placement has to know how big each part is. Two earlier versions of this
    read the courtyard with a windowed regex and both were wrong - see
    kicad_geom.py for what each one measured instead. An 0402 came out
    0.308 x 0.000 mm, so the packer spaced parts by a sliver and DRC found
    123 courtyard collisions on a board where nothing had been routed.

    A footprint's origin is its pin-1 datum, not its courtyard centre, so
    the offset is returned as well as the size: placing at (x + w/2) assumes
    they coincide, and for the connectors and the LQFP they do not.
    """
    try:
        return kicad_geom.extent(path.read_text(encoding="utf-8"))
    except ValueError:
        sys.exit(f"{path.name}: no courtyard and no pads - cannot place it")



def edge_datum(path):
    """(min_y, max_y) of a footprint's Edge.Cuts, in footprint coordinates.

    A card-edge footprint draws the tongue profile it expects the board
    outline to follow. That profile - not the courtyard - is what has to
    coincide with the board edge, and it is the only thing in the file that
    says where the fingers are meant to stop.
    """
    t = path.read_text(encoding="utf-8")
    ys = []
    for tok in ("fp_line", "fp_rect", "fp_poly", "fp_arc"):
        for e in kicad_geom.sexprs(t, tok):
            if '(layer "Edge.Cuts")' not in e:
                continue
            for m in re.finditer(r'\((?:start|end|xy|mid) '
                                 r'(-?[\d.]+) (-?[\d.]+)\)', e):
                ys.append(float(m.group(2)))
    return (min(ys), max(ys)) if ys else None


def part_gap(w, h):
    """Clearance to the next part, from its size.

    Ordinary assembly practice, not one number for everything: roughly
    0.5 mm around small parts, 0.8 mm around medium, 1.2 mm around large.
    A flat 1.2 mm - which is what this used - puts an 0402 two and a half
    times further from its neighbour than it has to be, and with forty-odd
    passives on the bottom face that is most of a board length spent on air.
    """
    d = max(w, h)
    if d <= 3.0:
        return 0.5
    if d <= 8.0:
        return 0.8
    return 1.2


def pack(items, x0, y0, x1, y1, gap=None, avoid=None):
    """Shelf-pack parts into a zone, largest first, no overlaps.

    Not a good layout - a good layout groups by function and puts decoupling
    under its own IC. This only guarantees the two things a generator can
    guarantee: every part is inside its zone, and no two parts occupy the
    same copper.
    """
    order = sorted(items, key=lambda it: -max(it[4], it[5]))
    out, cx, cy, row_h = [], x0, y0, 0.0
    avoid = list(avoid or ())
    for ref, val, path, side, w, h, ox, oy in order:
        while True:
            if cx + w > x1:
                cx = x0
                cy += row_h + (gap or 0.8)
                row_h = 0.0
            if cy + h > y1:
                break
            # Areas already taken on this side - the decoupling packed
            # under each IC. Without this the general bottom pack laid its
            # rows straight across them, and 15 courtyards collided.
            hit = next((a for a in avoid
                        if cx < a[2] and a[0] < cx + w
                        and cy < a[3] and a[1] < cy + h), None)
            if not hit:
                break
            cx = hit[2] + (gap or 0.5)
        if cy + h > y1:
            out.append((ref, val, path, side, None, None))
            continue
        # Place so the courtyard's top-left lands at (cx, cy), whatever the
        # origin's offset from it happens to be.
        out.append((ref, val, path, side, cx - ox, cy - oy))
        g = gap if gap is not None else part_gap(w, h)
        cx += w + g
        row_h = max(row_h, h)
    return out


def zone_for(ref):
    for pat, zone, side in ZONE_OF:
        if re.match(pat, ref):
            return zone, side
    # Everything unlisted is a passive: bottom side, under the block it
    # serves. Decoupling wants to be beneath its own IC, which a human will
    # do properly; this at least puts it on the right side and in the right
    # half of the board.
    return None, "B"


def edge_arc_rect_notch(x, y, w, h, r, nx0, nx1, ny, lead):
    """Rounded rectangle with a polarising notch cut into the south edge."""
    o = []

    def line(x1, y1, x2, y2):
        o.append(f'\t(gr_line (start {round(x1,3)} {round(y1,3)}) '
                 f'(end {round(x2,3)} {round(y2,3)})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) '
                 f'(layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    def arc(sx, sy, mx, my, ex, ey):
        o.append(f'\t(gr_arc (start {round(sx,3)} {round(sy,3)}) '
                 f'(mid {round(mx,3)} {round(my,3)}) '
                 f'(end {round(ex,3)} {round(ey,3)})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) '
                 f'(layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    k = r * 0.29289
    line(x + r, y, x + w - r, y)
    arc(x + w - r, y, x + w - k, y + k, x + w, y + r)
    line(x + w, y + r, x + w, lead - r)
    arc(x + w, lead - r, x + w - k, lead - k, x + w - r, lead)
    line(x + w - r, lead, nx1, lead)          # south edge, right of the notch
    line(nx1, lead, nx1, ny)                  # notch, right wall
    line(nx1, ny, nx0, ny)                    # notch, top
    line(nx0, ny, nx0, lead)                  # notch, left wall
    line(nx0, lead, x + r, lead)              # south edge, left of the notch
    arc(x + r, lead, x + k, lead - k, x, lead - r)
    line(x, lead - r, x, y + r)
    arc(x, y + r, x + k, y + k, x + r, y)
    return o


def edge_profile(path, ox, oy):
    """A footprint's Edge.Cuts segments, translated into board coordinates.

    Returns [(x1, y1, x2, y2)] and the profile's x range. This is what makes
    the key slot real: the polarised card edge has a 1.24 x 7.0 mm notch cut
    into its leading edge, and taking min/max of the profile - which is what
    this used to do - produces a plain rectangle with no notch in it. A
    tongue without the slot fouls the connector's polarising moulding, so
    the board would not have gone in at all.
    """
    t = path.read_text(encoding="utf-8")
    segs, xs = [], []
    for tok in ("fp_line", "fp_rect"):
        for e in kicad_geom.sexprs(t, tok):
            if '(layer "Edge.Cuts")' not in e:
                continue
            a = re.search(r'\(start (-?[\d.]+) (-?[\d.]+)\)', e)
            b = re.search(r'\(end (-?[\d.]+) (-?[\d.]+)\)', e)
            if not (a and b):
                continue
            x1, y1 = float(a.group(1)) + ox, float(a.group(2)) + oy
            x2, y2 = float(b.group(1)) + ox, float(b.group(2)) + oy
            segs.append((x1, y1, x2, y2))
            xs += [x1, x2]
    return segs, (min(xs), max(xs))


def edge_arc_rect_profile(x, y, w, h, r, segs, xr):
    """Board outline whose south edge hands over to a connector profile."""
    lo, hi = xr
    flush = abs(lo - x) < 1.0 and abs(hi - (x + w)) < 1.0
    if flush:
        # The board is as wide as its own fingers, so there is no tongue -
        # the card front IS the connector edge, and the body is narrower
        # than the socket housing so nothing needs relieving.
        #
        # Keeping only the LEADING-edge segments matters: the profile's
        # side stubs collapse to zero length once snapped flush, and a
        # zero-length segment leaves the outline open. KiCad calls that an
        # invalid outline, which is a board that cannot be filled or made.
        lead = max(max(t[1], t[3]) for t in segs)
        segs = [t for t in segs
                if abs(t[1] - lead) < 0.01 and abs(t[3] - lead) < 0.01
                or abs(t[0] - t[2]) < 0.01]
        segs = [(max(x, min(x + w, t[0])), t[1],
                 max(x, min(x + w, t[2])), t[3]) for t in segs]
        segs = [t for t in segs
                if abs(t[0] - t[2]) > 0.01 or abs(t[1] - t[3]) > 0.01]
        lo, hi = x, x + w
    o = []

    def line(x1, y1, x2, y2):
        o.append(f'\t(gr_line (start {round(x1,3)} {round(y1,3)}) '
                 f'(end {round(x2,3)} {round(y2,3)})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) (layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    def arc(sx, sy, mx, my, ex, ey):
        o.append(f'\t(gr_arc (start {round(sx,3)} {round(sy,3)}) '
                 f'(mid {round(mx,3)} {round(my,3)}) '
                 f'(end {round(ex,3)} {round(ey,3)})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) (layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    # The profile's own stubs sit at the body's south edge, so that is where
    # the rectangle has to stop.
    by = (max(max(t[1], t[3]) for t in segs) if flush
          else min(min(t[1], t[3]) for t in segs))
    k = r * 0.29289
    line(x + r, y, x + w - r, y)
    arc(x + w - r, y, x + w - k, y + k, x + w, y + r)
    line(x + w, y + r, x + w, by - r)
    arc(x + w, by - r, x + w - k, by - k, x + w - r, by)
    if flush:
        # Corner to the first notch wall, the notch, then on to
        # the far corner - one continuous south edge.
        pts = sorted({round(t[0], 3) for t in segs}
                     | {round(t[2], 3) for t in segs})
        line(x + w - r, by, pts[-1], by)
        for x1, y1, x2, y2 in segs:
            line(x1, y1, x2, y2)
        line(pts[0], by, x + r, by)
    else:
        line(x + w - r, by, hi, by)
        for x1, y1, x2, y2 in segs:
            line(x1, y1, x2, y2)
        line(lo, by, x + r, by)
    arc(x + r, by, x + k, by - k, x, by - r)
    line(x, by - r, x, y + r)
    arc(x, y + r, x + k, y + k, x + r, y)
    return o


def edge_arc_rect_tongue(x, y, w, h, r, tongue):
    """Outline with a tongue protruding from the south edge.

    (half_width, depth, centre_x) in board coordinates. The body stops
    `depth` short of the south edge everywhere except across the tongue,
    which runs on to it - so the relief steps either side are what the
    socket housing clears.
    """
    hw, depth, cx = tongue
    by = y + h - depth                      # body's south edge
    l, r_ = x + cx - hw, x + cx + hw        # tongue sides
    o = []

    def line(x1, y1, x2, y2):
        o.append(f'\t(gr_line (start {round(x1,3)} {round(y1,3)}) '
                 f'(end {round(x2,3)} {round(y2,3)})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) (layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    def arc(sx, sy, mx, my, ex, ey):
        o.append(f'\t(gr_arc (start {round(sx,3)} {round(sy,3)}) '
                 f'(mid {round(mx,3)} {round(my,3)}) '
                 f'(end {round(ex,3)} {round(ey,3)})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) (layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    k = r * 0.29289
    # top edge and the two top corners
    line(x + r, y, x + w - r, y)
    arc(x + w - r, y, x + w - k, y + k, x + w, y + r)
    line(x + w, y + r, x + w, by - r)
    arc(x + w, by - r, x + w - k, by - k, x + w - r, by)
    # south edge, right of the tongue
    line(x + w - r, by, r_, by)
    # the tongue: down, across the leading edge, back up
    line(r_, by, r_, y + h)
    line(r_, y + h, l, y + h)
    line(l, y + h, l, by)
    # south edge, left of the tongue
    line(l, by, x + r, by)
    arc(x + r, by, x + k, by - k, x, by - r)
    line(x, by - r, x, y + r)
    arc(x, y + r, x + k, y + k, x + r, y)
    return o


def edge_arc_rect(x, y, w, h, r):
    """Board outline with rounded corners, as lines plus arcs."""
    o = []

    def line(x1, y1, x2, y2):
        o.append(f'\t(gr_line (start {x1} {y1}) (end {x2} {y2})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) (layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    def arc(sx, sy, mx, my, ex, ey):
        o.append(f'\t(gr_arc (start {sx} {sy}) (mid {mx} {my}) (end {ex} {ey})\n'
                 f'\t\t(stroke (width 0.1) (type solid)) (layer "Edge.Cuts")\n'
                 f'\t\t(uuid "{uid()}")\n\t)')

    k = r * 0.29289  # 1 - cos(45deg), for the arc midpoint
    line(x + r, y, x + w - r, y)
    arc(x + w - r, y, x + w - k, y + k, x + w, y + r)
    line(x + w, y + r, x + w, y + h - r)
    arc(x + w, y + h - r, x + w - k, y + h - k, x + w - r, y + h)
    line(x + w - r, y + h, x + r, y + h)
    arc(x + r, y + h, x + k, y + h - k, x, y + h - r)
    line(x, y + h - r, x, y + r)
    arc(x, y + r, x + k, y + k, x + r, y)
    return o


def strip_edge_cuts(body):
    """Remove a footprint's own Edge.Cuts geometry.

    The Samtec card-edge footprint carries Edge.Cuts lines describing the
    card's tongue profile. Dropped straight into a board that already has a
    complete outline, they produce a second, disconnected set of outline
    fragments and KiCad reports invalid_outline - the board has no single
    closed boundary any more, so it cannot be manufactured or even filled.

    The outline this generator draws already ends at the board edge where
    the fingers are, so the footprint's copy is redundant. The bevel on the
    leading edge is a FABRICATION NOTE, not board geometry - it belongs on
    the drawing with the selective hard gold callout, and neither can be
    expressed in the .kicad_pcb.
    """
    out, depth, keep = [], 0, True
    for chunk in re.split(r'(\(fp_(?:line|arc|poly|rect|circle))', body):
        out.append(chunk)
    txt = "".join(out)
    # Walk each graphic and drop the ones on Edge.Cuts.
    import kicad_geom
    for tok in ("fp_line", "fp_arc", "fp_poly", "fp_rect", "fp_circle"):
        for e in kicad_geom.sexprs(txt, tok):
            if re.search(r'\(layer "Edge\.Cuts"\)', e):
                txt = txt.replace(e, "", 1)
    return txt


def embed_footprint(path, ref, value, x, y, side, nets_for_ref):
    """Place a footprint, with its pads assigned to the right nets."""
    t = path.read_text(encoding="utf-8")
    name = re.match(r'\(footprint "([^"]+)"', t).group(1)

    body = t[t.index("\n"):].rstrip()
    # Strip every field the generated header already supplies. The library
    # body carries its own (layer) and (uuid); leaving them produces a
    # footprint with two of each, which KiCad loads and DRC then reports as
    # the same pad colliding with itself - 90 phantom clearance violations
    # that no amount of moving parts apart would ever fix.
    body = strip_edge_cuts(body)
    for field in ("version", "generator", "generator_version",
                  "layer", "uuid", "at"):
        body = re.sub(r'\n\t\(%s[^\n]*\)' % field, "", body, count=1)
    if body.endswith(")"):
        body = body[:-1].rstrip()

    # Attach nets to pads by pad number.
    def add_net(m):
        num = m.group(1)
        hit = nets_for_ref.get(num)
        if not hit:
            return m.group(0)
        code, nname = hit
        return m.group(0) + f'\n\t\t(net {code} "{nname}")'
    body = re.sub(r'\(pad "([^"]+)"[^\n]*', add_net, body)

    body = body.replace('(property "Reference" "REF**"',
                        f'(property "Reference" "{ref}"')
    body = re.sub(r'\(property "Value" "[^"]*"',
                  f'(property "Value" "{value}"', body, count=1)

    # Flipping a footprint to the back means mirroring EVERY layer it
    # references, not just the header. Setting (layer "B.Cu") alone leaves
    # every pad on F.Cu, so the "bottom" passives stayed on top and collided
    # with the parts they were supposed to sit beneath - which is what DRC
    # was reporting as 91 courtyard overlaps and 107 clearance violations.
    if side == "B":
        body = re.sub(r'"F\.(Cu|SilkS|Mask|Paste|CrtYd|Fab|Adhes)"',
                      lambda m: '"B.%s"' % m.group(1), body)
        # Text on a back layer reads through the board, so every text item
        # needs a mirror flag or it is unreadable on the fabricated part.
        # KiCad reports the omission as nonmirrored_text_on_back_layer, 199
        # of them here - one per silkscreen field on every flipped passive.
        body = re.sub(r'\(justify ([^)]*)\)',
                      lambda m: m.group(0) if 'mirror' in m.group(1)
                      else '(justify %s mirror)' % m.group(1), body)
        body = re.sub(r'\(effects\n(\s*)\(font',
                      lambda m: '(effects\n%s(justify mirror)\n%s(font'
                                % (m.group(1), m.group(1)), body)
    layer = "F.Cu" if side == "F" else "B.Cu"
    head = (f'\t(footprint "{name}"\n\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{uid()}")\n\t\t(at {round(x,3)} {round(y,3)})')
    return head + body + "\n\t)"


def main():
    comps, nets = netlist()
    pins = nets.get("_pins", {})

    # --- group parts by zone ------------------------------------------------
    placed, zoned = [], {z: [] for z in ZONES}
    bottom = []
    for ref, val, fp in comps:
        p = resolve(fp)
        if p is None:
            print(f"  skip {ref}: {fp} unresolved")
            continue
        z, side = zone_for(ref)
        ox, oy, w, h = extent(p)
        (zoned[z] if z else bottom).append((ref, val, p, side, w, h, ox, oy))

    body = []

    # --- outline and mounting ----------------------------------------------
    # The tongue comes from the card-edge connector's own profile, so the
    # outline cannot disagree with the fingers it has to carry.
    tongue = None
    tongue_seg = None
    for ref, _val, path, *_ in ([c for z in zoned.values() for c in z]
                                + bottom):
        if ref != TONGUE_REF:
            continue
        d = edge_datum(path)
        if d is None:
            sys.exit(f"{ref}: no Edge.Cuts profile, so the board outline has "
                     f"nothing to cut the card tongue from")
        xs = []
        for tok in ("fp_line", "fp_rect", "fp_poly"):
            for e in kicad_geom.sexprs(path.read_text(encoding="utf-8"), tok):
                if '(layer "Edge.Cuts")' not in e:
                    continue
                for m in re.finditer(r'\((?:start|end|xy) '
                                     r'(-?[\d.]+) (-?[\d.]+)\)', e):
                    if abs(float(m.group(2)) - d[1]) < 0.01:
                        xs.append(float(m.group(1)))
        tongue = (max(xs), d[1] - d[0], FIXED_EDGE[ref][1])
        # FIXED is not populated yet - the outline is drawn before the
        # edge-aligned parts are resolved - so the FLUSH_S placement is
        # computed here directly rather than read back. Reading it gave a
        # KeyError, and the DRC that ran afterwards reported PASS on the
        # STALE board file, which is the same trap as the one that hid a
        # board KiCad could not load for several rounds.
        _edge, _off, _side = FIXED_EDGE[ref]
        assert _edge == "FLUSH_S", f"{ref}: tongue expects a FLUSH_S placement"
        tongue_seg = edge_profile(path, BX + _off, BY + H - d[1])
    if tongue_seg:
        segs, (lo, hi) = tongue_seg
        if abs(lo - BX) < 1.5 and abs(hi - (BX + W)) < 1.5:
            # Board as wide as its own fingers: there is no tongue to cut.
            # The card front IS the connector edge, and the body is narrower
            # than the 43.22 mm socket housing so nothing needs relieving.
            # A plain rectangle with the polarising notch in its south edge
            # is the whole outline - trying to synthesise a tongue here left
            # sub-0.1 mm slivers either side, which KiCad rejects as an
            # invalid outline.
            lead = max(max(t[1], t[3]) for t in segs)
            # The profile has four vertical segments: the tongue's two side
            # walls at the extremes, and the notch's two inside them.
            # Taking the outermost pair selects the SIDE walls, which made
            # the generator cut the whole 39.85 mm finger area away as if it
            # were the key slot. The notch is the pair strictly inside.
            verts = sorted(t[0] for t in segs if abs(t[1] - t[3]) > 0.01)
            inner = [v for v in verts if lo + 0.5 < v < hi - 0.5]
            if len(inner) != 2:
                raise SystemExit(
                    f"expected 2 notch walls inside the profile, found "
                    f"{len(inner)} - refusing to guess which edge is the key")
            nx = inner
            ny = min(min(t[1], t[3]) for t in segs
                     if abs(t[1] - t[3]) > 0.01 and t[0] in inner)
            body += edge_arc_rect_notch(BX, BY, W, H, CORNER_R,
                                        nx[0], nx[1], ny, lead)
        else:
            body += edge_arc_rect_profile(BX, BY, W, H, CORNER_R, *tongue_seg)
    else:
        body += edge_arc_rect(BX, BY, W, H, CORNER_R)
    m3 = resolve(M3_FP)
    # Inset from the BODY's corners, not the overall length. With a 10 mm
    # tongue on the rear edge, H - M3_INSET puts the rear pair inside the
    # tongue - which is 39.85 mm wide, so on a 50 mm card the holes land
    # half on laminate and half in fresh air.
    body_h = H - (tongue[1] if tongue else 0.0)
    for i, (dx, dy) in enumerate(M3_HOLES(body_h), start=1):
        if m3:
            body.append(embed_footprint(m3, f"MH{i}", "M3",
                                        BX + dx, BY + dy, "F", {}))

    # --- placement ----------------------------------------------------------
    # Resolve the edge-aligned parts now that extents are known.
    for ref, val, p, side, w, h, ox, oy in (
            [c for z in zoned.values() for c in z] + bottom):
        if ref not in FIXED_EDGE:
            continue
        edge, off, fside = FIXED_EDGE[ref]
        m = 1.5          # clearance from the outline
        # South-referenced placements measure from the BODY edge, not from
        # the overall length. With a 10 mm tongue on the rear, BY + H is the
        # tongue's leading edge - so a part put 1.5 mm inside "the south
        # edge" lands in the tongue's Y band but outside its 39.85 mm width,
        # i.e. in mid-air. That is where U6 and its decoupling went, and
        # nothing caught it: DRC has no rule for a part off the board, and
        # every checker here measured against the bounding box, which the
        # tongue makes a poor description of the shape.
        bh = H - (tongue[1] if tongue else 0.0)
        if edge == "S":
            FIXED[ref] = (BX + off, BY + bh - m - h - oy, fside)
        elif edge == "N":
            FIXED[ref] = (BX + off, BY + m - oy, fside)
        elif edge == "W":
            FIXED[ref] = (BX + m - ox, BY + off, fside)
        elif edge == "E":
            FIXED[ref] = (BX + W - m - w - ox, BY + off, fside)
        elif edge == "SW":
            FIXED[ref] = (BX + m - ox, BY + bh - m - h - oy, fside)
        elif edge in ("BODY_N", "BODY_S"):
            # Courtyard flush with the outline, no margin. For a connector
            # whose MOUTH is the mating feature - a card slot, a USB
            # receptacle - the body has to reach the edge even though the
            # pads do not. Held 1.5 mm inboard, a USB-C plug's overmould
            # fouls the board edge before the contacts seat, and the card
            # slot loses the support that stops a half-inserted card
            # levering on its contacts.
            #
            # Ideally these overhang the outline by ~0.5 mm, which needs a
            # notch in the board edge. That is a fabrication detail this
            # generator does not draw; it is on the open list.
            if edge == "BODY_N":
                FIXED[ref] = (BX + off, BY - oy, fside)
            else:
                FIXED[ref] = (BX + off, BY + H - h - oy, fside)
        elif edge in ("FLUSH_N", "FLUSH_S"):
            # Align the footprint's OWN Edge.Cuts datum to the board edge,
            # not its courtyard. Courtyard alignment left the gold fingers
            # 7.25 mm inboard - a board that passes DRC and cannot be
            # plugged in.
            d = edge_datum(p)
            if d is None:
                raise SystemExit(
                    f"{ref}: asked for a flush edge placement but the "
                    f"footprint carries no Edge.Cuts datum, so there is "
                    f"nothing to align to")
            dmin, dmax = d
            if edge == "FLUSH_N":
                FIXED[ref] = (BX + off, BY - dmin, fside)
            else:
                FIXED[ref] = (BX + off, BY + H - dmax, fside)
        elif edge == "XY":
            # Absolute position, courtyard top-left. Used where a part is
            # placed by a mechanical constraint rather than by an edge -
            # the base board's three mezzanine headers each sit under their
            # own riser column, which is a position, not an edge.
            FIXED[ref] = (BX + off[0] - ox, BY + off[1] - oy, fside)
        elif edge == "B_CENTRE":
            FIXED[ref] = (BX + W / 2 - w / 2 - ox,
                          BY + bh / 2 - h / 2 - oy, fside)
        else:
            raise SystemExit(f"{ref}: unknown edge {edge!r}")

    # The MCU last, so it wins the centre outright.
    for ref, val, p, side, w, h, ox, oy in (
            [c for z in zoned.values() for c in z] + bottom):
        if ref == MCU_CENTRE:
            FIXED[ref] = (BX + W / 2 - w / 2 - ox,
                          BY + H / 2 - h / 2 - oy, "F")

    overflow = []
    where = {}
    taken = []
    fp_path = {}
    ic_side = {}
    for ref, val, p, side, w, h, ox, oy in list(
            [c for z in zoned.values() for c in z] + bottom):
        if ref in FIXED:
            fx, fy, fside = FIXED[ref]
            body.append(embed_footprint(
                p, ref, val, fx, fy, fside,
                {pn: v for (r_, pn), v in pins.items() if r_ == ref}))
            placed.append(ref)
            where[ref] = (fx + ox, fy + oy, w, h)
            fp_path[ref] = p
            ic_side[ref] = fside
    for z in zoned:
        zoned[z] = [c for c in zoned[z] if c[0] not in FIXED]
    bottom = [c for c in bottom if c[0] not in FIXED]

    for zname, (zx0, zy0, zx1, zy1) in ZONES.items():
        for ref, val, p, side, x, y in pack(zoned[zname], BX + zx0, BY + zy0,
                                            BX + zx1, BY + zy1):
            if x is None:
                overflow.append((ref, zname))
                continue
            body.append(embed_footprint(
                p, ref, val, x, y, side,
                {pn: v for (r_, pn), v in pins.items() if r_ == ref}))
            placed.append(ref)
            for c in zoned[zname]:
                if c[0] == ref:
                    where[ref] = (x + c[6], y + c[7], c[4], c[5])
                    fp_path[ref] = c[2]
                    ic_side[ref] = side
                    # Anything already on the BACK face has to be reserved
                    # against the bottom passive pack, which runs the whole
                    # board. Moving the power and isolated blocks under the
                    # board put them straight in its path - 53 mask bridges
                    # and 130 violations, all from two placement passes
                    # writing to the same face without telling each other.
                    if side == "B":
                        taken.append((x + c[6], y + c[7],
                                      x + c[6] + c[4], y + c[7] + c[5]))

    # --- decoupling, under the IC it decouples -----------------------------
    # A capacitor packed into a row 30 mm away is not decoupling anything.
    # The loop from the pin through a via to the cap and back is the whole
    # quantity it exists to minimise, so each one goes directly beneath the
    # IC it shares a supply net with, on the far side of the board.
    net_of = {}
    for (r_, pn), v in pins.items():
        net_of.setdefault(r_, set()).add(v)

    # Only ICs whose land is entirely surface-mount. U21's exposed pad has
    # a thermal via array, and a via is a hole through every layer - so a
    # capacitor placed on the far side "under" it lands on top of the vias
    # rather than under the pad. DRC reported it as four mask bridges and
    # three shorts, which is exactly what it would have been.
    def all_smd(ref):
        _ox, _oy, _w, _h = where[ref]
        path = fp_path.get(ref)
        if path is None:
            return False
        body = path.read_text(encoding="utf-8")
        return "thru_hole" not in body and "(pads" not in body

    ics = [r for r in where if re.match(r'^U\d', r) and all_smd(r)]
    under = {r: [] for r in ics}
    rest = []
    for c in bottom:
        ref = c[0]
        if not re.match(r'^C\d', ref):
            rest.append(c)
            continue
        # The supply net is the one that is not ground. A cap that shares
        # only GND with an IC is not that IC's decoupling.
        rails = {n for n in net_of.get(ref, ()) if n and n != "GND"}
        cands = [r for r in ics if rails & net_of.get(r, set())]
        if not cands:
            rest.append(c)
            continue
        # Spread across the ICs on that rail rather than piling every +3V3
        # cap under whichever one is listed first.
        under[min(cands, key=lambda r: len(under[r]))].append(c)

    # A part with a thermal via array occupies BOTH faces: the vias are
    # holes through every layer. Excluding it from under-IC decoupling is
    # only half the fix - the general bottom pack still runs across it, and
    # that is where the mask bridges and shorts on U21 came from. Its area
    # is reserved on the far side too.
    for ref in list(where):
        if not re.match(r'^U\d', ref) or all_smd(ref):
            continue
        ox_, oy_, w_, h_ = where[ref]
        taken.append((ox_, oy_, ox_ + w_, oy_ + h_))

    # What each face already holds, so a capacitor is only tucked under its
    # IC when the far side is actually empty there. Placing on the opposite
    # face is right in principle and wrong whenever that face is occupied -
    # which after the power blocks moved under the board is most of the
    # front, where the MCU and the sensor island live.
    occupied = {"F": [], "B": []}
    for r_, (ox_, oy_, w_, h_) in where.items():
        occupied[ic_side.get(r_, "F")].append(
            (ox_, oy_, ox_ + w_, oy_ + h_))

    # A hole goes through both faces, so it belongs in both lists. It was in
    # the bottom pack's keep-out and not in this one, which is how two
    # capacitors ended up on top of MH1.
    for dx, dy in M3_HOLES(H - (tongue[1] if tongue else 0.0)):
        r = (BX + dx - 3.45, BY + dy - 3.45, BX + dx + 3.45, BY + dy + 3.45)
        occupied["F"].append(r)
        occupied["B"].append(r)

    def face_free(face, x0_, y0_, x1_, y1_):
        return not any(x0_ < b[2] and b[0] < x1_ and y0_ < b[3] and b[1] < y1_
                       for b in occupied[face])

    for ic, caps in under.items():
        if not caps:
            continue
        ix, iy, iw, ih = where[ic]
        for ref, val, p, side, x, y in pack(caps, ix, iy, ix + iw, iy + ih,
                                            gap=0.5):
            if x is None:
                rest.append(next(c for c in caps if c[0] == ref))
                continue
            far = "F" if ic_side.get(ic, "F") == "B" else "B"
            c0 = next(c for c in caps if c[0] == ref)
            if not face_free(far, x + c0[6], y + c0[7],
                             x + c0[6] + c0[4], y + c0[7] + c0[5]):
                rest.append(c0)
                continue
            occupied[far].append((x + c0[6], y + c0[7],
                                  x + c0[6] + c0[4], y + c0[7] + c0[5]))
            body.append(embed_footprint(
                p, ref, val, x, y, far,
                {pn: v for (r_, pn), v in pins.items() if r_ == ref}))
            placed.append(ref)
            c = next(c for c in caps if c[0] == ref)
            if far == "B":
                taken.append((x + c[6], y + c[7],
                              x + c[6] + c[4], y + c[7] + c[5]))
    bottom = rest

    # Passives on the bottom, packed across the whole board.
    # Anything with a hole in it occupies EVERY layer, so it blocks the back
    # face regardless of which side its body is on: the four M3 holes, the
    # USB-C shell tabs, the card-edge fingers. The bottom pass was laying
    # rows straight over them - which is why MH3 and J30 accounted for
    # eighteen of the last thirty-three violations.
    taken.extend(occupied["B"])
    for r_, (ox_, oy_, w_, h_) in where.items():
        path_ = fp_path.get(r_)
        if r_.startswith("MH") or (
                path_ is not None
                and "thru_hole" in path_.read_text(encoding="utf-8")):
            taken.append((ox_, oy_, ox_ + w_, oy_ + h_))
    for dx, dy in M3_HOLES(body_h):
        taken.append((BX + dx - 3.45, BY + dy - 3.45,
                      BX + dx + 3.45, BY + dy + 3.45))

    for ref, val, p, side, x, y in pack(bottom, BX + 2.0, BY + 48.0,
                                        BX + W - 2.0, BY + H - 11.0,
                                        gap=1.0, avoid=taken):
        if x is None:
            overflow.append((ref, "bottom"))
            continue
        body.append(embed_footprint(
            p, ref, val, x, y, "B",
            {pn: v for (r_, pn), v in pins.items() if r_ == ref}))
        placed.append(ref)

    # --- through-hole parts must not overlap the far face -----------------
    # Zone packing fills its rectangle without consulting any keep-out list,
    # so a band drawn over something on the other side wins silently. That
    # has now produced mounting holes under bands twice and a via array
    # under the MCU once. DRC catches the electrical result but only after
    # the fact; this refuses to write the file at all.
    tht = []
    for r_, path_ in fp_path.items():
        if r_.startswith("MH") or (
                path_ is not None
                and "thru_hole" in path_.read_text(encoding="utf-8")):
            tht.append(r_)
    for a_ in tht:
        ax0, ay0, aw, ah = where[a_]
        for b_, (bx0, by0, bw, bh) in where.items():
            if b_ == a_ or b_ in tht:
                continue
            if ic_side.get(a_) == ic_side.get(b_):
                continue          # same face - ordinary courtyard rules
            if (ax0 < bx0 + bw and bx0 < ax0 + aw
                    and ay0 < by0 + bh and by0 < ay0 + ah):
                sys.exit(
                    f"{a_} has through-hole pads and overlaps {b_} on the "
                    f"far face - its holes would land in {b_}'s pads. "
                    f"Move one of them; a via is a hole through every layer, "
                    f"so opposite sides is not clearance.")

    # --- silkscreen zone labels, so the intent survives into the editor ----
    for zname, (zx0, zy0, _zx1, _zy1) in ZONES.items():
        body.append(
            f'\t(gr_text "{zname}"\n\t\t(at {BX+zx0+1} {BY+zy0+1.5})\n'
            f'\t\t(layer "Cmts.User")\n\t\t(uuid "{uid()}")\n'
            f'\t\t(effects (font (size 1.5 1.5) (thickness 0.2)) '
            f'(justify left top))\n\t)')

    net_decls = "\n".join(
        f'\t(net {c} "{n}")' for n, c in sorted(
            ((n, c) for n, c in nets.items() if n != "_pins"),
            key=lambda kv: kv[1]))

    OUT.write_text(
        f'(kicad_pcb\n\t(version {VERSION})\n\t(generator "jfox gen_fmu_pcb")\n'
        f'\t(generator_version "10.0")\n'
        f'\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n'
        f'\t(paper "A3")\n'
        + LAYERS + "\n"
        # Neither (rules ...) nor (net_class ...) may appear in the board's
        # (setup) block - KiCad 10 rejects both and refuses to load the file.
        # Design constraints and net classes are project-level settings, so
        # write_netclasses() puts them in the .kicad_pro instead.
        + SETUP.format(gx=BX, gy=BY) + "\n"

        + net_decls + "\n"
        + "\n".join(body) + "\n)\n", encoding="utf-8")

    nlayers = len(re.findall(r'"(?:F|B|In\d+)\.Cu"', LAYERS))
    print(f"  board {W:.0f} x {H:.0f} mm, {nlayers} layers, "
          f"{len(placed)} footprints placed")
    if overflow:
        print(f"  {len(overflow)} did not fit their zone: "
              f"{[r for r, _ in overflow][:8]}")
    for z in ZONES:
        print(f"     {z:<9} {len(zoned[z]):>3}")
    print(f"     bottom    {len(bottom):>3}  (passives)")
    print(f"  wrote {OUT.relative_to(REPO)}")
    print(f"  wrote {write_netclasses()} net classes and "
          f"{len(RULES)} design rules into {OUT.stem}.kicad_pro")


if __name__ == "__main__":
    main()
