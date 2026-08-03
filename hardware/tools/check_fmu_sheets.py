#!/usr/bin/env python3
"""Check that every sheet's drawing actually fits on its page.

The generator has its own fit check, but it measures the s-expression it is
about to write: anchor points, plus an *estimate* of how wide each label's
text will render. Estimates of text are exactly the kind of thing that is
right until it is not.

This measures the opposite end. It asks KiCad to plot each sheet with
`--exclude-drawing-sheet`, which draws the circuit and nothing else - no
frame, no title block - and then measures the geometry KiCad actually
emitted. Text is already converted to strokes by then, so a label that
renders wider than predicted has nowhere to hide.

Content must sit inside the frame (12..198 x 12..285 on A4 portrait) and must
not run under the title block (x >= 90, y >= 253).

    python hardware/tools/check_fmu_sheets.py

Exits non-zero if anything overflows.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
ROOT = BOARD / "jfox-fmu.kicad_sch"

FRAME = (12.0, 12.0, 198.0, 285.0)
TITLE_BLOCK = (90.0, 253.0)

CLI = next((str(c) for c in (
    Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"),
    Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")) if c.exists()), None)

NUM = r'-?\d*\.?\d+(?:[eE][-+]?\d+)?'
TOKEN = re.compile(rf'([MmLlHhVvCcSsQqTtAaZz])|({NUM})')

# How many numbers each SVG path command takes, and which of them are a
# coordinate pair. Arc is the one that matters: `A rx ry rot large sweep x y`
# carries seven numbers of which only the last two are a point. Pairing them
# up blindly - which is what a bare number-scraper does - turns the two
# boolean flags into a phantom vertex at (0, 0) and reports every sheet
# containing a rounded connector as overflowing off the top left corner.
ARITY = {"M": 2, "L": 2, "T": 2, "H": 1, "V": 1,
         "C": 6, "S": 4, "Q": 4, "A": 7, "Z": 0}


def path_points(d):
    """Every real vertex in an SVG path, absolute coordinates."""
    toks = TOKEN.findall(d)
    pts, i, cmd, cur = [], 0, "M", (0.0, 0.0)
    nums = []
    seq = []
    for c, n in toks:
        seq.append(("c", c) if c else ("n", float(n)))
    i = 0
    while i < len(seq):
        kind, val = seq[i]
        if kind == "c":
            cmd = val
            i += 1
            if cmd.upper() == "Z":
                continue
        n = ARITY[cmd.upper()]
        nums = []
        while len(nums) < n and i < len(seq) and seq[i][0] == "n":
            nums.append(seq[i][1])
            i += 1
        if len(nums) < n:
            break
        rel = cmd.islower()
        up = cmd.upper()
        if up == "H":
            x = cur[0] + nums[0] if rel else nums[0]
            cur = (x, cur[1])
        elif up == "V":
            y = cur[1] + nums[0] if rel else nums[0]
            cur = (cur[0], y)
        else:
            x, y = nums[-2], nums[-1]
            cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
        pts.append(cur)
    return pts


def extents(svg):
    t = svg.read_text(encoding="utf-8")
    pts = []
    for d in re.findall(r'\sd="([^"]*)"', t):
        pts += path_points(d)
    for m in re.finditer(
            r'<rect x="(-?[\d.]+)" y="(-?[\d.]+)" '
            r'width="([\d.]+)" height="([\d.]+)"', t):
        x, y, w, h = map(float, m.groups())
        pts += [(x, y), (x + w, y + h)]
    for m in re.finditer(r'<circle cx="(-?[\d.]+)" cy="(-?[\d.]+)" r="([\d.]+)"', t):
        x, y, r = map(float, m.groups())
        pts += [(x - r, y - r), (x + r, y + r)]
    return pts


def main():
    if CLI is None:
        sys.exit("kicad-cli not found")
    if not ROOT.exists():
        sys.exit(f"missing {ROOT} - run gen_fmu_schematic.py first")

    tmp = Path(tempfile.mkdtemp(prefix="jfox-sheets-"))
    try:
        r = subprocess.run(
            [CLI, "sch", "export", "svg", "-e", "-n", "-o", str(tmp), str(ROOT)],
            capture_output=True, text=True)
        svgs = sorted(tmp.glob("*.svg"))
        if not svgs:
            sys.exit(f"no SVG produced:\n{r.stdout}\n{r.stderr}")

        x0f, y0f, x1f, y1f = FRAME
        tbx, tby = TITLE_BLOCK
        bad = 0
        for s in svgs:
            pts = extents(s)
            if not pts:
                print(f"  {s.stem:<24} empty")
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            errs = []
            if min(xs) < x0f:
                errs.append(f"{x0f - min(xs):.1f}mm past the left edge")
            if max(xs) > x1f:
                errs.append(f"{max(xs) - x1f:.1f}mm past the right edge")
            if min(ys) < y0f:
                errs.append(f"{y0f - min(ys):.1f}mm above the top edge")
            if max(ys) > y1f:
                errs.append(f"{max(ys) - y1f:.1f}mm below the bottom edge")
            over = [p for p in pts if p[0] > tbx and p[1] > tby]
            if over:
                errs.append(f"{len(over)} points under the title block")
            print(f"  {s.stem:<24} x {min(xs):>6.1f}..{max(xs):<6.1f} "
                  f"y {min(ys):>6.1f}..{max(ys):<6.1f}  "
                  + ("OK" if not errs else "OVERFLOW"))
            for e in errs:
                print(f"      - {e}")
            bad += bool(errs)
        print(f"  [{'PASS' if not bad else 'FAIL'}] "
              f"all {len(svgs)} sheets fit inside the frame and clear the "
              f"title block")
        print()
        if bad:
            print(f"{bad} sheet(s) do not fit the page")
            return 1
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
