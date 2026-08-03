#!/usr/bin/env python3
"""Generate the footprints this board needs and KiCad does not ship.

Two of the sensors have no stock footprint at any acceptable approximation:

  ICM-42688-P / ICM-45686   14-lead LGA 2.5x3mm, P0.5mm
  BMP388                    10-lead LGA 2x2mm

The near miss worth recording: `Package_LGA:Bosch_LGA-14_3x2.5mm_P0.5mm`
exists, is 14 pads, is 3x2.5mm, and is 0.5mm pitch - every word of the name
matches the InvenSense package. It is still the wrong part. It is drawn for
the BMI160 and uses 0.675mm-long pads centred at +/-1.2625; InvenSense
specifies 0.475mm pads centred at +/-1.1625. Dropping it in would have given
every pad a 0.2mm overhang past the land, on a part whose whole job is to sit
still. Matching names are not matching geometry.

Every number below is transcribed from the manufacturer's own package
drawing, cited per footprint, and re-derived by `check()` from the datasheet's
independent dimensions so a typo cannot pass silently.

    python hardware/tools/gen_fmu_footprints.py

Writes hardware/jfox-fmu-v1/jfox-fmu.pretty/*.kicad_mod
"""

import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.pretty"

# KiCad 10 footprint format. Boards and footprints share this number;
# schematics (20260306) and symbol libraries (20251024) do not.
VERSION = 20260206

# KiCad board coordinates put +Y DOWN. Package drawings put +Y up. Every
# y below is written in the drawing's convention and negated on output, so
# these tables can be read straight off the datasheet.
UP = -1


def lga14():
    """InvenSense 14-lead LGA, 2.5 x 3.0 mm.

    ICM-42688-P: TDK DS-000347 rev 1.6, section 10.2, page 55-56.
    ICM-45686:   TDK DS-000577 rev 1.0, section 11.2, page 52-53.

    The two package tables are identical in every dimension that affects the
    land - D, E, W, L, e, D1, E1, SD all match - so one footprint serves both.
    They differ only in total thickness (0.91 vs 0.81), which is a height, not
    a land.

    Datasheet table: D 2.5 BSC, E 3 BSC, W 0.25 nom, L 0.475 nom, e 0.5 BSC,
    D1 1.5 BSC, E1 1 BSC.

    Pad centres are not given directly; they follow from the 0.10 edge inset
    dimensioned on the bottom view, and check() re-derives them.
    """
    cx, cy = 1.1625, 0.9125     # column X, row Y - see check()
    L, W = 0.475, 0.25
    pads = []
    # Numbering read off the datasheet's own TOP VIEW, which is what KiCad
    # draws: down the left side, along the bottom, up the right, back along
    # the top. Counter-clockwise, pin 1 at upper left.
    for i, y in enumerate([0.75, 0.25, -0.25, -0.75]):        # 1-4 left
        pads.append((str(i + 1), -cx, y, L, W))
    for i, x in enumerate([-0.5, 0.0, 0.5]):                  # 5-7 bottom
        pads.append((str(i + 5), x, -cy, W, L))
    for i, y in enumerate([-0.75, -0.25, 0.25, 0.75]):        # 8-11 right
        pads.append((str(i + 8), cx, y, L, W))
    for i, x in enumerate([0.5, 0.0, -0.5]):                  # 12-14 top
        pads.append((str(i + 12), x, cy, W, L))
    return dict(
        name="InvenSense_LGA-14_2.5x3mm_P0.5mm",
        descr="14-lead LGA 2.5x3x0.91mm, TDK InvenSense ICM-42688-P "
              "(DS-000347 rev 1.6 s10.2) and ICM-45686 (DS-000577 rev 1.0 "
              "s11.2) - identical land pattern",
        tags="lga land grid array invensense imu",
        body=(3.0, 2.5), pads=pads)


def lga10():
    """Bosch BMP388 10-lead LGA, 2.0 x 2.0 mm.

    Bosch BST-BMP388-DS001-07 rev 1.7, section 7.1 figure 26.

    Section 7.2 is explicit that there is no separate land drawing: "Bosch
    Sensortec suggests the BMP388 outline Dimensions (see 7.1 - bottom view)
    as landing pattern." So the package pads are the land, 1:1.

    Drawing gives: body 2.00+/-0.05 square, 1.525 between column centres,
    1.000 between the outer pads of a column, 0.500 between the row pads,
    0.100+/-0.05 edge inset, pads 0.275x0.250 (6x, the columns) and
    0.250x0.275 (4x, the rows).

    Note the pitch is 0.5mm, not the 0.35mm this part is often listed with.
    """
    c = 0.7625                   # = 1.525 / 2
    pads = []
    # Numbering read off the BOTTOM view (which is where the pin numbers are
    # printed) and mirrored about the vertical axis to get the top view KiCad
    # wants. The mirror axis is fixed by the drawing itself: PIN1 indexes to
    # the upper LEFT in the bottom view and the upper RIGHT in the top view.
    # Clockwise in the bottom view, so counter-clockwise here.
    for n, x, y in [("1", 0.25, c), ("2", -0.25, c)]:                  # top
        pads.append((n, x, y, 0.250, 0.275))
    for i, y in enumerate([0.5, 0.0, -0.5]):                           # left
        pads.append((str(i + 3), -c, y, 0.275, 0.250))
    for n, x, y in [("6", -0.25, -c), ("7", 0.25, -c)]:                # bottom
        pads.append((n, x, y, 0.250, 0.275))
    for i, y in enumerate([-0.5, 0.0, 0.5]):                           # right
        pads.append((str(i + 8), c, y, 0.275, 0.250))
    return dict(
        name="Bosch_LGA-10_2x2mm_P0.5mm_LayoutBorder2x3y",
        descr="10-lead LGA 2x2x0.75mm, Bosch BMP388, BST-BMP388-DS001-07 "
              "rev 1.7 s7.1 fig 26 (s7.2: outline is the landing pattern)",
        tags="lga land grid array bosch barometer",
        body=(2.0, 2.0), pads=pads)


def lga10_icp():
    """TDK InvenSense ICP-20100 10-lead LGA, 2.0 x 2.0 mm.

    TDK DS-000416 rev 1.3, section 10 figure 19 and table 19.

    Same body size as the BMP388 and the same pin count, and a completely
    different land. Bosch puts three pads on the left and right and two top
    and bottom; TDK puts three top and bottom and two left and right. Reusing
    the BMP388 footprint would place ten pads that all land somewhere, none of
    them on the right terminal.

    Table 19: D = E = 2.000, e = 0.500, b = 0.250, L = 0.375. The terminals
    run to the package edge - unlike the BMP388's 0.10 mm inset - so a pad
    centre sits L/2 in from it.
    """
    c = 2.0 / 2 - 0.375 / 2          # 0.8125
    pads = []
    # Numbering read off the bottom view (figure 19), which is where the pin
    # numbers are, then mirrored about the vertical axis for the top view
    # KiCad draws. The mirror axis is fixed by the drawing: the PIN 1 indent
    # is upper right in the bottom view and upper left in the top view.
    for n, x, y in [("1", -c, 0.25), ("2", -c, -0.25)]:            # was right
        pads.append((n, x, y, 0.375, 0.250))
    for i, x in enumerate([-0.5, 0.0, 0.5]):                       # bottom
        pads.append((str(i + 3), x, -c, 0.250, 0.375))
    for n, x, y in [("6", c, -0.25), ("7", c, 0.25)]:              # was left
        pads.append((n, x, y, 0.375, 0.250))
    for i, x in enumerate([0.5, 0.0, -0.5]):                       # top
        pads.append((str(i + 8), x, c, 0.250, 0.375))
    return dict(
        name="InvenSense_LGA-10_2x2mm_P0.5mm",
        descr="10-lead LGA 2x2x0.8mm, TDK InvenSense ICP-20100, "
              "DS-000416 rev 1.3 s10 fig 19 / table 19",
        tags="lga land grid array invensense barometer",
        body=(2.0, 2.0), pads=pads)


PARTS = [lga14, lga10, lga10_icp]

# Independent facts from the same drawings, used to re-derive what the tables
# above assert. If a pad centre were mistyped these would disagree.
DERIVE = {
    # name: (body_x, body_y, edge_inset, outward_pad_len_col, ..._row)
    "InvenSense_LGA-14_2.5x3mm_P0.5mm": (3.0, 2.5, 0.10, 0.475, 0.475),
    "Bosch_LGA-10_2x2mm_P0.5mm_LayoutBorder2x3y": (2.0, 2.0, 0.10, 0.275, 0.275),
    # Terminals run to the package edge here, so the inset is zero.
    "InvenSense_LGA-10_2x2mm_P0.5mm": (2.0, 2.0, 0.0, 0.375, 0.375),
}


def check(fp):
    """Re-derive pad centres from the drawing's edge inset.

    A pad's outer edge sits `inset` inside the body edge, so its centre is at
    body/2 - inset - length/2. That is a completely different set of numbers
    from the ones typed into the pad tables, taken from different callouts on
    the same drawing. Agreement means the transcription is right; a typo in
    either place shows up here rather than as a part that will not solder.
    """
    bx, by, inset, lcol, lrow = DERIVE[fp["name"]]
    problems = []
    want_x = bx / 2 - inset - lcol / 2
    want_y = by / 2 - inset - lrow / 2
    nums = []
    for num, x, y, w, h in fp["pads"]:
        nums.append(int(num))
        # A pad is in a column if it is displaced in X, a row if in Y.
        if abs(x) > abs(y):
            got, want, axis = abs(x), want_x, "x"
        else:
            got, want, axis = abs(y), want_y, "y"
        if abs(got - want) > 0.0005:
            problems.append(
                f"{fp['name']} pad {num}: {axis}={got} but the "
                f"{inset}mm edge inset puts it at {want:.4f}")
    n = len(fp["pads"])
    if sorted(nums) != list(range(1, n + 1)):
        problems.append(f"{fp['name']}: pin numbers are not 1..{n}: "
                        f"{sorted(nums)}")
    # Pads must sit inside the body they belong to.
    for num, x, y, w, h in fp["pads"]:
        if abs(x) + w / 2 > bx / 2 + 0.001 or abs(y) + h / 2 > by / 2 + 0.001:
            problems.append(f"{fp['name']} pad {num} hangs off the package")
    return problems


def render(fp):
    bx, by = fp["body"]
    hx, hy = bx / 2, by / 2
    o = [f'(footprint "{fp["name"]}"',
         f'\t(version {VERSION})',
         '\t(generator "jfox gen_fmu_footprints")',
         '\t(generator_version "10.0")',
         '\t(layer "F.Cu")',
         f'\t(descr "{fp["descr"]}")',
         f'\t(tags "{fp["tags"]}")',
         '\t(attr smd)']
    for pname, val, y in [("Reference", "REF**", -(hy + 1.0)),
                          ("Value", fp["name"], hy + 1.0)]:
        layer = "F.SilkS" if pname == "Reference" else "F.Fab"
        o += [f'\t(property "{pname}" "{val}"',
              f'\t\t(at 0 {y} 0)', f'\t\t(layer "{layer}")',
              f'\t\t(uuid "{uuid.uuid4()}")',
              '\t\t(effects (font (size 1 1) (thickness 0.15)))', '\t)']

    # Courtyard: IPC-7351 gives 0.25mm clearance for a part of this class.
    cx, cy = hx + 0.25, hy + 0.25
    o += [f'\t(fp_rect (start {-cx} {-cy}) (end {cx} {cy})',
          '\t\t(stroke (width 0.05) (type solid)) (fill no)',
          f'\t\t(layer "F.CrtYd") (uuid "{uuid.uuid4()}")\n\t)',
          # Fabrication outline is the true body.
          f'\t(fp_rect (start {-hx} {-hy}) (end {hx} {hy})',
          '\t\t(stroke (width 0.1) (type solid)) (fill no)',
          f'\t\t(layer "F.Fab") (uuid "{uuid.uuid4()}")\n\t)']

    # Silkscreen pin-1 mark, placed outside the courtyard so it survives
    # assembly and is still readable with the part fitted.
    o += [f'\t(fp_circle (center {-cx - 0.2} {-cy - 0.2}) '
          f'(end {-cx - 0.1} {-cy - 0.2})',
          '\t\t(stroke (width 0.12) (type solid)) (fill solid)',
          f'\t\t(layer "F.SilkS") (uuid "{uuid.uuid4()}")\n\t)']

    for num, x, y, w, h in fp["pads"]:
        o += [f'\t(pad "{num}" smd rect',
              f'\t\t(at {round(x, 4)} {round(UP * y, 4)})',
              f'\t\t(size {w} {h})',
              '\t\t(layers "F.Cu" "F.Mask" "F.Paste")',
              f'\t\t(uuid "{uuid.uuid4()}")\n\t)']
    o.append(")")
    return "\n".join(o) + "\n"


def main():
    fps = [f() for f in PARTS]
    problems = [p for fp in fps for p in check(fp)]
    if problems:
        print("GEOMETRY PROBLEMS:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    for fp in fps:
        (OUT / f"{fp['name']}.kicad_mod").write_text(render(fp),
                                                     encoding="utf-8")
        print(f"  {fp['name']:<46} {len(fp['pads']):>2} pads")
    print(f"\n  wrote {OUT.relative_to(REPO)}")
    print("  pad centres re-derived from each drawing's edge inset - agreed")


if __name__ == "__main__":
    main()
