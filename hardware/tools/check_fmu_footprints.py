#!/usr/bin/env python3
"""Check every component has a footprint, and that the footprint exists.

Checks the generated netlist rather than the table in the generator, so what
is verified is what the board will actually be built from.

Two distinct failures, both silent until far too late:

  - a component with no footprint. KiCad will import the netlist, place
    everything else, and simply leave that part off the board.
  - a footprint whose library or name does not resolve. This one is worse,
    because the schematic looks complete and the name looks plausible. Three
    of the names this design started with were plausible and wrong:
    `Sensor_Motion:InvenSense_QFN-14_3x3mm_P0.5mm` and
    `Sensor_Pressure:Bosch_LGA-10_2x2mm_P0.35mm` name no footprint in any
    installed library, and `Package_LGA:Bosch_LGA-14_3x2.5mm_P0.5mm` names a
    real one drawn for a different part.

    python hardware/tools/check_fmu_footprints.py

Exits non-zero if anything is missing.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
SCH = BOARD / "jfox-fmu.kicad_sch"

KICAD = Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0")
STOCK = KICAD / "share" / "kicad" / "footprints"

# Parts that are drawing symbols, not components: power flags, net ties.
VIRTUAL = re.compile(r'^#')

# Pin count per part, from its KiCad symbol. Only parts where a wrong
# footprint is plausible - passives and connectors are covered by their own
# naming. A footprint with FEWER pads than the symbol has pins cannot be
# built; more is allowed, since thermal pads and shields add pads.
PINS = {
    "STM32H753IIT6": 176, "LTC4417CGN": 24, "ISOW1044": 20,
    "TPS62132": 16, "BMI088": 16, "ICM-42688-P": 14, "ICM-45686": 14,
    "BMP388": 10, "ICP-20100": 10, "FM25V02A": 8,
    "AP2112K-3.3": 5, "AP22804AW5": 5, "PMOS": 3,
}


def cli():
    for c in (KICAD / "bin" / "kicad-cli.exe",
              Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found")


def netlist():
    out = Path(tempfile.gettempdir()) / "fmu_fp.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"netlist export failed:\n{r.stdout}\n{r.stderr}")
    return out.read_text(encoding="utf-8")


def project_libs():
    """Footprint libraries the PROJECT declares, from its fp-lib-table.

    Resolving through the table is the whole point. The first version of this
    checker hardcoded `{"jfox-fmu": BOARD / "jfox-fmu.pretty"}` and reported
    58 of 58 footprints resolving - while the project had no fp-lib-table at
    all, so KiCad could not find that library and refused to place four parts.
    The checker was answering "does this file exist", and the question that
    matters is "can KiCad find it", which is not the same question and was not
    the same answer.
    """
    tbl = BOARD / "fp-lib-table"
    if not tbl.exists():
        return {}, "the project has no fp-lib-table"
    libs = {}
    for name, uri in re.findall(r'\(name "([^"]+)"\).*?\(uri "([^"]+)"\)',
                                tbl.read_text(encoding="utf-8"), re.S):
        libs[name] = Path(uri.replace("${KIPRJMOD}", str(BOARD)))
    return libs, None


LIBS, TABLE_PROBLEM = project_libs()


def resolve(fp):
    """Path a `Library:Name` footprint reference points at, or None.

    Project libraries must be declared in fp-lib-table; stock ones come from
    the KiCad install. A name that resolves to neither is unplaceable.
    """
    if ":" not in fp:
        return None
    lib, name = fp.split(":", 1)
    root = LIBS.get(lib)
    if root is None:
        root = STOCK / f"{lib}.pretty"
        if not root.is_dir():
            return None          # not stock, and the project never declared it
    p = root / f"{name}.kicad_mod"
    return p if p.exists() else None


def pad_count(path):
    """Distinct pad NUMBERS in a footprint. Numbers, not pads: a thermal pad
    is often repeated under one number, and multi-pad nets like a connector
    shield share one too."""
    txt = path.read_text(encoding="utf-8")
    return len({m.group(1) for m in
                re.finditer(r'\(pad "([^"]+)"', txt) if m.group(1) != ""})



def main():
    txt = netlist()
    # Split into per-component blocks and read each field independently.
    #
    # The first version matched ref, value and footprint in one regex with the
    # footprint group optional. That inverts the check: a component with no
    # footprint - the exact thing being looked for - failed to match the
    # pattern at all and vanished from the list, so the count quietly dropped
    # by one and the run still reported "every component maps to a footprint".
    # A check whose failure mode is to stop seeing the failure is worse than
    # no check. Found by deleting a footprint and watching it pass.
    blocks = re.split(r'\n\s*\(comp\b', txt)[1:]
    if not blocks:
        sys.exit("no components found in the netlist")
    comps = []
    for b in blocks:
        ref = re.search(r'\(ref "([^"]+)"\)', b)
        if not ref:
            continue
        val = re.search(r'\(value "([^"]*)"\)', b)
        fp = re.search(r'\(footprint "([^"]*)"\)', b)
        comps.append((ref.group(1),
                      val.group(1) if val else "",
                      fp.group(1) if fp else ""))

    missing, unresolved, mismatched, ok = [], [], [], 0
    for ref, value, fp in comps:
        if VIRTUAL.match(ref):
            continue
        if not fp:
            missing.append(f"{ref} ({value}) has no footprint")
            continue
        path = resolve(fp)
        if path is None:
            unresolved.append(f"{ref} ({value}): {fp} does not exist")
            continue
        # A footprint that resolves can still be the wrong one. The LTC4417
        # is a 24-pin part and carried SSOP-16 - a real footprint, a real
        # name, eight pads short, and unbuildable. Resolving a name and
        # matching a part are different questions, and only the first was
        # being asked.
        want = PINS.get(value)
        if want is not None:
            got = pad_count(path)
            if got < want:
                mismatched.append(
                    f"{ref} ({value}): {fp} has {got} pads, the symbol has "
                    f"{want} pins")
                continue
        ok += 1

    # Every failure category must be in the total. Leaving one out is how
    # a new check conceals itself: adding `mismatched` without adding it
    # here made the count silently drop by one and print PASS.
    total = ok + len(missing) + len(unresolved) + len(mismatched)
    good = not (missing or unresolved or mismatched)
    # Same [PASS]/[FAIL] line shape the other checkers print, so
    # check_hw_traceability can consume this as verification evidence.
    print(f"  [{'PASS' if good else 'FAIL'}] "
          f"{ok} of {total} components have a footprint that resolves")
    for m in missing + unresolved + mismatched:
        print("      -", m)

    if missing or unresolved or mismatched:
        print(f"\n{len(missing)} without a footprint, "
              f"{len(unresolved)} pointing at one that does not exist, "
              f"{len(mismatched)} with too few pads for the symbol")
        return 1
    print("\nevery component maps to a footprint that exists and has enough "
          "pads for its symbol")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
