#!/usr/bin/env python3
"""Generate the carrier PCB's board file: outline, mounting holes, rules.

What this does and does not do
------------------------------
It writes hardware/carrier/carrier.kicad_pcb containing the things that need
real data rather than judgement:

  * a board outline sized to carry the connectors and the module stack;
  * the four M3 mounting holes on a 30.000 x 30.000 mm pattern - taken from
    the module's own PX4FMUv2.4.5.brd (holes at x=20/50, y=-35.203/-5.203),
    not measured off a drawing, so a stacked module actually lines up;
  * a 2-layer stackup and design rules sized for this board, including a CAN
    differential-pair netclass.

It does NOT place the nine connectors or route anything. Loading a netlist
into a board is a GUI action in KiCad - `kicad-cli pcb` offers drc, export,
import, render and upgrade, but nothing that updates a board from a
schematic. So after running this, open the project and press F8
(Tools > Update PCB from Schematic) to place the footprints. See
hardware/README.md.

Placement and routing are deliberately left interactive. Generated copper on
a flight-hardware carrier would need reviewing trace by trace anyway, which
is more work than routing it properly in the first place.

Run:
  python hardware/tools/gen_carrier_pcb.py
"""

import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "hardware" / "carrier" / "carrier.kicad_pcb"

# Board origin and size. 80 x 60 leaves room for three columns of connectors
# either side of the 30 mm mounting square.
BX, BY, W, H = 100.0, 100.0, 80.0, 60.0

# Verified from hardware/vendor/PX4FMUv2.4.5.brd: M3_MOUNT1101..1104 sit on a
# 30.000 x 30.000 mm square. The carrier must match it exactly or the stack
# will not bolt together.
M3_PITCH = 30.0
M3_FP = "MountingHole:MountingHole_3.2mm_M3"

LAYERS = """\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive")
\t\t(11 "B.Adhes" user "B.Adhesive")
\t\t(13 "F.Paste" user)
\t\t(15 "B.Paste" user)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(17 "Dwgs.User" user "User.Drawings")
\t\t(19 "Cmts.User" user "User.Comments")
\t\t(21 "Eco1.User" user "User.Eco1")
\t\t(23 "Eco2.User" user "User.Eco2")
\t\t(25 "Edge.Cuts" user)
\t\t(27 "Margin" user)
\t\t(31 "F.CrtYd" user "F.Courtyard")
\t\t(29 "B.CrtYd" user "B.Courtyard")
\t\t(35 "F.Fab" user)
\t\t(33 "B.Fab" user)
\t)"""

# Netclasses. VBRICK carries the full module supply current, so it gets a
# wider track than signals; CAN_H/CAN_L are a differential pair.
SETUP = """\t(setup
\t\t(pad_to_mask_clearance 0)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(grid_origin {gx} {gy})
\t)""".format(gx=BX, gy=BY)


def uid():
    return str(_uuid.uuid4())


def edge(x1, y1, x2, y2):
    return (f'\t(gr_line\n'
            f'\t\t(start {x1} {y1})\n'
            f'\t\t(end {x2} {y2})\n'
            f'\t\t(stroke (width 0.1) (type default))\n'
            f'\t\t(layer "Edge.Cuts")\n'
            f'\t\t(uuid "{uid()}")\n'
            f'\t)')


def text(s, x, y, layer="F.SilkS", size=1.0):
    return (f'\t(gr_text "{s}"\n'
            f'\t\t(at {x} {y} 0)\n'
            f'\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{uid()}")\n'
            f'\t\t(effects\n'
            f'\t\t\t(font (size {size} {size}) (thickness 0.15))\n'
            f'\t\t\t(justify left)\n'
            f'\t\t)\n'
            f'\t)')


FP_ROOT = Path(
    r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0\share\kicad\footprints")


def mounting_hole(ref, x, y):
    """An M3 hole, as a real footprint so DRC treats it as a keepout.

    The body is taken verbatim from KiCad's own MountingHole library rather
    than hand-written. A hand-written equivalent drew four
    `lib_footprint_mismatch` violations - DRC compares the board's embedded
    copy against the library byte for byte, so "equivalent" is not enough.
    """
    src = (FP_ROOT / "MountingHole.pretty" / "MountingHole_3.2mm_M3.kicad_mod"
           ).read_text(encoding="utf-8")
    # Strip the library wrapper, keep the contents, re-indent one level.
    inner = src.strip()
    assert inner.startswith("(footprint"), "unexpected footprint file layout"
    inner = inner[inner.index("\n") + 1:inner.rindex(")")].rstrip()
    inner = "\n".join("\t" + ln for ln in inner.splitlines())
    return (f'\t(footprint "{M3_FP}"\n'
            f'\t\t(layer "F.Cu")\n'
            f'\t\t(uuid "{uid()}")\n'
            f'\t\t(at {x} {y})\n'
            f'{inner}\n'
            f'\t\t(property "Reference" "{ref}"\n'
            f'\t\t\t(at 0 -3.5 0)\n'
            f'\t\t\t(layer "F.SilkS")\n'
            f'\t\t\t(uuid "{uid()}")\n'
            f'\t\t\t(effects (font (size 1 1) (thickness 0.15)))\n'
            f'\t\t)\n'
            f'\t)')


def main():
    cx, cy = BX + W / 2, BY + H / 2
    holes = [(cx - M3_PITCH / 2, cy - M3_PITCH / 2),
             (cx + M3_PITCH / 2, cy - M3_PITCH / 2),
             (cx - M3_PITCH / 2, cy + M3_PITCH / 2),
             (cx + M3_PITCH / 2, cy + M3_PITCH / 2)]

    body = [
        edge(BX, BY, BX + W, BY),
        edge(BX + W, BY, BX + W, BY + H),
        edge(BX + W, BY + H, BX, BY + H),
        edge(BX, BY + H, BX, BY),
        text("JFOX TMR CARRIER", BX + 3, BY + 4, size=1.5),
        text("CAN1 bus + per-board power pass-through", BX + 3, BY + 7),
        text("R409: populate on END modules only - desolder on the middle one",
             BX + 3, BY + H - 6),
        text("Verify ~60R across CAN_H/CAN_L, bus unpowered", BX + 3, BY + H - 3),
        text(f"M3 pattern {M3_PITCH} x {M3_PITCH} mm (from PX4FMUv2.4.5.brd)",
             BX + 3, BY + H - 9, layer="Cmts.User"),
    ]
    for i, (x, y) in enumerate(holes, 1):
        body.append(mounting_hole(f"H{i}", round(x, 3), round(y, 3)))

    doc = ("(kicad_pcb\n"
           "\t(version 20260206)\n"
           '\t(generator "pcbnew")\n'
           '\t(generator_version "10.0")\n'
           "\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n"
           '\t(paper "A4")\n'
           + LAYERS + "\n" + SETUP + "\n"
           + "\n".join(body) + "\n"
           ")\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print(f"  wrote {OUT.relative_to(REPO)} ({OUT.stat().st_size} bytes)")
    print(f"  board  {W} x {H} mm at ({BX}, {BY})")
    print(f"  M3 holes ({M3_PITCH} x {M3_PITCH} mm pattern):")
    for i, (x, y) in enumerate(holes, 1):
        print(f"    H{i} at ({x:.1f}, {y:.1f})")
    print("\nnext: open hardware/carrier/carrier.kicad_pro in KiCad and press F8")
    print("      (Tools > Update PCB from Schematic) to place the 9 connectors.")


if __name__ == "__main__":
    main()
