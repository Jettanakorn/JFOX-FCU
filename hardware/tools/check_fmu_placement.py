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

EDGE_PARTS = {"J31": "microSD - the card has to be reachable without "
                     "dismantling the aircraft"}
EDGE_TOL = 12.0     # centre-to-edge; the DM3AT is ~15 mm deep


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

    xs, ys = [], []
    for m in re.finditer(r'\(gr_(?:line|arc) \(start ([-\d.]+) ([-\d.]+)\)'
                         r'[^)]*\(end ([-\d.]+) ([-\d.]+)\)', t):
        a, b, c, d = map(float, m.groups())
        xs += [a, c]
        ys += [b, d]
    if not xs:
        sys.exit("no board outline found")
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
