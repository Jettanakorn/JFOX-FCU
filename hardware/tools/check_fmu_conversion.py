#!/usr/bin/env python3
"""Prove the hierarchical conversion did not change the board's connectivity.

gen_fmu_hierarchical.py rewrites 132 of the imported board's labels. That is a
lot of automated surgery on a design nobody can eyeball, so the result is
checked rather than trusted: export a netlist from the pristine import and one
from the converted copy, and compare them net by net.

The two are expected to differ in exactly one way - net *names* pick up a sheet
path prefix once a net is hierarchical rather than global (`/PX4FMUv2.4.5_4/FOO`
instead of `FOO`). What must not differ is which pins are joined to which.

Run:
  python hardware/tools/check_fmu_conversion.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ORIG = REPO / "hardware" / "PX4FMUv2.4.5" / "PX4FMUv2.4.5.kicad_sch"
CONV = REPO / "hardware" / "fmu-v2" / "fmu-v2.kicad_sch"

CLI_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/bin/kicad-cli.exe",
    Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
]


def find_cli():
    found = shutil.which("kicad-cli")
    if found:
        return found
    for c in CLI_CANDIDATES:
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found - see hardware/README.md")


def netlist(sch, tag):
    out = Path(tempfile.gettempdir()) / f"fmu_cmp_{tag}.net"
    subprocess.run([find_cli(), "sch", "export", "netlist", "--format",
                    "kicadsexpr", "--output", str(out), str(sch)],
                   check=True, capture_output=True, text=True)
    return out.read_text(encoding="utf-8")


def nets_as_pinsets(text):
    """{frozenset of (ref, pin)} - net identity by membership, ignoring names,
    since names legitimately change when a net becomes hierarchical.

    References are normalised too: annotate_tmr_instances.py suffixes them per
    board (C101 -> C101A/B/C), so a raw comparison would report every net as
    changed. Only a trailing board letter directly after a digit is stripped,
    which cannot collide with a real designator.
    """
    sets = set()
    for blk in re.split(r'\n\t\t\(net\b', text)[1:]:
        nodes = frozenset(
            (re.sub(r'(?<=\d)[ABC]$', "", ref), pin)
            for ref, pin in
            re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))
        if len(nodes) > 1:          # single-pin nets carry no connectivity
            sets.add(nodes)
    return sets


def main():
    a = nets_as_pinsets(netlist(ORIG, "orig"))
    b = nets_as_pinsets(netlist(CONV, "conv"))

    print(f"  pristine import : {len(a)} multi-pin nets")
    print(f"  converted copy  : {len(b)} multi-pin nets")

    lost, gained = a - b, b - a
    if not lost and not gained:
        print("\nconnectivity identical: every net joins exactly the same pins")
        return

    print(f"\n  nets in the import but not the conversion: {len(lost)}")
    for s in sorted(lost, key=len, reverse=True)[:5]:
        print(f"    {sorted(s)[:6]}{' ...' if len(s) > 6 else ''}")
    print(f"  nets in the conversion but not the import: {len(gained)}")
    for s in sorted(gained, key=len, reverse=True)[:5]:
        print(f"    {sorted(s)[:6]}{' ...' if len(s) > 6 else ''}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
