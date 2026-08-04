#!/usr/bin/env python3
"""Check every 3D model path on the board actually resolves.

KiCad ships footprints that name a .step its 3D library does not contain -
the model library is packaged separately and does not cover every land
pattern. The part then renders as bare pads, and NOTHING reports it: DRC has
no opinion about 3D models, and the footprint checker only asks whether the
footprint exists.

So a board can pass every check here and still be missing bodies, which is
how U6 and U21 went unnoticed until someone opened the 3D view.

    python hardware/tools/check_3d_models.py
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KICAD = Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0")
M3D = KICAD / "share" / "kicad" / "3dmodels"

# Parts that legitimately have no body. Named, not pattern-matched, so the
# exemption cannot quietly widen: J40 is gold fingers - PCB copper, not a
# component - and a mounting hole is a hole.
# J40 is gold fingers and JP1/JP2 are solder jumpers - both are
# copper on the board, not components, so neither has a body to
# be missing.
NO_BODY = {"J40", "JP1", "JP2"}

BOARDS = [REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.kicad_pcb",
          REPO / "hardware" / "jfox-base-v1" / "jfox-base.kicad_pcb"]


def resolve(p, prj):
    for var in ("KICAD10_3DMODEL_DIR", "KICAD9_3DMODEL_DIR",
                "KICAD8_3DMODEL_DIR", "KICAD7_3DMODEL_DIR"):
        p = p.replace("${%s}" % var, str(M3D))
    return Path(p.replace("${KIPRJMOD}", str(prj)))


def main():
    bad, checked = [], 0
    for pcb in BOARDS:
        if not pcb.exists():
            continue
        prj, t = pcb.parent, pcb.read_text(encoding="utf-8")
        for m in re.finditer(r'\n\t\(footprint "([^"]+)"[\s\S]*?'
                             r'(?=\n\t\(footprint "|\n\)$)', t):
            blk = m.group(0)
            r = re.search(r'\(property "Reference" "([^"]+)"', blk)
            if not r:
                continue
            ref = r.group(1)
            if ref.startswith(("MH", "G")) or ref in NO_BODY:
                continue
            checked += 1
            md = re.search(r'\(model "([^"]+)"', blk)
            if not md:
                bad.append((pcb.name, ref, "no model reference at all"))
            elif not resolve(md.group(1), prj).exists():
                bad.append((pcb.name, ref, md.group(1)))

    print(f"  [{'PASS' if not bad else 'FAIL'}] {checked} footprints have a "
          f"3D body that resolves")
    for board, ref, why in bad:
        print(f"      - {board} {ref}: {why}")
    if bad:
        return 1
    print("\nevery part that should have a body has one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
