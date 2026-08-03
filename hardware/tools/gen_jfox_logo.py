#!/usr/bin/env python3
"""Turn the JFOX logo into a KiCad silkscreen footprint.

Why not bitmap2component
------------------------

KiCad ships it and it is the obvious tool, but it is a GUI application: it
hangs on `--help` with no console output, because it opens a window and
waits. Not usable from a script, so the conversion is done here.

Why the alpha channel
---------------------

The source is white artwork on a transparent background. That is right for a
presentation and wrong for a PCB twice over:

  * A tracer reads DARK pixels as the shape. White-on-transparent flattens
    to white-on-white and converts to nothing at all.
  * The ALPHA channel carries the artwork. The RGB planes are uniform white
    wherever anything is drawn, so thresholding on brightness discards the
    logo and keeps the background.

So alpha is extracted and inverted: opaque becomes the shape.

Why rectangles rather than contours
-----------------------------------

A contour tracer gives fewer, prettier polygons and has to solve holes -
KiCad's fp_poly has no hole primitive, so an inner contour would be filled
in and this logo is mostly inner contours. Decomposing into maximal
rectangles handles holes for free, because a hole is simply an absence of
rectangles. It costs polygon count, which silkscreen does not care about.

Why it is reduced first
-----------------------

Silkscreen resolves about 0.15 mm. A 1860 px logo at 20 mm is ~90 px/mm, so
the dashed detail inside the wings and the thin outline strokes cannot
print and would come back as broken speckle. Reducing before tracing turns
detail that cannot print into detail that is not there - a decision better
made here than by the plotter.

    python hardware/tools/gen_jfox_logo.py [--width-mm 20]

Writes hardware/jfox-fmu-v1/jfox-fmu.pretty/JFOX_Logo.kicad_mod
"""

import argparse
import sys
import uuid as _uuid
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.pretty"
SRC = REPO / "hardware" / "brand" / "jfox-logo.png"


def shape(src, width_px):
    """Binary mask from the alpha channel: True where the logo is."""
    im = Image.open(src)
    if im.mode != "RGBA":
        sys.exit(f"{src.name} is {im.mode}, expected RGBA - this reads the "
                 f"alpha channel, because that is where white artwork on a "
                 f"transparent background actually lives")
    a = im.getchannel("A")
    h = round(a.height * width_px / a.width)
    # Reduce first, then threshold. The other order thresholds detail the
    # reduction is about to average away, which produces speckle.
    a = a.resize((width_px, h), Image.LANCZOS)
    px = a.load()
    # 128, not 1: anti-aliased edges are half-transparent, and treating
    # anything non-zero as solid fattens every stroke by a pixel all round.
    return [[px[x, y] >= 128 for x in range(a.width)] for y in range(a.height)],\
           a.width, a.height


def rectangles(mask, w, h):
    """Greedy maximal-rectangle decomposition of the mask.

    Each rectangle is grown right as far as the run allows, then down as far
    as identical runs allow. Holes need no special handling - they are the
    cells no rectangle claims.
    """
    used = [[False] * w for _ in range(h)]
    out = []
    for y in range(h):
        x = 0
        while x < w:
            if not mask[y][x] or used[y][x]:
                x += 1
                continue
            x1 = x
            while x1 < w and mask[y][x1] and not used[y][x1]:
                x1 += 1
            y1 = y + 1
            while y1 < h and all(mask[y1][k] and not used[y1][k]
                                 for k in range(x, x1)):
                y1 += 1
            for yy in range(y, y1):
                for xx in range(x, x1):
                    used[yy][xx] = True
            out.append((x, y, x1, y1))
            x = x1
    return out


def main():
    ap = argparse.ArgumentParser()
    # 20 mm, not smaller. At 12 mm the "JFOX AIRCRAFT" lettering reduces to
    # unreadable mush - every stroke lands in the same pixel as its
    # neighbour - while the wings still survive. A logo whose text cannot be
    # read is worse than no logo: it looks like a printing defect.
    #
    # The printability floor below catches strokes too thin to print. This
    # catches art too small to mean anything, which is a different failure
    # and needs its own limit.
    ap.add_argument("--width-mm", type=float, default=20.0)
    ap.add_argument("--min-width-mm", type=float, default=18.0,
                    help="below this the lettering stops being legible")
    # One pixel must be at least the silkscreen minimum feature, or the
    # trace produces art the fab cannot print. At 8 px/mm a pixel is
    # 0.125 mm and 209 of 278 features came out below 0.15 - most of the
    # logo would have arrived as broken speckle. 6 px/mm gives 0.167 mm.
    ap.add_argument("--px-per-mm", type=float, default=6.0)
    ap.add_argument("--min-feature", type=float, default=0.15,
                    help="silkscreen minimum feature, mm")
    args = ap.parse_args()

    if not SRC.exists():
        sys.exit(f"missing {SRC} - put the source artwork there first")

    px = max(64, round(args.width_mm * args.px_per_mm))
    mask, w, h = shape(SRC, px)
    rects = rectangles(mask, w, h)
    if not rects:
        sys.exit("the alpha channel is empty - nothing to trace")

    s = args.width_mm / w                      # mm per pixel
    ox, oy = -args.width_mm / 2, -h * s / 2     # centre the artwork

    body = ['(footprint "JFOX_Logo"',
            '\t(version 20260206)',
            '\t(generator "jfox gen_jfox_logo")',
            '\t(generator_version "10.0")',
            '\t(layer "F.SilkS")',
            '\t(descr "JFOX Aircraft Co., Ltd. logo, front silkscreen. '
            'Generated from hardware/brand/jfox-logo-white.png - edit that '
            'and re-run gen_jfox_logo.py, do not hand-edit this file.")',
            '\t(tags "logo graphic")',
            '\t(attr board_only exclude_from_pos_files exclude_from_bom)',
            '\t(property "Reference" "G***"',
            f'\t\t(at 0 {round(oy - 1, 3)} 0)',
            '\t\t(layer "F.SilkS")',
            f'\t\t(uuid "{_uuid.uuid4()}")',
            '\t\t(hide yes)',
            '\t\t(effects (font (size 1 1) (thickness 0.15)))',
            '\t)',
            '\t(property "Value" "JFOX_Logo"',
            f'\t\t(at 0 {round(oy + h * s + 1, 3)} 0)',
            '\t\t(layer "F.Fab")',
            f'\t\t(uuid "{_uuid.uuid4()}")',
            '\t\t(hide yes)',
            '\t\t(effects (font (size 1 1) (thickness 0.15)))',
            '\t)']

    for x0, y0, x1, y1 in rects:
        ax, ay = round(ox + x0 * s, 4), round(oy + y0 * s, 4)
        bx, by = round(ox + x1 * s, 4), round(oy + y1 * s, 4)
        body += [
            '\t(fp_poly',
            '\t\t(pts',
            f'\t\t\t(xy {ax} {ay}) (xy {bx} {ay}) '
            f'(xy {bx} {by}) (xy {ax} {by})',
            '\t\t)',
            '\t\t(stroke (width 0) (type solid))',
            '\t\t(fill yes)',
            '\t\t(layer "F.SilkS")',
            f'\t\t(uuid "{_uuid.uuid4()}")',
            '\t)']
    body.append(')')

    LIB.mkdir(parents=True, exist_ok=True)
    out = LIB / "JFOX_Logo.kicad_mod"
    out.write_text("\n".join(body) + "\n", encoding="utf-8")

    # A pixel IS the smallest feature this can produce, so check it against
    # what the process can print rather than hoping. Silkscreen art below
    # the minimum does not come back thin - it comes back broken.
    if args.width_mm < args.min_width_mm - 1e-9:
        sys.exit(f"{args.width_mm:g} mm is below the {args.min_width_mm:g} mm "
                 f"legibility floor - the lettering will not be readable. "
                 f"Use the emblem-only artwork if the space is fixed, or "
                 f"pass --min-width-mm to override deliberately.")

    if s < args.min_feature - 1e-9:
        sys.exit(f"one pixel is {s:.3f} mm but silkscreen resolves "
                 f"{args.min_feature:.3f} mm - at {args.px_per_mm:g} px/mm "
                 f"most of this logo would not print. Use "
                 f"--px-per-mm {1 / args.min_feature:.1f} or lower, or make "
                 f"the logo wider.")

    print(f"  traced {w} x {h} px -> {len(rects)} rectangle(s)")
    print(f"  thinnest feature {s:.3f} mm (silkscreen min "
          f"{args.min_feature:.2f})")
    print(f"  {args.width_mm:.1f} x {h * s:.1f} mm at {args.px_per_mm:.0f} px/mm")
    print(f"  wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
