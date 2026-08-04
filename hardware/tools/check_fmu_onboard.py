#!/usr/bin/env python3
"""Check every footprint is actually on the board.

Nothing else checks this. DRC has no rule for a part sitting off the edge -
it checks clearances between things, and two things in mid-air are perfectly
clear of each other. The layout scorer measures against the bounding box,
and once the card grew a tongue the bounding box stopped describing the
shape: the last 10 mm of it is 39.85 mm wide, not 48, so a part can be
inside the box and off the board by 20 mm.

That is how U6 and its decoupling ended up floating beside the tongue on a
board reporting zero DRC violations and a clean layout score. The failure
was invisible to every tool here, and was caught by a person looking at a
render - which is not a process.

    python hardware/tools/check_fmu_onboard.py

Exits non-zero if any footprint is outside the board.
"""

import math
import re
import sys
from pathlib import Path

import kicad_geom

REPO = Path(__file__).resolve().parents[2]
PCB = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.kicad_pcb"

# The card-edge connector defines the tongue, so its courtyard sits a
# fraction proud of it by construction - the courtyard carries a margin the
# copper does not. Exempt, and named rather than pattern-matched so the
# exemption cannot quietly widen.
DEFINES_OUTLINE = {"J40"}


def segments(t):
    """Edge.Cuts as a list of (x1, y1, x2, y2)."""
    out = []
    for tok in ("gr_line", "gr_arc", "gr_rect"):
        for e in kicad_geom.sexprs(t, tok):
            if '(layer "Edge.Cuts")' not in e:
                continue
            pts = [(float(a), float(b)) for a, b in re.findall(
                r'\((?:start|end|mid) (-?[\d.]+) (-?[\d.]+)\)', e)]
            for i in range(len(pts) - 1):
                out.append((*pts[i], *pts[i + 1]))
    return out


def inside(px, py, segs):
    """Even-odd ray cast against the outline.

    Works on any shape the outline actually is, which is the entire point -
    a bounding-box test passes a part that is 20 mm off the side of a
    tongue.
    """
    n = 0
    for x1, y1, x2, y2 in segs:
        if (y1 > py) != (y2 > py):
            xi = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if xi > px:
                n += 1
    return n % 2 == 1


def main():
    if not PCB.exists():
        sys.exit(f"missing {PCB} - run gen_fmu_pcb.py first")
    t = PCB.read_text(encoding="utf-8")
    segs = segments(t)
    if not segs:
        sys.exit("no board outline - nothing to check against")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import score_fmu_layout as S
    parts, _pads, _outline = S.parse(PCB)

    bad = []
    for ref, (px, py, w, h, ox, oy, side) in sorted(parts.items()):
        # A part that DEFINES the outline is forgiven a small overhang - its
        # courtyard carries a margin the copper does not - but not being off
        # the board. The blanket exemption hid exactly that: the outline was
        # cutting away the whole gold-finger area and this check said PASS.
        tol = 1.0 if ref in DEFINES_OUTLINE else 0.0
        # All four courtyard corners plus the centre. A part is off the
        # board if any corner is, not only if its middle is.
        l, r, tp, b = px + ox, px + ox + w, py + oy, py + oy + h
        pts = [(l + tol, tp + tol), (r - tol, tp + tol),
               (l + tol, b - tol), (r - tol, b - tol),
               ((l + r) / 2, (tp + b) / 2)]
        off = [p for p in pts if not inside(p[0], p[1], segs)]
        if off:
            bad.append((ref, side, l, r, tp, b, len(off)))

    print(f"  [{'PASS' if not bad else 'FAIL'}] {len(parts)} footprints "
          f"inside the board outline")
    for ref, side, l, r, tp, b, n in bad:
        print(f"      - {ref} [{side}] x {l:.2f}..{r:.2f} y {tp:.2f}..{b:.2f} "
              f"- {n} of 5 test points are off the board")
    if bad:
        return 1
    print("\nevery part is on the board, tongue and all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
