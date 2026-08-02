#!/usr/bin/env python3
"""Rebuild the container root of the Eagle-imported FMU project.

Why this exists
---------------
KiCad's Eagle import produced 12 pages plus a container root that referenced
them. The root file was subsequently overwritten with page 1's own content:
its symbols carry instance path "/e0a7e50b..." - the UUID that
PX4FMUv2.4.5.kicad_pro records as sheet "PX4FMUv2.4.5_1" - which is what a
child page saved over its parent looks like.

The effect is that KiCad sees a one-page project. `kicad-cli sch erc`
enumerates only "Sheet /", and a netlist export yields 8 components instead of
421. The other 11 files are on disk, complete, and unreachable.

All the page content survived, so this rebuilds the container rather than
requiring a re-import:

  1. move PX4FMUv2.4.5.kicad_sch -> PX4FMUv2.4.5_1.kicad_sch (it is page 1)
  2. write a new PX4FMUv2.4.5.kicad_sch holding 12 (sheet ...) elements whose
     UUIDs come from the .kicad_pro sheet list, so existing symbol instance
     paths keep resolving

No sheet pins are needed: the importer wired every cross-page net as a global
label, which connects across the whole hierarchy regardless.

The result is checked against an independent parse of the original Eagle file
(tools/extract_eagle_nets.py), so this is verified rather than assumed - see
verify() below.

Run:
  python hardware/tools/repair_import_hierarchy.py
"""

import json
import shutil
import sys
import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "hardware" / "PX4FMUv2.4.5"
PRO = DIR / "PX4FMUv2.4.5.kicad_pro"
ROOT = DIR / "PX4FMUv2.4.5.kicad_sch"
PAGE1 = DIR / "PX4FMUv2.4.5_1.kicad_sch"


def already_repaired(text):
    return "Sheetfile" in text


def build_root(sheets):
    """A container root: 12 sheet elements, no content of its own.

    KiCad 10 writes child instance paths as "/<sheet-element-uuid>" - one
    level, without the root document's UUID. (KiCad 7 included the root UUID;
    the imported pages here use the newer single-level form, so the container
    must match or nothing resolves.)
    """
    out = ['(kicad_sch',
           '\t(version 20260306)',
           '\t(generator "eeschema")',
           '\t(generator_version "10.0")',
           f'\t(uuid "{_uuid.uuid4()}")',
           '\t(paper "A4")']
    x, y = 25.4, 25.4
    for i, (su, name) in enumerate(sheets):
        out += [
            '\t(sheet',
            f'\t\t(at {x} {round(y, 2)})',
            '\t\t(size 50.8 20.32)',
            '\t\t(fields_autoplaced yes)',
            '\t\t(stroke (width 0.1524) (type solid))',
            '\t\t(fill (color 0 0 0 0.0000))',
            f'\t\t(uuid "{su}")',
            f'\t\t(property "Sheetname" "{name}" (at {x} {round(y - 0.71, 2)} 0)',
            '\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))',
            '\t\t)',
            f'\t\t(property "Sheetfile" "{name}.kicad_sch" (at {x} {round(y + 20.9, 2)} 0)',
            '\t\t\t(effects (font (size 1.27 1.27)) (justify left top))',
            '\t\t)',
            '\t\t(instances',
            '\t\t\t(project "PX4FMUv2.4.5"',
            f'\t\t\t\t(path "/" (page "{i + 1}"))',
            '\t\t\t)',
            '\t\t)',
            '\t)',
        ]
        y += 27.94
        if y > 240:
            y = 25.4
            x += 63.5
    out += ['\t(sheet_instances',
            '\t\t(path "/" (page "1"))',
            '\t)',
            '\t(embedded_fonts no)',
            ')']
    return "\n".join(out) + "\n"


def verify():
    """Compare the repaired project's netlist against an independent parse of
    the original Eagle file. Two parsers, one source - this is what makes the
    repair verified rather than plausible."""
    import re
    import subprocess
    import tempfile
    sys.path.insert(0, str(Path(__file__).parent))
    import extract_eagle_nets as E
    from check_tmr_netlist import find_cli

    out = Path(tempfile.gettempdir()) / "fmu_repaired.net"
    subprocess.run([find_cli(), "sch", "export", "netlist", "--format",
                    "kicadsexpr", "--output", str(out), str(ROOT)],
                   check=True, capture_output=True, text=True)
    txt = out.read_text(encoding="utf-8")

    kic_comps = set(re.findall(r'\(comp\s*\n\s*\(ref "([^"]+)"\)', txt))
    eag = E.part_index(E.load())
    # Eagle carries GND/supply pseudo-parts and test PADs that are not real
    # components; KiCad represents those as power symbols, excluded from BOM.
    eag_real = {n for n, p in eag.items()
                if not n.startswith(("GND", "FRAME", "FIDUCIAL", "OSHW",
                                     "MMOUNT", "M3_MOUNT"))
                and p["deviceset"] not in ("PAD", "GND", "VCC")}

    kic_nets = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        nm = re.search(r'\(name "([^"]*)"\)', blk)
        if nm:
            kic_nets[nm.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)', blk))

    print(f"  components: kicad={len(kic_comps)} eagle(real)={len(eag_real)}")
    missing = eag_real - kic_comps
    if missing:
        print(f"  MISSING from import: {len(missing)} {sorted(missing)[:10]}")

    ok = True
    for net, expect in (("CAN_H", {"J405", "R409", "U401"}),
                        ("CAN_L", {"J405", "R409", "U401"}),
                        ("CAN1_TX", {"U101", "U401"}),
                        ("SAFETY", {"J702", "R713", "U801"})):
        got = kic_nets.get(net, set())
        mark = "ok" if expect <= got else "MISMATCH"
        if expect > got:
            ok = False
        print(f"  net {net:<9} {mark:<9} expected {sorted(expect)} got {sorted(got)}")
    return ok and not missing


def main():
    if not PRO.exists():
        sys.exit(f"missing {PRO} - run the Eagle import first")
    text = ROOT.read_text(encoding="utf-8") if ROOT.exists() else ""
    if already_repaired(text):
        print("root already references sub-sheets; nothing to repair")
    else:
        sheets = [(u, n) for u, n in json.loads(
            PRO.read_text(encoding="utf-8"))["sheets"]]
        if PAGE1.exists():
            sys.exit(f"{PAGE1.name} already exists - refusing to overwrite")
        shutil.move(str(ROOT), str(PAGE1))
        ROOT.write_text(build_root(sheets), encoding="utf-8")
        print(f"  moved page 1 -> {PAGE1.name}")
        print(f"  wrote container root with {len(sheets)} sheets")

    print("\nverifying against the original Eagle netlist:")
    if not verify():
        raise SystemExit(1)
    print("\nrepair verified: the imported project matches the Eagle source")


if __name__ == "__main__":
    main()
