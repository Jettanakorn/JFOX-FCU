#!/usr/bin/env python3
"""Search the card's placement parameters until DRC is clean, with a render.

Why this exists
---------------

Every band edge and connector offset on this board has been tuned by hand:
generate, read the DRC report, move one number, generate again. That found
the answers, but it took a dozen rounds and each one only tested a single
guess. Worse, moving a band to clear one collision routinely created another
somewhere the previous pass had already settled - the last manual round went
from 2 violations to 7 doing exactly that.

The parameters are a handful of numbers with obvious ranges. That is a
search, and a search is a thing to run rather than perform.

What it optimises
-----------------

    cost = 1000 * blocking DRC violations
         +  500 * parts that did not fit a zone
         +        the layout score (overlap, edge, decoupling, net length)

DRC dominates because a board with a physical fault is not a candidate at
any price. Unplaced parts come next: a board missing seven components is not
smaller, it is incomplete - and that distinction is easy to lose when the
generator prints a tidy summary either way.

Every time the best cost improves, the board is rendered to PNG, so the run
leaves a visual trail rather than only a number. Component locations and
orientations are what a person actually needs to check, and no scalar shows
them.

    python hardware/tools/loop_fmu_layout.py [--rounds N]

Writes the best configuration back into gen_fmu_pcb.py and leaves
hardware/jfox-fmu-v1/render/ holding the PNGs.
"""

import argparse
import itertools
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "hardware" / "tools"
GEN = TOOLS / "gen_fmu_pcb.py"
PCB = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.kicad_pcb"
RENDER = REPO / "hardware" / "jfox-fmu-v1" / "render"

sys.path.insert(0, str(TOOLS))
import score_fmu_layout as SCORE            # noqa: E402

KICAD = Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0")


def cli():
    for c in (KICAD / "bin" / "kicad-cli.exe",
              Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found")


# --------------------------------------------------------------------------
# The parameters worth searching, and why each one.
#
# Only things whose value is genuinely arbitrary within a range. The MCU
# position is NOT here - it is fixed deliberately, and letting a search move
# it would undo a decision made for a reason. Nor is the card edge, which is
# pinned to the tongue by the connector's own profile.
# --------------------------------------------------------------------------
def band(name, idx):
    """Match one coordinate of one ZONES entry, and nothing else.

    Each pattern captures only the number it changes. The previous version
    baked its neighbours' values into the regex, so moving one band made
    three other patterns match nothing - and the run stopped on its own
    guard rather than searching.
    """
    pre = r'("%s":\s*\(\s*' % name
    for _ in range(idx):
        pre += r'[\d.]+,\s*'
    # Terminator is ',' for every field but the last, which the tuple's
    # closing paren ends. Demanding a comma made every "far edge" parameter
    # match nothing.
    return pre + r')([\d.]+)([,)])'


PARAMS = {
    # Band edges that trade against each other on the back face, where the
    # two noise groups sit.
    "NOISY_Y1":    (band("NOISY", 3), [28.0, 29.0, 30.0]),
    "ISOLATED_Y0": (band("ISOLATED", 1), [30.0, 31.0, 32.0]),
    "ISOLATED_Y1": (band("ISOLATED", 3), [46.0, 48.0, 50.0]),
    # The sensor island: its front edge sets the distance to the converters,
    # which is the clearance that failed at 48 x 90.
    "QUIET_Y0":    (band("QUIET", 1), [65.0, 67.0, 69.0]),
    # The two harness landings behind the MCU.
    "J12_Y": (r'("J12": \("E", )([\d.]+)(, "F"\))', [50.0, 52.0, 54.0]),
    "J13_Y": (r'("J13": \("E", )([\d.]+)(, "F"\))', [60.0, 62.0, 64.0]),
}



def patch(name, value):
    """Set one parameter in the generator, in place."""
    pat, _ = PARAMS[name]
    t = GEN.read_text(encoding="utf-8")
    new, n = re.subn(pat, lambda m: f"{m.group(1)}{value}{m.group(3)}", t)
    if n != 1:
        raise SystemExit(
            f"{name}: pattern matched {n} times, expected 1.\n"
            f"  pattern: {pat}\n"
            f"The generator has changed shape, so this search would be "
            f"editing the wrong number. Every candidate for {name} will be "
            f"skipped until the pattern is fixed - which looks identical to "
            f"'{name} never improves the board'.")
    GEN.write_text(new, encoding="utf-8")


def build():
    """Regenerate, and report how many parts failed to place."""
    r = subprocess.run([sys.executable, str(GEN)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r"(\d+) did not fit", r.stdout)
    return int(m.group(1)) if m else 0


BLOCKING = {"clearance", "courtyards_overlap", "shorting_items",
            "solder_mask_bridge", "hole_clearance", "drill_out_of_range",
            "npth_inside_courtyard", "copper_edge_clearance",
            "invalid_outline", "malformed_courtyard", "footprint_symbol_mismatch"}


def drc():
    """Blocking violations only. Silk and unrouted nets are not faults yet."""
    rpt = RENDER / "_drc.rpt"
    rpt.unlink(missing_ok=True)
    r = subprocess.run([cli(), "pcb", "drc", "--format", "report",
                        "-o", str(rpt), str(PCB)],
                       capture_output=True, text=True)
    if "Failed to load board" in (r.stderr + r.stdout) or not rpt.exists():
        return None
    txt = rpt.read_text(encoding="utf-8")
    return sum(1 for k in re.findall(r'^\[(\w+)\]', txt, re.M)
               if k in BLOCKING)


def render(tag):
    for side, nick in (("top", "top"), ("bottom", "bot")):
        subprocess.run([cli(), "pcb", "render", "--side", side,
                        "--width", "1000", "--height", "1400",
                        "-o", str(RENDER / f"{tag}_{nick}.png"), str(PCB)],
                       capture_output=True, text=True)


def cost():
    bad = build()
    if bad is None:
        return None, None
    v = drc()
    if v is None:
        return None, None
    parts, pads, outline = SCORE.parse(PCB)
    # score() returns (total, metrics) - total first. Unpacking it the
    # other way round gave a float where a dict was expected.
    layout, _metrics = SCORE.score(parts, pads, outline)
    return 1000 * v + 500 * bad + layout, (v, bad, round(layout, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()
    RENDER.mkdir(parents=True, exist_ok=True)

    current = {k: None for k in PARAMS}
    best, detail = cost()
    if best is None:
        sys.exit("the generator or DRC failed on the starting board - fix "
                 "that before searching, or every candidate looks equal")
    print(f"  start   cost {best:9.1f}   drc {detail[0]:>3}  unplaced "
          f"{detail[1]:>2}  layout {detail[2]}")
    render("best")

    # Coordinate descent: one parameter at a time, keep what improves.
    # Not a global optimum, but these parameters barely interact and the
    # alternative is 4^4 full builds at ~4 s each.
    for rnd in range(args.rounds):
        improved = False
        for name, (_pat, options) in PARAMS.items():
            for val in options:
                if current[name] == val:
                    continue
                before = GEN.read_text(encoding="utf-8")
                try:
                    patch(name, val)
                except SystemExit as e:
                    print(f"   {e}")
                    continue
                c, d = cost()
                if c is not None and c < best - 1e-6:
                    best, detail, current[name] = c, d, val
                    improved = True
                    print(f"  round {rnd}  {name}={val:<6} cost {c:9.1f}   "
                          f"drc {d[0]:>3}  unplaced {d[1]:>2}  layout {d[2]}")
                    render("best")
                else:
                    GEN.write_text(before, encoding="utf-8")
        if not improved:
            print(f"  round {rnd}: no parameter improved - stopping")
            break

    build()
    render("final")
    print(f"\n  best cost {best:.1f}  (drc {detail[0]}, unplaced {detail[1]}, "
          f"layout {detail[2]})")
    print(f"  renders in {RENDER.relative_to(REPO)}")
    return 0 if detail[0] == 0 and detail[1] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
