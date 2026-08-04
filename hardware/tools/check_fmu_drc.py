#!/usr/bin/env python3
"""Run KiCad's DRC on the board and gate on what matters.

DRC on an unrouted board reports one violation per unconnected net, which is
true and useless - nothing is routed yet, so of course nothing is connected.
Gating on the raw total would mean the check can never pass until the board is
finished, and a check that can never pass gets ignored.

So this splits the report:

  BLOCKING    faults that mean the placement is wrong - overlapping
              courtyards, copper shorts, pads too close, parts off the edge.
              These must be zero.
  EXPECTED    unrouted nets. Counted and reported, never gated on.
  ADVISORY    silkscreen overlap and similar. Reported; they get cleaned up
              during layout and blocking on them now would be noise.

    python hardware/tools/check_fmu_drc.py

Exits non-zero if anything in BLOCKING is present.
"""

import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PCB = REPO / "hardware" / "jfox-fmu-v1" / "jfox-fmu.kicad_pcb"

KICAD = Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0")

# A placement is wrong if any of these appear. Every one means two pieces of
# copper occupy the same space, or a part cannot physically be fitted.
BLOCKING = {
    "courtyards_overlap", "shorting_items", "clearance", "hole_clearance",
    "npth_inside_courtyard", "copper_edge_clearance", "solder_mask_bridge",
    "drill_out_of_range", "track_dangling", "footprint_symbol_mismatch",
    "invalid_outline", "malformed_courtyard", "duplicate_footprints",
}

# True, and not a defect until routing is done.
EXPECTED = {"unconnected_items"}

# Cosmetic or resolved during layout.
ADVISORY = {
    "silk_over_copper", "silk_overlap", "silk_edge_clearance",
    "text_height", "text_thickness", "nonmirrored_text_on_back_layer",
    "zones_intersect", "assertion_failure",
}


def cli():
    for c in (KICAD / "bin" / "kicad-cli.exe",
              Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found")


def main():
    if not PCB.exists():
        sys.exit(f"missing {PCB} - run gen_fmu_pcb.py first")

    # Delete the report before running. It is a fixed path in the temp
    # directory, so a run that fails outright leaves the PREVIOUS run's
    # report sitting there - and this script parsed it happily. That is how
    # a board KiCad refused to load ("Unexpected rules", exit 2) reported a
    # detailed 107-violation breakdown for several rounds of edits: the
    # numbers were real, they were just from a different file.
    rpt = Path(tempfile.gettempdir()) / "fmu_drc.rpt"
    rpt.unlink(missing_ok=True)

    r = subprocess.run([cli(), "pcb", "drc", "--format", "report",
                        "-o", str(rpt), str(PCB)],
                       capture_output=True, text=True)

    # kicad-cli exits non-zero when it finds violations, so the return code
    # alone cannot distinguish "board is bad" from "board did not load".
    # A load failure says so, and produces no report at all.
    if "Failed to load board" in (r.stderr + r.stdout):
        sys.exit(f"kicad-cli could not load the board - DRC never ran:\n"
                 f"{r.stderr.strip() or r.stdout.strip()}")
    if not rpt.exists():
        sys.exit(f"DRC produced no report (exit {r.returncode}):\n"
                 f"{r.stdout}\n{r.stderr}")

    txt = rpt.read_text(encoding="utf-8")
    counts = Counter(re.findall(r'^\[(\w+)\]', txt, re.M))

    unconn = 0
    m = re.search(r'Found (\d+) unconnected item', r.stdout)
    if m:
        unconn = int(m.group(1))

    blocking = {k: v for k, v in counts.items() if k in BLOCKING}
    advisory = {k: v for k, v in counts.items() if k in ADVISORY}
    unknown = {k: v for k, v in counts.items()
               if k not in BLOCKING and k not in ADVISORY and k not in EXPECTED}

    nblock = sum(blocking.values())
    print(f"  [{'PASS' if not nblock and not unknown else 'FAIL'}] "
          f"DRC: {nblock} blocking violation(s)")
    for k, v in sorted(blocking.items(), key=lambda kv: -kv[1]):
        print(f"      {v:>4}  {k}")
        for line in re.findall(r'^\[%s\]:[^\n]*\n(?:[^\n]*\n){1,2}' % k,
                               txt, re.M)[:2]:
            for l in line.strip().splitlines()[1:]:
                print(f"            {l.strip()[:90]}")

    if unknown:
        # A rule this tool has never seen is not automatically harmless.
        # Report it as blocking rather than silently dropping it, which is
        # how a checker stops noticing new classes of fault.
        print("      unclassified rules, treated as blocking:")
        for k, v in sorted(unknown.items()):
            print(f"      {v:>4}  {k}")

    print(f"\n  expected while unrouted: {unconn} unconnected item(s)")
    if advisory:
        print("  advisory (cleaned up during layout):")
        for k, v in sorted(advisory.items(), key=lambda kv: -kv[1]):
            print(f"      {v:>4}  {k}")

    if nblock or unknown:
        print("\nplacement has physical faults - see above")
        return 1
    print("\nno blocking DRC violations: nothing overlaps, shorts or "
          "falls off the board")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
