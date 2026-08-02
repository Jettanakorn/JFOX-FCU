#!/usr/bin/env python3
"""Place and route the carrier board.

Runs on hardware/carrier/carrier.kicad_pcb after the netlist has been loaded
into it (Tools > Update PCB from Schematic). KiCad drops the nine connectors
in a heap wherever there was room, which happens to be on top of the mounting
holes; this puts them where the layout wants them and lays the copper.

The layout is chosen so the routing is trivially correct rather than merely
DRC-clean:

  * The three CAN connectors sit in a column at the same x, so their pin 2s
    line up and CAN_H is a single straight trace down the board, with CAN_L
    parallel to it 1.25 mm away. That is a real daisy chain with no stubs, and
    the pair stays tight, which is what a differential bus wants. No
    termination is placed - each module carries a fixed 120R R409, so the
    carrier must not add a fourth.

  * Power runs left to right: brick in on one column, out to the module on
    another, at matching pin positions. The three signals per board would
    collide if routed straight across at pin height, so each drops to the back
    layer at its own offset and comes back up - three parallel runs, no
    crossings, no shared copper between boards.

Everything is checked afterwards by `kicad-cli pcb drc`, which is the point:
this script's job is to be verifiable, not clever.

Run:
  python hardware/tools/route_carrier.py
"""

import re
import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PCB = REPO / "hardware" / "carrier" / "carrier.kicad_pcb"

ROWS = [108.0, 125.0, 142.0]          # one per board, clear of the M3 holes
X_CAN, X_IN, X_OUT = 106.0, 140.0, 165.0
PITCH = 1.25                           # DF13

W_SIG, W_PWR = 0.25, 0.6               # trace widths
VIA_D, VIA_DRILL = 0.6, 0.3

# Per-board signals, as (pin, net-suffix, back-layer offset, width). The offsets
# are what keep the three runs from crossing: each net owns one y level.
POWER = [(2, "VBRICK", 3.0, W_PWR), (3, "BATT_I", 4.5, W_SIG),
         (4, "BATT_V", 6.0, W_SIG)]

PLACE = {}
for i, (b, y) in enumerate(zip("ABC", ROWS)):
    PLACE[f"J{i+1}"] = (X_CAN, y)      # CAN to module J405
    PLACE[f"J{i+4}"] = (X_IN, y)       # brick in
    PLACE[f"J{i+7}"] = (X_OUT, y)      # out to module J601
PLACE.update({"H1": (125.0, 115.0), "H2": (155.0, 115.0),
              "H3": (125.0, 145.0), "H4": (155.0, 145.0)})


def uid():
    return str(_uuid.uuid4())


def seg(x1, y1, x2, y2, w, layer, net):
    return (f'\t(segment\n\t\t(start {round(x1,3)} {round(y1,3)})\n'
            f'\t\t(end {round(x2,3)} {round(y2,3)})\n'
            f'\t\t(width {w})\n\t\t(layer "{layer}")\n'
            f'\t\t(net "{net}")\n\t\t(uuid "{uid()}")\n\t)')


def via(x, y, net):
    return (f'\t(via\n\t\t(at {round(x,3)} {round(y,3)})\n'
            f'\t\t(size {VIA_D})\n\t\t(drill {VIA_DRILL})\n'
            f'\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net "{net}")\n\t\t(uuid "{uid()}")\n\t)')


def zone(layer):
    """A ground pour on both layers, carrying GND for all 15 ground pads.

    Two details that are easy to get wrong and silently produce a zone that
    conducts nothing: KiCad 10 names the net (`(net "GND")`) where KiCad 7 used
    an index plus `net_name`, and the fill has to be explicitly enabled with
    `(fill yes ...)`. Without either, DRC reports every ground pad unconnected
    while the board looks poured on screen.

    Thermal relief keeps the through-hole DF13 grounds hand-solderable; tied
    straight into a plane they sink too much heat to wet properly.
    """
    return (f'\t(zone\n\t\t(net "GND")\n'
            f'\t\t(layers "{layer}")\n\t\t(uuid "{uid()}")\n'
            f'\t\t(hatch edge 0.5)\n\t\t(connect_pads\n\t\t\t(clearance 0.5)\n\t\t)\n'
            f'\t\t(min_thickness 0.25)\n\t\t(filled_areas_thickness no)\n'
            f'\t\t(fill yes\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t)\n'
            f'\t\t(polygon\n\t\t\t(pts\n'
            f'\t\t\t\t(xy 100.5 100.5) (xy 179.5 100.5)\n'
            f'\t\t\t\t(xy 179.5 159.5) (xy 100.5 159.5)\n'
            f'\t\t\t)\n\t\t)\n\t)')


# The board title sits where J1 ended up once the connectors were placed, so
# the silkscreen is moved out of the CAN column here rather than in
# gen_carrier_pcb.py, which runs before placement is known.
TEXT_MOVES = {
    "JFOX TMR CARRIER": (150.0, 102.5),
    "CAN1 bus + per-board power pass-through": (103.0, 149.0),
    "M3 pattern 30.0 x 30.0 mm (from PX4FMUv2.4.5.brd)": (103.0, 151.5),
    "R409: populate on END modules only - desolder on the middle one": (103.0, 154.0),
    "Verify ~60R across CAN_H/CAN_L, bus unpowered": (103.0, 156.5),
}


def move_texts(text):
    moved = 0
    for body, (x, y) in TEXT_MOVES.items():
        pat = (r'(\(gr_text "' + re.escape(body) + r'"\s*\n\s*\(at )'
               r'[-\d.]+ [-\d.]+( [-\d.]+)?(\))')
        text, n = re.subn(pat, lambda m: f"{m.group(1)}{x} {y} 0{m.group(3)}",
                          text, count=1)
        moved += n
    return text, moved


def reposition(text):
    """Move each footprint to its planned spot.

    The footprint's own `(at ...)` is the first one inside the block; pads have
    their own. Rewriting the wrong one would move a single pad and leave the
    part where it was, so this only touches the first, and only at footprint
    indent level.
    """
    out, pos, moved = [], 0, 0
    for m in re.finditer(r'\t\(footprint "[^"]+"', text):
        start = m.start()
        depth, j, instr, esc = 0, start, False, False
        while j < len(text):
            c = text[j]
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
        blk = text[start:j + 1]
        rm = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if rm and rm.group(1) in PLACE:
            x, y = PLACE[rm.group(1)]
            new, n = re.subn(r'\n\t\t\(at [-\d.]+ [-\d.]+( [-\d.]+)?\)',
                             f'\n\t\t(at {x} {y})', blk, count=1)
            if n:
                blk = new
                moved += 1
        out.append(text[pos:start])
        out.append(blk)
        pos = j + 1
    out.append(text[pos:])
    return "".join(out), moved


def strip_existing(text):
    """Drop any previous copper so re-running is idempotent."""
    for tok in ("segment", "via", "zone"):
        while True:
            m = re.search(r'\t\(' + tok + r'\n', text)
            if not m:
                break
            depth, j, instr, esc = 0, m.start(), False, False
            while j < len(text):
                c = text[j]
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
            text = text[:m.start()] + text[j + 2:]
    return text


def route():
    out = []

    # CAN: one straight run per signal down the column of three connectors.
    for pin, net in ((2, "CAN_H"), (3, "CAN_L")):
        x = X_CAN + PITCH * (pin - 1)
        for a, b in zip(ROWS, ROWS[1:]):
            out.append(seg(x, a, x, b, W_SIG, "F.Cu", net))

    # Power: brick in -> module out, one board at a time.
    for i, (b, y) in enumerate(zip("ABC", ROWS)):
        # pins 1+2 are the same rail, pins 5+6 the same ground - tie the pairs
        out.append(seg(X_IN, y, X_IN + PITCH, y, W_PWR, "F.Cu", f"/VBRICK_{b}"))
        out.append(seg(X_OUT, y, X_OUT + PITCH, y, W_PWR, "F.Cu", f"/VBRICK_{b}"))
        for pin, base, off, w in POWER:
            net = f"/{base}_{b}" if base != "VBRICK" else f"/VBRICK_{b}"
            xa = X_IN + PITCH * (pin - 1)
            xb = X_OUT + PITCH * (pin - 1)
            ya = y - off
            out.append(seg(xa, y, xa, ya, w, "F.Cu", net))
            out.append(via(xa, ya, net))
            out.append(seg(xa, ya, xb, ya, w, "B.Cu", net))
            out.append(via(xb, ya, net))
            out.append(seg(xb, ya, xb, y, w, "F.Cu", net))

    # Ground, routed explicitly rather than left to the pours. A zone that
    # fails to fill conducts nothing while still looking poured, so the board
    # is made correct by copper and the planes are a bonus on top.
    #
    # Run as three vertical trunks joined by one horizontal link, because a
    # horizontal run at pin height would cross the power stubs leaving the
    # module-side connectors, and one at row+3 would land inside an M3 keepout.
    Y_LINK = 133.0                      # between rows B and C, clear of holes
    for x in (X_CAN + PITCH * 3, X_IN + PITCH * 4, X_OUT + PITCH * 4):
        for a, b in zip(ROWS, ROWS[1:]):
            out.append(seg(x, a, x, b, W_SIG, "F.Cu", "GND"))
    for y in ROWS:                      # tie each connector's two ground pins
        out.append(seg(X_IN + PITCH * 4, y, X_IN + PITCH * 5, y, W_SIG, "F.Cu", "GND"))
        out.append(seg(X_OUT + PITCH * 4, y, X_OUT + PITCH * 5, y, W_SIG, "F.Cu", "GND"))
    out.append(seg(X_CAN + PITCH * 3, Y_LINK, X_IN + PITCH * 4, Y_LINK,
                   W_SIG, "F.Cu", "GND"))
    out.append(seg(X_IN + PITCH * 4, Y_LINK, X_OUT + PITCH * 4, Y_LINK,
                   W_SIG, "F.Cu", "GND"))

    out.append(zone("F.Cu"))
    out.append(zone("B.Cu"))
    return out


def main():
    text = PCB.read_text(encoding="utf-8")
    if '(footprint "Connector_Hirose' not in text:
        raise SystemExit(
            "no connectors on the board - run Tools > Update PCB from Schematic "
            "(F8) in KiCad first")

    text = strip_existing(text)
    text, moved = reposition(text)
    text, texts_moved = move_texts(text)

    copper = route()
    close = text.rindex(")")
    text = text[:close] + "\n".join(copper) + "\n" + text[close:]
    PCB.write_text(text, encoding="utf-8")

    print(f"  repositioned {moved} footprints, {texts_moved} silkscreen texts")
    print(f"  laid {sum(1 for c in copper if c.startswith(chr(9) + '(segment'))} segments, "
          f"{sum(1 for c in copper if c.startswith(chr(9) + '(via'))} vias, "
          f"2 ground zones")
    print(f"  wrote {PCB.relative_to(REPO)}")
    print("\n  verify:  kicad-cli pcb drc hardware/carrier/carrier.kicad_pcb")


if __name__ == "__main__":
    main()
