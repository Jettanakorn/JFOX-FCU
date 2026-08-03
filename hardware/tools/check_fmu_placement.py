#!/usr/bin/env python3
"""Check sensor placement against the things that make noise.

"Keep the sensors away from the noise" is the kind of instruction that is
obviously right, impossible to argue with, and completely untestable as
written. This measures it.

Every sensitive part has a minimum distance from every noise source, and the
distances are here with the reason for each. They are engineering judgement,
not datasheet numbers - no manufacturer publishes "keep 25 mm from a
switching regulator" - so they are stated as judgement and can be argued with
on the evidence. What they are not is invisible.

Also checks the microSD socket sits on a board edge. A card slot in the
middle of a board is a card you cannot change without dismantling the
aircraft.

    python hardware/tools/check_fmu_placement.py

Exits non-zero if a sensor is too close to a noise source.
"""

import math
import re
import sys
from pathlib import Path

import kicad_geom

REPO = Path(__file__).resolve().parents[2]
PCB = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.kicad_pcb"

# --------------------------------------------------------------------------
# Noise sources, and why each one is one.
# --------------------------------------------------------------------------
NOISE = {
    "U21": "TPS62132 buck - switches at 2.5 MHz, the board's primary emitter",
    "L1":  "buck inductor - the switch-node loop's magnetic field",
    "U30": "ISOW1044 - integrated isolated converter running at 25 MHz",
    "U31": "ISOW1044 - integrated isolated converter running at 25 MHz",
    "U23": "load switch - current step when a sensor rail is cycled",
    "U24": "load switch",
    "U25": "load switch",
    "U26": "load switch",
}

# --------------------------------------------------------------------------
# Sensitive parts, minimum clearance in mm, and the mechanism that makes each
# one sensitive. Different mechanisms, so different distances.
# --------------------------------------------------------------------------
SENSITIVE = {
    # A magnetometer measures exactly what a switching converter emits. This
    # is the largest number on the board and the reason U6 is placed by hand
    # in the far corner rather than packed.
    "U6": (25.0, "BMM150 magnetometer - measures the field a switcher makes"),
    # Gyro bias walks with temperature, and a buck dissipating a watt is a
    # thermal gradient as much as an electrical one.
    "U1": (15.0, "ICM-42688-P - gyro bias drifts with thermal gradient"),
    "U2": (15.0, "ICM-45686 - gyro bias drifts with thermal gradient"),
    "U3": (15.0, "BMI088 - gyro bias drifts with thermal gradient"),
    # A barometer near a heat source reads the heat source. Self-heating
    # shows up directly as an altitude error.
    "U4": (15.0, "BMP388 - self-heating reads as an altitude error"),
    "U7": (15.0, "ICP-20100 - self-heating reads as an altitude error"),
    # Oscillator pulling. Less critical than the magnetometer, still real.
    "X1": (10.0, "16 MHz HSE - injected noise pulls the oscillator"),
    "X2": (10.0, "32.768 kHz LSE - low amplitude, easily disturbed"),
}

# Every harness connector, not just the card slot. This listed J31 alone,
# so it passed while J6, J12 and J13 sat 30 mm inland - the check reported
# "1 edge-mounted part reaches a board edge" and that was true and useless.
# A guard that covers one of five cases reads exactly like a guard.
#
# J40 is deliberately absent: the mezzanine mates vertically against the
# carrier and belongs in the middle of the board.
EDGE_PARTS = {
    "J31": "microSD - the card has to be reachable without dismantling the "
           "aircraft",
    # J6 moved to the backplane (J52) in the card-cage refactor. One debug
    # port serves the set; SWD reaches each card over its gold fingers. A
    # checker that still demands it here would fail forever on a board that
    # is correct.
    "J12": "isolated CAN1 harness",
    "J13": "isolated CAN2 harness",
    "J30": "USB-C - a cable has to reach it",
}
# Centre-to-edge, so the tolerance has to cover the deepest part in the set:
# the DM3AT card slot is ~15 mm front to back, giving a centre ~9 mm in.
EDGE_TOL = 12.0


def positions():
    """{ref: (x, y)} and the board outline extent, from the .kicad_pcb."""
    t = PCB.read_text(encoding="utf-8")
    pos = {}
    for m in re.finditer(
            r'\(footprint "[^"]+"\s*\n\s*\(layer "[^"]+"\)\s*\n'
            r'\s*\(uuid "[^"]+"\)\s*\n\s*\(at ([-\d.]+) ([-\d.]+)\)'
            r'[\s\S]{0,4000}?\(property "Reference" "([^"]+)"', t):
        x, y, ref = float(m.group(1)), float(m.group(2)), m.group(3)
        pos.setdefault(ref, (x, y))

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
    return pos, (min(xs), min(ys), max(xs), max(ys))


def main():
    if not PCB.exists():
        sys.exit(f"missing {PCB} - run gen_fmu_pcb.py first")
    pos, (x0, y0, x1, y1) = positions()

    fails, worst = [], []
    for ref, (need, why) in SENSITIVE.items():
        if ref not in pos:
            fails.append(f"{ref} is not placed")
            continue
        sx, sy = pos[ref]
        near = None
        for nref, nwhy in NOISE.items():
            if nref not in pos:
                continue
            nx, ny = pos[nref]
            d = math.hypot(sx - nx, sy - ny)
            if near is None or d < near[0]:
                near = (d, nref, nwhy)
            if d < need:
                fails.append(
                    f"{ref} is {d:.1f} mm from {nref} (needs {need:.0f} mm) - "
                    f"{why}; {nref} is {nwhy}")
        if near:
            worst.append((near[0] - need, ref, near[0], near[1], need))

    print(f"  [{'PASS' if not fails else 'FAIL'}] "
          f"{len(SENSITIVE)} sensitive parts clear of "
          f"{len(NOISE)} noise sources")
    for f in fails:
        print("      -", f)

    worst.sort()
    print("\n  closest approach per sensitive part:")
    for margin, ref, d, nref, need in worst:
        flag = "  <-- tight" if 0 <= margin < 5 else ""
        print(f"      {ref:<4} {d:>6.1f} mm to {nref:<4} "
              f"(needs {need:>4.0f}, margin {margin:>+6.1f}){flag}")

    # --- edge-mounted parts -----------------------------------------------
    ebad = []
    for ref, why in EDGE_PARTS.items():
        if ref not in pos:
            ebad.append(f"{ref} is not placed")
            continue
        px, py = pos[ref]
        d = min(px - x0, x1 - px, py - y0, y1 - py)
        if d > EDGE_TOL:
            ebad.append(f"{ref} is {d:.1f} mm from the nearest edge "
                        f"(needs <= {EDGE_TOL:.0f}) - {why}")
    print(f"\n  [{'PASS' if not ebad else 'FAIL'}] "
          f"{len(EDGE_PARTS)} edge-mounted part(s) reach a board edge")
    for e in ebad:
        print("      -", e)

    if fails or ebad:
        return 1
    print("\nsensor placement clears every noise source it needs to")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
