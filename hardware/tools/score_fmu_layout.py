#!/usr/bin/env python3
"""Score a placement, so "iterate until it is good" means something.

"Loop until you get the best result" needs a definition of best, or the loop
is just churn. This is that definition: six measurable criteria, each with a
target taken from ordinary PCB practice, combined into one number that is
lower when the board is better.

    python hardware/tools/score_fmu_layout.py

Prints the breakdown and the total. gen_fmu_pcb.py calls score() directly and
keeps the best arrangement it finds.

The criteria, and why each one is here:

  mcu_offset      The MCU wants to be near the centre. Almost every net on
                  the board terminates at it, so its position sets the total
                  length of everything else.
  conn_edge       A connector not on an edge is a connector you cannot plug
                  into. Measured as the distance from each connector's
                  courtyard to the nearest board edge.
  decap_reach     Decoupling that is not next to the pin it serves is not
                  decoupling - the loop inductance is the whole point. This
                  is the criterion the first placement failed worst.
  sensor_clear    Sensitive parts away from switching sources; the same
                  distances check_fmu_placement.py enforces, scored rather
                  than pass/fail so improvement is visible.
  net_length      Sum of the straight-line spans of every net. A proxy for
                  routability - not exact, but strongly correlated and cheap.
  overlap         Courtyard collisions. Weighted heavily: a board with
                  overlapping parts is not a placement at all.
"""

import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import kicad_geom

REPO = Path(__file__).resolve().parents[2]
PCB = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.kicad_pcb"

NOISE = ("U21", "L1", "U30", "U31", "U23", "U24", "U25", "U26")
SENSITIVE = {"U6": 25.0, "U1": 15.0, "U2": 15.0, "U3": 15.0,
             "U4": 15.0, "U7": 15.0, "X1": 10.0, "X2": 10.0}
# Harness connectors only. J40 is the board-to-board mezzanine: it
# mates vertically against the carrier, so it belongs in the middle of
# the board, and scoring it as "38 mm from an edge" penalised the one
# position it should actually be in.
CONNECTORS = ("J6", "J12", "J13", "J30", "J31")

# How much each criterion contributes. Overlap dominates because it is
# disqualifying rather than merely undesirable.
WEIGHT = {
    "overlap": 200.0,
    "conn_edge": 8.0,
    "decap_reach": 4.0,
    "mcu_offset": 3.0,
    "sensor_clear": 2.0,
    "net_length": 0.02,
}


def parse(path=PCB):
    """Footprint positions, courtyard extents, pad nets, and the outline."""
    t = path.read_text(encoding="utf-8")
    parts, pads = {}, defaultdict(list)

    for m in re.finditer(r'\n\t\(footprint "([^"]+)"\s*\n\s*\(layer "([^"]+)"\)'
                         r'\s*\n\s*\(uuid "[^"]+"\)\s*\n\s*\(at '
                         r'([-\d.]+) ([-\d.]+)\)', t):
        start = m.start()
        depth, i, instr, esc = 0, start + 2, False, False
        while i < len(t):
            c = t[i]
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
            i += 1
        blk = t[start:i + 1]
        ref = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if not ref:
            continue
        ref = ref.group(1)
        x, y = float(m.group(3)), float(m.group(4))

        # Courtyard extent, via the shared parser. Read with a regex
        # here twice, and wrong both times - the second version measured an
        # 0402 as a zero-height sliver and this scorer then reported zero
        # overlaps on a board DRC found 123 collisions in. A measurement
        # with a silent fallback fails the same way a check that stops
        # seeing failures does: the number keeps arriving, and stops
        # meaning anything.
        # Board-only artwork - the logo - has no courtyard and no pads by
        # definition. It is not a placement subject, so it is skipped
        # rather than measured. The guard below is right for a component
        # and wrong for a graphic, and it took down the whole scorer.
        # Artwork, not a component: no pads means nothing to
        # connect and nothing to place around. Keying off the
        # board_only attribute did not work - it does not
        # survive into the board file - and "has no pads" is a
        # property of the thing itself rather than a label on it.
        if "(pad " not in blk:
            continue
        try:
            ox, oy, w, h = kicad_geom.extent(blk)
        except ValueError:
            raise SystemExit(f"{ref}: no courtyard and no pads - refusing "
                             f"to score it against a made-up size")
        parts[ref] = (x, y, w, h, ox, oy, m.group(2)[0])

        # (net ...) comes BEFORE (at ...) in a pad, not after. Reading
        # them the other way round silently matched nothing - which
        # surfaced as decap_reach 0.00 and 3.9 mm of total net length on
        # a board with 931 netted pads. Both obviously wrong, which is
        # the only reason it was noticed.
        pad_re = (r'\(pad "[^"]+"[^\n]*\n\s*'
                  r'\(net \d+ "([^"]*)"\)\s*\n\s*'
                  r'\(at (-?[\d.]+) (-?[\d.]+)')
        for pm in re.finditer(pad_re, blk):
            pads[pm.group(1)].append((ref, x + float(pm.group(2)),
                                      y + float(pm.group(3))))

    # Read with the balanced-bracket parser, not a regex. KiCad rewrites the
    # board into canonical multi-line form, so `(gr_line (start ...)` on one
    # line stops existing and a single-line regex matches NOTHING - which is
    # exactly what happened here. The old code then fell back to a
    # hard-coded (0, 0, 100, 80), so every edge measurement on a 48 x 90
    # board was taken against an imaginary one, and reported a number the
    # whole time.
    xs, ys = [], []
    for tok in ("gr_line", "gr_arc", "gr_rect"):
        for e in kicad_geom.sexprs(t, tok):
            if '(layer "Edge.Cuts")' not in e:
                continue
            for mm in re.finditer(r'\((?:start|end|mid) '
                                  r'(-?[\d.]+) (-?[\d.]+)\)', e):
                xs.append(float(mm.group(1)))
                ys.append(float(mm.group(2)))
    if not xs:
        raise SystemExit("no board outline found - refusing to measure edge "
                         "distances against a guess")
    outline = (min(xs), min(ys), max(xs), max(ys))
    return parts, pads, outline


def score(parts, pads, outline, verbose=False):
    x0, y0, x1, y1 = outline
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    m = {}

    # --- MCU centrality ----------------------------------------------------
    if "U10" in parts:
        px, py, w, h, ox, oy, _ = parts["U10"]
        m["mcu_offset"] = math.hypot(px + ox + w / 2 - cx,
                                     py + oy + h / 2 - cy)
    else:
        m["mcu_offset"] = 999.0

    # --- connectors on an edge --------------------------------------------
    tot = 0.0
    for ref in CONNECTORS:
        if ref not in parts:
            continue
        px, py, w, h, ox, oy, _ = parts[ref]
        l, r = px + ox, px + ox + w
        tp, b = py + oy, py + oy + h
        tot += max(0.0, min(l - x0, x1 - r, tp - y0, y1 - b))
    m["conn_edge"] = tot

    # --- decoupling next to what it decouples ------------------------------
    # Every capacitor's distance to the nearest pin of the IC it shares a
    # supply net with. Not exact - a cap on +3V3 could serve any of them -
    # but the nearest is the one it is actually decoupling.
    ics = {r for r in parts if re.match(r'^U\d', r)}
    tot, n = 0.0, 0
    for ref, (px, py, w, h, ox, oy, _) in parts.items():
        if not re.match(r'^C\d', ref):
            continue
        mine = [nm for nm, pl in pads.items()
                if any(p[0] == ref for p in pl)]
        best = None
        for nm in mine:
            for pr, qx, qy in pads.get(nm, []):
                if pr in ics:
                    d = math.hypot(px - qx, py - qy)
                    best = d if best is None else min(best, d)
        if best is not None:
            tot += best
            n += 1
    m["decap_reach"] = tot / max(1, n)

    # --- sensors clear of switchers ---------------------------------------
    pen = 0.0
    for ref, need in SENSITIVE.items():
        if ref not in parts:
            continue
        sx, sy = parts[ref][0], parts[ref][1]
        for nref in NOISE:
            if nref not in parts:
                continue
            nx, ny = parts[nref][0], parts[nref][1]
            d = math.hypot(sx - nx, sy - ny)
            if d < need:
                pen += (need - d)
    m["sensor_clear"] = pen

    # --- net span ----------------------------------------------------------
    tot = 0.0
    for nm, pl in pads.items():
        if len(pl) < 2 or nm in ("GND", "+3V3", "+5V"):
            continue
        xs = [p[1] for p in pl]
        ys = [p[2] for p in pl]
        tot += (max(xs) - min(xs)) + (max(ys) - min(ys))
    m["net_length"] = tot

    # --- courtyard overlaps -----------------------------------------------
    # Side matters. This counted a top-side part against a bottom-side one
    # as a collision, which on a two-sided board it is not - that alone
    # accounted for 18 of the 19 reported clashes. The exception is the
    # mounting holes, which are non-plated and go straight through: a part
    # over one of those is a part that cannot be fitted, whichever side it
    # is on.
    boxes = [(r, p[0] + p[4], p[1] + p[5], p[0] + p[4] + p[2],
              p[1] + p[5] + p[3], p[6]) for r, p in parts.items()]
    clash = 0
    for i, (r1, a1, b1, c1, d1, s1) in enumerate(boxes):
        for r2, a2, b2, c2, d2, s2 in boxes[i + 1:]:
            through = r1.startswith("MH") or r2.startswith("MH")
            if s1 != s2 and not through:
                continue
            if a1 < c2 and a2 < c1 and b1 < d2 and b2 < d1:
                clash += 1
    m["overlap"] = float(clash)

    total = sum(WEIGHT[k] * v for k, v in m.items())
    if verbose:
        print(f"  {'criterion':<14} {'value':>10}  {'weight':>7} "
              f"{'contribution':>13}")
        for k in ("overlap", "conn_edge", "decap_reach", "mcu_offset",
                  "sensor_clear", "net_length"):
            print(f"  {k:<14} {m[k]:>10.2f}  {WEIGHT[k]:>7.2f} "
                  f"{WEIGHT[k]*m[k]:>13.1f}")
        print(f"  {'TOTAL':<14} {'':>10}  {'':>7} {total:>13.1f}")
    return total, m


def main():
    if not PCB.exists():
        sys.exit(f"missing {PCB}")
    parts, pads, outline = parse()
    print(f"  {len(parts)} parts, board "
          f"{outline[2]-outline[0]:.0f} x {outline[3]-outline[1]:.0f} mm\n")
    score(parts, pads, outline, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
