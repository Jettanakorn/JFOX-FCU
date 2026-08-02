#!/usr/bin/env python3
"""Give each of the three FMU instances its own reference designators.

One sheet file instantiated three times means one symbol appears three times
in the netlist. KiCad keeps those apart by letting a symbol carry one
`(path ...)` entry per instance, each with its own reference - that is exactly
how KiCad's own qa/data/eeschema test project handles a thrice-instantiated
subsheet. Straight out of the generator, fmu-v2's symbols carry only the single
path they were imported with, so all three boards report C101, R102, U101 and
the netlist shows 863 component instances sharing 301 designators.

This rewrites those blocks: C101 becomes C101A / C101B / C101C, one per board.
It reads the sheet UUIDs it needs from the generated files rather than taking
them as arguments, so it cannot drift out of step with them:

  jfox-tmr.kicad_sch     -> the three FMU-A/B/C sheet element UUIDs
  fmu-v2/fmu-v2.kicad_sch -> the twelve page sheet element UUIDs

Symbol instance paths are two levels here - "/<fmu-instance>/<page>" - because
the symbols live one sheet below the FMU sheet.

Run after gen_fmu_hierarchical.py and gen_tmr_schematic.py:
  python hardware/tools/annotate_tmr_instances.py
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware"
TMR = HW / "jfox-tmr.kicad_sch"
FMU_ROOT = HW / "fmu-v2" / "fmu-v2.kicad_sch"
BOARDS = ["A", "B", "C"]


def sheet_uuids(path):
    """[(sheetname, sheetfile, uuid)] per (sheet ...) element, in file order.

    Paren-counted, not regex-matched: the two generators here indent
    differently (two spaces vs tabs) and these blocks nest, so anything
    anchored on layout finds one sheet and misses eleven.
    """
    text = path.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'\(sheet\b(?!_)', text):
        depth, j, instr, esc = 0, m.start(), False, False
        while j < len(text):
            c = text[j]
            if esc:
                esc = False
            elif c == "\\" and instr:
                esc = True
            elif c == '"':
                instr = not instr
            elif not instr:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        blk = text[m.start():j + 1]
        u = re.search(r'\(uuid "?([0-9a-f-]{36})"?\)', blk)
        n = re.search(r'\(property "Sheetname" "([^"]+)"', blk)
        f = re.search(r'\(property "Sheetfile" "([^"]+)"', blk)
        if u and n and f:
            out.append((n.group(1), f.group(1), u.group(1)))
    return out


def parent_path(path):
    """The hierarchy path a top-level sheet's children hang off, read from the
    first sheet's own (instances ... (path X))."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r'\(instances\s*\n\s*\(project "[^"]*"\s*\n\s*\(path "([^"]+)"',
                  text)
    return m.group(1).rstrip("/") if m else ""


def main():
    for p in (TMR, FMU_ROOT):
        if not p.exists():
            sys.exit(f"missing {p} - run the generators first")

    # A symbol's instance path is the full hierarchy path to the sheet it sits
    # on. Rather than assume the prefix, take it from the FMU sheet's own
    # (instances ... (path X)) - X is that sheet's PARENT path, so the sheet
    # itself is X + "/" + its element uuid, and a page below it is one more
    # level down. KiCad 10 roots these at the root document's uuid, KiCad 7 did
    # it differently, and the imported pages use a third form; deriving avoids
    # having to be right about which.
    parent = parent_path(TMR)
    fmu_instances = [(n, f"{parent}/{u}".replace("//", "/"))
                     for n, f, u in sheet_uuids(TMR)
                     if f.endswith("fmu-v2.kicad_sch")]
    if len(fmu_instances) != 3:
        sys.exit(f"expected 3 FMU sheet instances in {TMR.name}, "
                 f"found {len(fmu_instances)}")
    pages = {f: u for n, f, u in sheet_uuids(FMU_ROOT)}
    if len(pages) != 12:
        sys.exit(f"expected 12 page sheets in {FMU_ROOT.name}, found {len(pages)}")

    total = 0
    for page_file, page_uuid in sorted(pages.items()):
        path = FMU_ROOT.parent / page_file
        text = path.read_text(encoding="utf-8")
        text, n = rewrite(text, fmu_instances, page_uuid)
        path.write_text(text, encoding="utf-8")
        print(f"  {page_file:<32} {n:3d} symbols")
        total += n

    print(f"\n  {total} symbols x 3 boards = {total * 3} uniquely-referenced instances")
    print("  references suffixed A/B/C per board")


def rewrite(text, fmu_instances, page_uuid):
    """Replace every symbol's (instances ...) block with three paths."""
    out, count, pos = [], 0, 0
    for m in re.finditer(r'\t\t\(instances\n(.*?)\n\t\t\)\n', text, re.S):
        ref = re.search(r'\(reference "([^"]+)"\)', m.group(1))
        unit = re.search(r'\(unit (\d+)\)', m.group(1))
        if not ref:
            continue
        # Strip any suffix a previous run added, or re-running stacks them:
        # C1102 -> C1102A -> C1102AA -> C1102AAA. Only trailing board letters
        # directly after a digit are removed, and every designator in this
        # design ends in a digit before its suffix.
        base = re.sub(r'(?<=\d)[ABC]+$', "", ref.group(1))
        u = unit.group(1) if unit else "1"
        block = ['\t\t(instances', '\t\t\t(project "jfox-tmr"']
        for (name, fmu_path), b in zip(fmu_instances, BOARDS):
            block += [f'\t\t\t\t(path "{fmu_path}/{page_uuid}"',
                      f'\t\t\t\t\t(reference "{base}{b}")',
                      f'\t\t\t\t\t(unit {u})',
                      '\t\t\t\t)']
        block += ['\t\t\t)', '\t\t)', '']
        out.append(text[pos:m.start()])
        out.append("\n".join(block))
        pos = m.end()
        count += 1
    out.append(text[pos:])
    return "".join(out), count


if __name__ == "__main__":
    main()
