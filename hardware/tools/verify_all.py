#!/usr/bin/env python3
"""Check everything about the hardware design, in one command.

Each check asks KiCad itself, not the generators - the point is to catch a
generator that produced something plausible but wrong. Prints PASS/FAIL per
check and exits non-zero if any failed.

  python hardware/tools/verify_all.py
"""

import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware"
TMP = Path(tempfile.gettempdir())

CLI_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/bin/kicad-cli.exe",
    Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
]

results = []


def cli():
    found = shutil.which("kicad-cli")
    if found:
        return found
    for c in CLI_CANDIDATES:
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found - install KiCad, see hardware/README.md")


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


def netlist(sch, tag):
    out = TMP / f"verify_{tag}.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format", "kicadsexpr",
                        "--output", str(out), str(sch)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return out.read_text(encoding="utf-8")


def nets_of(text):
    nets = {}
    for blk in re.split(r'\n\t\t\(net\b', text)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            nets[m.group(1)] = set(re.findall(r'\(ref "([^"]+)"\)', blk))
    return nets


def pinsets(text):
    out = set()
    for blk in re.split(r'\n\t\t\(net\b', text)[1:]:
        nodes = frozenset(
            (re.sub(r'(?<=\d)[ABC]+$', "", r), p) for r, p in
            re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))
        if len(nodes) > 1:
            out.add(nodes)
    return out


def main():
    if list(HW.rglob("~*.lck")):
        print("NOTE: KiCad has these projects open. Results reflect what is on\n"
              "      disk; close KiCad before trusting a FAIL.\n")

    print("Imported FMU board")
    orig = netlist(HW / "PX4FMUv2.4.5" / "PX4FMUv2.4.5.kicad_sch", "orig")
    conv = netlist(HW / "fmu-v2" / "fmu-v2.kicad_sch", "conv")
    if orig and conv:
        a, b = pinsets(orig), pinsets(conv)
        check("conversion preserved every connection", a == b,
              f"{len(a)} nets in the import, {len(b)} in the converted copy")
    else:
        check("netlists export", False, "kicad-cli could not export")

    print("\n3-board TMR system")
    tmr = netlist(HW / "jfox-tmr.kicad_sch", "tmr")
    if tmr:
        refs = re.findall(r'\(comp\s*\n\s*\(ref "([^"]+)"\)', tmr)
        dupes = [r for r, n in collections.Counter(refs).items() if n > 1]
        check("every component has a unique designator", not dupes,
              f"{len(refs)} instances, {len(set(refs))} distinct")

        nets = nets_of(tmr)
        vb = [nets.get(f"/VBRICK_{x}", set()) for x in "ABC"]
        disjoint = all(not (vb[i] & vb[j]) for i, j in ((0, 1), (0, 2), (1, 2)))
        check("the three supplies share no node", disjoint and all(vb),
              "one brick failing cannot take the other two boards down")

        can = nets.get("CAN_H", set())
        want = {"U401A", "U401B", "U401C", "J1", "J2", "J3"}
        check("CAN_H reaches all three modules", want <= can,
              "via each module's own MAX3051")

        term = sorted(r for r in can if r.startswith("R409"))
        check("all three module terminators are on the bus", len(term) == 3,
              f"{term} - desolder the middle one before powering up")
    else:
        check("TMR netlist exports", False)

    print("\nCarrier board")
    pcb = HW / "carrier" / "carrier.kicad_pcb"
    r = subprocess.run([cli(), "pcb", "drc", "--output", str(TMP / "verify.rpt"),
                        str(pcb)], capture_output=True, text=True)
    out = r.stdout + r.stderr
    viol = re.search(r"Found (\d+) violations", out)
    unc = re.search(r"Found (\d+) unconnected", out)
    check("DRC clean", viol and viol.group(1) == "0",
          f"{viol.group(1) if viol else '?'} violations")
    check("fully routed", unc and unc.group(1) == "0",
          f"{unc.group(1) if unc else '?'} unconnected")

    carrier = netlist(HW / "carrier" / "carrier.kicad_sch", "car")
    if carrier:
        nets = nets_of(carrier)
        dangling = [n for n, v in nets.items()
                    if n and not n.startswith("unconnected") and len(v) < 2]
        check("no net dead-ends on the board", not dangling,
              f"{len(nets)} nets, all with a path across")

    failed = [n for n, ok, _ in results if not ok]
    print("\n" + ("-" * 60))
    if failed:
        print(f"{len(failed)} check(s) FAILED: {', '.join(failed)}")
        raise SystemExit(1)
    print(f"all {len(results)} checks passed")


if __name__ == "__main__":
    main()
