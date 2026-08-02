#!/usr/bin/env python3
"""Make the imported FMU board safe to instantiate three times.

The problem
-----------
KiCad's Eagle import represents every cross-page net as a *global* label -
136 distinct, 123 spanning more than one page, no internal hierarchy at all.
A global label is global across the entire project. Instantiate that design
three times as FMU-A/B/C and all 120 non-shared nets short together across the
boards: every SPI bus, every MCU pin, every internal rail. The schematic would
look perfectly normal and be electrically meaningless.

Only four nets are genuinely shared between the three modules and may stay
global: CAN_H, CAN_L, GND, SAFETY. That is the same split the carrier assumes.

What this does
--------------
Generates hardware/fmu-v2/ from the pristine import in
hardware/PX4FMUv2.4.5/, leaving that untouched and re-importable:

  * multi-page nets      -> hierarchical labels + matching sheet pins on a new
                            container root, joined there by local labels, so
                            connectivity is preserved but scoped to one
                            instance of the board;
  * single-page nets     -> plain local labels (they never left the page);
  * CAN_H/CAN_L/GND/SAFETY -> left global, which is correct;
  * VDD_5V_BRICK, BATT_CURRENT_SENS, BATT_VOLTAGE_SENS -> also exposed as
    hierarchical labels on the root, so jfox-tmr can wire each board's power
    to its own carrier connector.

Run (after repair_import_hierarchy.py):
  python hardware/tools/gen_fmu_hierarchical.py
"""

import os
import re
import shutil
import stat
import sys
import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "hardware" / "PX4FMUv2.4.5"
DST = REPO / "hardware" / "fmu-v2"

# Genuinely common to all three modules - a shared bus, a shared ground, one
# switch. Leaving these global is not an oversight, it is the design.
SHARED = {"CAN_H", "CAN_L", "GND", "SAFETY"}

# The board's per-instance power interface, using the names the board itself
# uses (checked against the import - not BATT_V_SENS/BATT_I_SENS, which an
# earlier version of the TMR generator had invented).
BOUNDARY = ["VDD_5V_BRICK", "BATT_CURRENT_SENS", "BATT_VOLTAGE_SENS"]

MM = 2.54
PAGES = [f"PX4FMUv2.4.5_{i}.kicad_sch" for i in range(1, 13)]


def uid():
    return str(_uuid.uuid4())


def blocks(text, token):
    """Yield (start, end) of each top-level `\\t(token ...)` block.

    Paren-counted rather than regex-matched: these blocks nest (effects, font,
    property), and a lazy regex silently truncates at the first inner `)`.
    """
    out = []
    for m in re.finditer(r'\t\(' + token + r'\b', text):
        i = m.start() + 1
        depth, j, instr, esc = 0, i, False, False
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
                        out.append((m.start(), j + 1))
                        break
            j += 1
    return out


def convert_page(text, multi, single):
    """Rewrite this page's global labels in place, longest blocks first so
    earlier edits do not shift later offsets."""
    edits = []
    for s, e in blocks(text, "global_label"):
        blk = text[s:e]
        nm = re.match(r'\t\(global_label "([^"]+)"', blk)
        if not nm:
            continue
        name = nm.group(1)
        if name in SHARED:
            continue
        # hierarchical_label and label do not carry Intersheetrefs; that
        # property is specific to global labels and KiCad rejects it elsewhere.
        body = strip_property(blk, "Intersheetrefs")
        if name in multi:
            body = body.replace("(global_label", "(hierarchical_label", 1)
        else:
            # a plain label takes no shape
            body = body.replace("(global_label", "(label", 1)
            body = re.sub(r'\n\t\t\(shape \w+\)', "", body, count=1)
        body = body.replace("\n\t\t(fields_autoplaced yes)", "", 1)
        edits.append((s, e, body))
    for s, e, body in reversed(edits):
        text = text[:s] + body + text[e:]
    return text


def strip_property(blk, prop):
    for m in re.finditer(r'\t\t\(property "' + prop + r'"', blk):
        i = m.start() + 2
        depth, j, instr, esc = 0, i, False, False
        while j < len(blk):
            c = blk[j]
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
                        return blk[:m.start()] + blk[j + 2:]
            j += 1
    return blk


def scan():
    """net name -> set of pages carrying it."""
    pages = {}
    for p in PAGES:
        t = (SRC / p).read_text(encoding="utf-8")
        for s, e in blocks(t, "global_label"):
            nm = re.match(r'\t\(global_label "([^"]+)"', t[s:e])
            if nm:
                pages.setdefault(nm.group(1), set()).add(p)
    return pages


def build_root(pins_per_page):
    """Container root: 12 sheets, their pins joined by labels.

    Same-named pins on different sheets carry the same label, which is what
    restores the flat connectivity Eagle had - but scoped to this sheet, so
    three instances of it stay independent.
    """
    ru = uid()
    out = ['(kicad_sch', '\t(version 20260306)', '\t(generator "eeschema")',
           '\t(generator_version "10.0")', f'\t(uuid "{ru}")', '\t(paper "A1")']

    out.append(f'\t(text "PX4FMUv2.4.5 - one module.\\n'
               f'Generated by hardware/tools/gen_fmu_hierarchical.py from the pristine\\n'
               f'import in hardware/PX4FMUv2.4.5/ - do not hand-edit, regenerate.\\n'
               f'Cross-page nets are hierarchical here, NOT global, so the three\\n'
               f'instances in jfox-tmr stay electrically separate."\n'
               f'\t\t(at 20 12 0)\n'
               f'\t\t(effects (font (size 2 2)) (justify left top))\n'
               f'\t\t(uuid "{uid()}")\n\t)')

    # everything on the 2.54 mm grid: 30.0 and 100.0 are not multiples of it,
    # and KiCad reports one endpoint_off_grid per label (262 of them).
    col_w, x0, y0 = 101.6, 63.5, 25.4
    rows = [PAGES[:6], PAGES[6:]]
    y = y0
    for row in rows:
        row_h = 0
        for ci, page in enumerate(row):
            pins = sorted(pins_per_page[page])
            x = x0 + ci * col_w
            h = MM * (len(pins) + 2)
            row_h = max(row_h, h)
            out.append(sheet_block(page, x, y, h, pins, ru,
                                   PAGES.index(page) + 2))
            py = y + MM
            for name in pins:
                out.append(f'\t(wire (pts (xy {x} {round(py,2)}) '
                           f'(xy {round(x-7.62,2)} {round(py,2)}))\n'
                           f'\t\t(stroke (width 0) (type default))\n'
                           f'\t\t(uuid "{uid()}")\n\t)')
                tok = "hierarchical_label" if name in BOUNDARY else "label"
                shape = '\n\t\t(shape passive)' if name in BOUNDARY else ""
                out.append(f'\t({tok} "{name}"{shape}\n'
                           f'\t\t(at {round(x-7.62,2)} {round(py,2)} 180)\n'
                           f'\t\t(effects (font (size 1.27 1.27)) (justify right))\n'
                           f'\t\t(uuid "{uid()}")\n\t)')
                py += MM
        y += row_h + 20.32

    out.append('\t(sheet_instances\n\t\t(path "/" (page "1"))\n\t)')
    out.append('\t(embedded_fonts no)')
    out.append(')')
    return "\n".join(out) + "\n", ru


def sheet_block(page, x, y, h, pins, ru, pagenum):
    su = uid()
    o = ['\t(sheet', f'\t\t(at {x} {y})', f'\t\t(size 55 {round(h,2)})',
         '\t\t(fields_autoplaced yes)',
         '\t\t(stroke (width 0.1524) (type solid))',
         '\t\t(fill (color 0 0 0 0.0000))', f'\t\t(uuid "{su}")',
         f'\t\t(property "Sheetname" "{page[:-10]}" (at {x} {round(y-0.71,2)} 0)',
         '\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))', '\t\t)',
         f'\t\t(property "Sheetfile" "{page}" (at {x} {round(y+h+0.6,2)} 0)',
         '\t\t\t(effects (font (size 1.27 1.27)) (justify left top))', '\t\t)']
    py = y + MM
    for name in pins:
        o += [f'\t\t(pin "{name}" passive (at {x} {round(py,2)} 180)',
              '\t\t\t(effects (font (size 1.27 1.27)) (justify right))',
              f'\t\t\t(uuid "{uid()}")', '\t\t)']
        py += MM
    o += ['\t\t(instances', '\t\t\t(project "fmu-v2"',
          f'\t\t\t\t(path "/" (page "{pagenum}"))', '\t\t\t)', '\t\t)', '\t)']
    return "\n".join(o)


def main():
    if not (SRC / PAGES[0]).exists():
        sys.exit(f"missing {SRC / PAGES[0]} - run repair_import_hierarchy.py first")

    pages = scan()
    multi = {n for n, ps in pages.items() if len(ps) > 1 and n not in SHARED}
    single = {n for n, ps in pages.items() if len(ps) == 1 and n not in SHARED}

    if DST.exists():
        # KiCad's Local History feature drops a git repo in the project
        # directory, and git marks its objects read-only, which makes a plain
        # rmtree fail with EACCES on Windows. Clear the bit and retry.
        def force(func, path, _exc):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(DST, onexc=force)
    DST.mkdir(parents=True)

    pins_per_page = {p: set() for p in PAGES}
    for n in multi:
        for p in pages[n]:
            pins_per_page[p].add(n)

    for p in PAGES:
        t = (SRC / p).read_text(encoding="utf-8")
        (DST / p).write_text(convert_page(t, multi, single), encoding="utf-8")

    root, _ = build_root(pins_per_page)
    (DST / "fmu-v2.kicad_sch").write_text(root, encoding="utf-8")

    for extra in ("PX4FMUv2.4.5-eagle-import.kicad_sym", "sym-lib-table"):
        if (SRC / extra).exists():
            shutil.copy2(SRC / extra, DST / extra)
    (DST / "fmu-v2.kicad_pro").write_text(
        '{\n  "meta": {"filename": "fmu-v2.kicad_pro", "version": 1},\n'
        '  "schematic": {},\n  "sheets": [],\n  "text_variables": {}\n}\n',
        encoding="utf-8")

    print(f"  converted {len(multi)} multi-page nets to hierarchical labels")
    print(f"  converted {len(single)} single-page nets to local labels")
    print(f"  left {sorted(SHARED & set(pages))} global (genuinely shared)")
    print(f"  root exposes {BOUNDARY} to the parent")
    print(f"  wrote {DST.relative_to(REPO)} "
          f"({sum(len(v) for v in pins_per_page.values())} sheet pins)")


if __name__ == "__main__":
    main()
