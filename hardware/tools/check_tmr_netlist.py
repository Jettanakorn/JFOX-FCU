#!/usr/bin/env python3
"""Assert the TMR carrier's design invariants against KiCad's own netlist.

The properties this checks are the ones that make the array redundant at all.
They are easy to break silently: merging three power nets into one, or leaving
a terminator on the carrier, both look fine in a schematic and are only
obvious once the hardware misbehaves. So they are checked mechanically,
against the netlist KiCad exports - not against the generator's intent.

Run (after gen_tmr_schematic.py) against the standalone carrier board:
  python hardware/tools/check_tmr_netlist.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware"
ROOT_SCH = HW / "carrier" / "carrier.kicad_sch"

CLI_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/bin/kicad-cli.exe",
    Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
]

CAN_CONNECTORS = {"J1", "J2", "J3"}
BRICK_IN = {"J4", "J5", "J6"}      # brick power in, one per module
MODULE_OUT = {"J7", "J8", "J9"}    # out to each module's J601
BRICK_CONNECTORS = BRICK_IN | MODULE_OUT


def find_cli():
    found = shutil.which("kicad-cli")
    if found:
        return found
    for c in CLI_CANDIDATES:
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found - install KiCad (see hardware/README.md)")


def export_netlist():
    out = Path(tempfile.gettempdir()) / "jfox_tmr_check.net"
    subprocess.run(
        [find_cli(), "sch", "export", "netlist", "--format", "kicadsexpr",
         "--output", str(out), str(ROOT_SCH)],
        check=True, capture_output=True, text=True,
    )
    return out.read_text(encoding="utf-8")


def parse_nets(text):
    """net name -> {(ref, pin)}. The netlist is s-expression but regularly
    formatted, so a scan is enough and avoids a parser dependency."""
    nets = {}
    for block in re.findall(r'\(net\b(.*?)(?=\n\t\t\(net\b|\n\t\)\s*\n\)\s*$)',
                            text, re.S):
        nm = re.search(r'\(name "([^"]*)"\)', block)
        if not nm:
            continue
        nodes = set(re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', block))
        nets[nm.group(1)] = nodes
    return nets


def main():
    nets = parse_nets(export_netlist())
    if not nets:
        sys.exit("could not parse any nets - netlist format may have changed")
    fails = []

    def refs(net):
        return {r for r, _ in nets.get(net, set())}

    # 1. Power independence. This is the whole reason for board-level
    #    redundancy: one brick failing must not take the other two boards down.
    brick_nets = [f"/VBRICK_{b}" for b in "ABC"]
    missing = [n for n in brick_nets if n not in nets]
    if missing:
        fails.append(f"missing power nets: {missing}")
    else:
        for a in range(3):
            for b in range(a + 1, 3):
                shared = refs(brick_nets[a]) & refs(brick_nets[b])
                if shared:
                    fails.append(
                        f"{brick_nets[a]} and {brick_nets[b]} share {sorted(shared)} "
                        "- the three supplies are commoned, which defeats "
                        "board-level redundancy")
        # Each supply must run in on exactly one brick connector and out on
        # exactly one module connector - a path, not a dead end.
        for n in brick_nets:
            gin, gout = refs(n) & BRICK_IN, refs(n) & MODULE_OUT
            if len(gin) != 1 or len(gout) != 1:
                fails.append(
                    f"{n} runs from {sorted(gin)} to {sorted(gout)}; expected "
                    "exactly one brick-in and one module-out connector")

    # 2. CAN is one bus reaching all three boards.
    for n in ("CAN_H", "CAN_L"):
        got = refs(n) & CAN_CONNECTORS
        if got != CAN_CONNECTORS:
            fails.append(f"{n} reaches {sorted(got)}, expected all of {sorted(CAN_CONNECTORS)}")

    # 3. No terminator on the carrier. Each module already carries a fixed
    #    120R (R409); adding a fourth in parallel would make the bus worse.
    #    Any resistor on CAN_H/CAN_L here means one crept in.
    for n in ("CAN_H", "CAN_L"):
        rs = sorted(r for r in refs(n) if r.startswith("R"))
        if rs:
            fails.append(
                f"{n} has resistor(s) {rs} on the carrier - the carrier must "
                "carry NO termination (see hardware/README.md)")

    # 4. Nothing dangles. A single-pin net on a pass-through board means a
    #    signal with no path, which is how the first carrier revision was
    #    wrong in a way the schematic still looked fine.
    for n, nodes in nets.items():
        if n and not n.startswith("unconnected") and len(nodes) < 2:
            fails.append(f"{n} terminates on one pin - no path across the board")

    # 5. Ground is common across all three boards - the star point.
    gnd = refs("GND")
    for c in CAN_CONNECTORS | BRICK_CONNECTORS:
        if c not in gnd:
            fails.append(f"GND does not reach {c}")

    print(f"parsed {len(nets)} nets from KiCad's netlist export")
    if fails:
        print("\nTMR INVARIANT FAILURES:")
        for f in fails:
            print("  -", f)
        raise SystemExit(1)
    print("all TMR invariants hold:")
    print("  - the three brick supplies are electrically independent")
    print("  - CAN_H/CAN_L form one bus reaching all three modules")
    print("  - no termination resistor on the carrier")
    print("  - no net terminates on a single pin")
    print("  - GND is common across all modules")


if __name__ == "__main__":
    main()
