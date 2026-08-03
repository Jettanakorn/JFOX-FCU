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

import re
import subprocess
import sys
import tempfile
import uuid as _uuid
from pathlib import Path

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
BX, BY, W, H = 30.0, 30.0, 100.0, 80.0
CORNER_R = 2.0

# M3 clear holes, 8 mm in from each corner.
M3_INSET = 8.0
M3_FP = "MountingHole:MountingHole_3.2mm_M3"


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
    "NOISY":    (13.0, 2.0, 48.0, 22.0),
    "ISOLATED": (50.0, 2.0, 87.0, 22.0),
    # 32 mm tall so the 27 mm LQFP176 fits with room to escape.
    "DIGITAL":  (2.0, 26.0, 98.0, 58.0),
    "QUIET":    (13.0, 62.0, 87.0, 78.0),
}

# Which zone each part belongs in, and which side. Passives default to the
# bottom so the top stays routable; the parts that must be top are the ones
# with a connector, a package too large to fit under, or a placement
# constraint of their own.
ZONE_OF = [
    # (regex on reference, zone, side)
    (r'^U10$',            "DIGITAL",  "F"),   # the MCU
    (r'^J3[01]$',         "DIGITAL",  "F"),   # USB-C, microSD
    (r'^U5$',             "DIGITAL",  "F"),   # FRAM
    (r'^U40$|^L5$',       "DIGITAL",  "F"),   # USB protection, near J30

    (r'^U2[0-6]$',        "NOISY",    "F"),   # ORing, buck, LDO, load switches
    (r'^Q[123][AB]$',     "NOISY",    "F"),   # ORing pass FETs
    (r'^L1$',             "NOISY",    "F"),   # buck inductor
    (r'^J[89]$',          "NOISY",    "F"),   # power inputs
    (r'^D[456]$|^FB[123]$', "NOISY",  "F"),   # input TVS, ferrites

    (r'^U3[01]$',         "ISOLATED", "F"),   # the two ISOW1044
    (r'^L[34]$|^D[78]$',  "ISOLATED", "F"),   # CAN chokes and TVS
    (r'^JP[12]$',         "ISOLATED", "F"),   # termination jumpers

    (r'^U[1-467]$',       "QUIET",    "F"),   # IMUs, baros, magnetometer
    (r'^X[12]$',          "QUIET",    "F"),   # crystals
    (r'^D[123]$',         "QUIET",    "F"),   # status LEDs
    (r'^J([1-7]|10|11)$', "QUIET",    "F"),   # signal connectors
]


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
    """Courtyard size of a footprint, or the pad bounding box plus a margin.

    Placement has to know how big each part is. The first version of this
    used a fixed 14 mm grid, which is fine for an 0402 and nonsense for a
    27 mm LQFP176: parts overlapped, and DRC reported 72 shorts and 63
    courtyard collisions on a board where nothing had been routed yet. A
    placement that overlaps is worse than no placement, because it looks
    done.
    """
    t = path.read_text(encoding="utf-8")
    xs, ys = [], []
    for m in re.finditer(r'\(fp_rect\s*\(start (-?[\d.]+) (-?[\d.]+)\)\s*'
                         r'\(end (-?[\d.]+) (-?[\d.]+)\)[\s\S]{0,200}?'
                         r'\(layer "[FB]\.CrtYd"\)', t):
        a, b, c, d = map(float, m.groups())
        xs += [a, c]
        ys += [b, d]
    if not xs:
        for m in re.finditer(r'\(pad "[^"]*" \w+ \w+\s*\(at (-?[\d.]+) '
                             r'(-?[\d.]+)[^)]*\)\s*\(size ([\d.]+) '
                             r'([\d.]+)\)', t):
            x, y, w, h = map(float, m.groups())
            xs += [x - w / 2, x + w / 2]
            ys += [y - h / 2, y + h / 2]
    if not xs:
        return -2.5, -2.5, 5.0, 5.0
    # Offset as well as size. A footprint's origin is its pin-1 datum, not
    # its courtyard centre - placing at (x + w/2) assumes they coincide, and
    # for the connectors and the LQFP they do not. That assumption produced
    # 92 courtyard collisions on a board where nothing had been routed.
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def pack(items, x0, y0, x1, y1, gap=1.2):
    """Shelf-pack parts into a zone, largest first, no overlaps.

    Not a good layout - a good layout groups by function and puts decoupling
    under its own IC. This only guarantees the two things a generator can
    guarantee: every part is inside its zone, and no two parts occupy the
    same copper.
    """
    order = sorted(items, key=lambda it: -max(it[4], it[5]))
    out, cx, cy, row_h = [], x0, y0, 0.0
    for ref, val, path, side, w, h, ox, oy in order:
        if cx + w > x1:
            cx = x0
            cy += row_h + gap
            row_h = 0.0
        if cy + h > y1:
            out.append((ref, val, path, side, None, None))
            continue
        # Place so the courtyard's top-left lands at (cx, cy), whatever the
        # origin's offset from it happens to be.
        out.append((ref, val, path, side, cx - ox, cy - oy))
        cx += w + gap
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


def embed_footprint(path, ref, value, x, y, side, nets_for_ref):
    """Place a footprint, with its pads assigned to the right nets."""
    t = path.read_text(encoding="utf-8")
    name = re.match(r'\(footprint "([^"]+)"', t).group(1)

    body = t[t.index("\n"):].rstrip()
    body = re.sub(r'\n\t\(version \d+\)', "", body)
    body = re.sub(r'\n\t\(generator[^\n]*\)', "", body)
    body = re.sub(r'\n\t\(generator_version[^\n]*\)', "", body)
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
    body += edge_arc_rect(BX, BY, W, H, CORNER_R)
    m3 = resolve(M3_FP)
    for i, (dx, dy) in enumerate((
            (M3_INSET, M3_INSET), (W - M3_INSET, M3_INSET),
            (M3_INSET, H - M3_INSET), (W - M3_INSET, H - M3_INSET)), start=1):
        if m3:
            body.append(embed_footprint(m3, f"MH{i}", "M3",
                                        BX + dx, BY + dy, "F", {}))

    # --- placement ----------------------------------------------------------
    overflow = []
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

    # Passives on the bottom, packed across the whole board.
    for ref, val, p, side, x, y in pack(bottom, BX + 13.0, BY + 13.0,
                                        BX + W - 13.0, BY + H - 13.0,
                                        gap=1.0):
        if x is None:
            overflow.append((ref, "bottom"))
            continue
        body.append(embed_footprint(
            p, ref, val, x, y, "B",
            {pn: v for (r_, pn), v in pins.items() if r_ == ref}))
        placed.append(ref)

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
        + '\t(setup\n\t\t(pad_to_mask_clearance 0)\n'
          '\t\t(allow_soldermask_bridges_in_footprints no)\n'
        + f'\t\t(grid_origin {BX} {BY})\n\t)\n'
        + net_decls + "\n"
        + "\n".join(body) + "\n)\n", encoding="utf-8")

    print(f"  board {W:.0f} x {H:.0f} mm, 6 layers, "
          f"{len(placed)} footprints placed")
    if overflow:
        print(f"  {len(overflow)} did not fit their zone: "
              f"{[r for r, _ in overflow][:8]}")
    for z in ZONES:
        print(f"     {z:<9} {len(zoned[z]):>3}")
    print(f"     bottom    {len(bottom):>3}  (passives)")
    print(f"  wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
