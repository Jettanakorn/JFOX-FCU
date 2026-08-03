#!/usr/bin/env python3
"""Check the backplane. Nothing else does.

Every other checker in this directory reads
`hardware/jfox-fmu-v1/jfox-fmu.kicad_sch` and only that. The backplane's
LTC4417 ORing stage, its transient suppression, its fuses and its card
sockets have never been read by anything, so no claim about them is
provable - including the ones the requirements table marks as verified.

That is how the set came to have no power path at all: the fuses put out
`A_VDD_BRICK` and the cards read `+5V_CARRIER`, and nothing was in a
position to notice the two never meet.

Four checks, each aimed at a defect that was found by hand and could have
been found here:

  rails_reach_cards   every fused output arrives at a card socket
  oring_window        the divider chain produces the window it claims
  absolute_maximum    the accepted window fits every part on the rail
  valid_reaches_cards the feed-health outputs arrive at a card socket

    python hardware/tools/check_base_schematic.py

Exits non-zero if any of them fails.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-base-v1"
SCH = BOARD / "jfox-base.kicad_sch"

CLI_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/KiCad/10.0/bin/kicad-cli.exe",
    Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
]

# The three card sockets. A rail that does not reach one of these does not
# reach a card, whatever else it connects to.
SOCKETS = ("J1", "J2", "J3")

# LTC4417 comparators both sit at 1.000 V (ADI 4417fg p12). The divider is
# tapped twice from one chain, so:
#     UV = Rtot / (Rmid + Rbot)      OV = Rtot / Rbot
# Reproduced from the datasheet's own worked example rather than derived,
# which is how the FCU's version was validated.
COMPARATOR_V = 1.000

# Absolute maximum input voltage of every part that sits on the ORed rail or
# downstream of it, with the citation. The accepted over-voltage threshold
# must be below all of these, or the ORing stage passes a voltage that
# destroys something while reporting the feed as good.
#
# AP2112K is the binding one and it is not close: 6.0 V against an OV
# threshold that was 5.81 V, which is 190 mV before any transient.
ABS_MAX = {
    "AP2112K-3.3": (6.0, "Diodes AP2112 DS35501 rev 9 s6 - VIN 6.0 V max"),
    "TPS62132":    (17.0, "TI SLVSBM3D s6.1 - VIN 17 V max"),
    "ISOW1044":    (5.5, "TI SLLSFF7A s6.1 - VDD 5.5 V max"),
}


def cli():
    for c in CLI_CANDIDATES:
        if c.exists():
            return str(c)
    found = shutil.which("kicad-cli")
    if found:
        return found
    sys.exit("kicad-cli not found - see hardware/README.md")


def nets():
    """{net: {(ref, pin)}} for the whole backplane hierarchy."""
    out = Path(tempfile.gettempdir()) / "base_check.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"netlist export failed:\n{r.stdout}{r.stderr}")
    txt = out.read_text(encoding="utf-8")
    d = {}
    for blk in re.split(r'\n\t\t\(net\b', txt)[1:]:
        m = re.search(r'\(name "([^"]*)"\)', blk)
        if m:
            d[m.group(1).lstrip("/")] = set(
                re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(pin "([^"]+)"\)', blk))
    return d


def values():
    """{ref: value} - what part each designator actually is."""
    out = Path(tempfile.gettempdir()) / "base_check.net"
    txt = out.read_text(encoding="utf-8")
    return dict(re.findall(r'\(ref "([^"]+)"\)\s*\n\s*\(value "([^"]*)"\)', txt))


def ohms(v):
    """'787k' -> 787000.0. Values are written the way a BOM writes them."""
    scale = {"": 1, "r": 1, "R": 1, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6}
    s = v.strip()
    # EIA notation puts the multiplier where the decimal point would go:
    # 49k9 is 49.9k, 4R7 is 4.7 ohm, 1M5 is 1.5M. It exists so the point
    # cannot be lost to a smudge, and it is how E96 values are normally
    # written on a BOM - so a parser that only accepts a trailing suffix
    # rejects most of the resistors on this board.
    m = re.fullmatch(r'(\d+)([kKmMrR])(\d+)', s)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * scale[m.group(2)]
    m = re.fullmatch(r'([\d.]+)([kKmMrR]?)', s)
    if not m:
        raise ValueError(f"cannot read resistance {v!r}")
    return float(m.group(1)) * scale[m.group(2)]


# --------------------------------------------------------------------------
def rails_reach_cards(net, val, fails):
    """Every fused output must arrive at a card socket.

    This is the check that would have caught the set having no power path.
    The fuses produced A/B/C_VDD_BRICK and the card edge carried
    +5V_CARRIER; both boards generated cleanly, both passed DRC, and the
    two halves were simply not connected to each other.

    A fuse whose output goes nowhere is not a subtle fault, but nothing was
    reading this board, so nothing said so.
    """
    fuses = sorted(r for r, v in val.items()
                   if r.startswith("F") and r[1:].isdigit())
    if not fuses:
        fails.append("no fuses found on the backplane - the per-channel "
                     "power split is missing entirely")
        return 0

    # Follow the chain, do not just look at the fuse's own nets. A current
    # shunt sits between the fuse and the socket, so a one-hop test reports
    # a perfectly good path as broken - which it did, and would have sent
    # someone hunting a defect that had just been fixed.
    SERIES = ("F", "R", "L", "FB")

    def reaches_socket(start, seen=None):
        seen = seen or set()
        if start in seen:
            return False
        seen.add(start)
        for ref, _pin in net.get(start, ()):
            if ref in SOCKETS:
                return True
            if not ref.startswith(SERIES):
                continue
            for onward in net:
                if onward != start and any(r == ref for r, _q in net[onward]):
                    if reaches_socket(onward, seen):
                        return True
        return False

    ok = 0
    for f in fuses:
        downstream = [n for n, pins in net.items()
                      if (f, "2") in pins or (f, "1") in pins]
        reached = any(reaches_socket(n) for n in downstream)
        if reached:
            ok += 1
        else:
            fails.append(
                f"{f} output reaches no card socket ({', '.join(SOCKETS)}) - "
                f"its nets are {sorted(downstream)}. A fuse that feeds "
                f"nothing means the cards have no power path.")
    return ok


def oring_window(net, val, fails):
    """The divider chain must produce the window the design claims.

    Same equation as the FCU's ORing check, which was validated by
    reproducing the LTC4417 datasheet's worked example. Reused rather than
    re-derived - a second derivation is a second chance to be wrong.
    """
    chains = []
    # A chain is Rtop from the feed to UVn_SET, Rmid to OVn_SET, Rbot to GND.
    for n in (1, 2, 3):
        uv, ov = f"UV{n}_SET", f"OV{n}_SET"
        if uv not in net or ov not in net:
            continue
        rtop = rmid = rbot = None
        for ref, _pin in net[uv]:
            if not ref.startswith("R"):
                continue
            others = [m for m in net if (ref, "1") in net[m] or
                      (ref, "2") in net[m]]
            if any(o not in (uv, ov) and o != "GND" for o in others):
                rtop = ref
            elif ov in others:
                rmid = ref
        for ref, _pin in net[ov]:
            if ref.startswith("R") and any(
                    o == "GND" for o in net
                    if (ref, "1") in net[o] or (ref, "2") in net[o]):
                rbot = ref
        if rtop and rmid and rbot:
            chains.append((n, rtop, rmid, rbot))

    if not chains:
        fails.append("no LTC4417 divider chain found - the ORing stage's "
                     "thresholds cannot be checked, so the window it "
                     "accepts is whatever the resistors happen to be")
        return 0, []

    windows = []
    for n, rtop, rmid, rbot in chains:
        try:
            a, b, c = ohms(val[rtop]), ohms(val[rmid]), ohms(val[rbot])
        except (KeyError, ValueError) as e:
            fails.append(f"channel {n}: cannot read a divider value ({e})")
            continue
        tot = a + b + c
        uv = COMPARATOR_V * tot / (b + c)
        ov = COMPARATOR_V * tot / c
        windows.append((n, uv, ov))
    return len(windows), windows


def absolute_maximum(windows, val, fails):
    """The accepted window must fit every part downstream of it.

    A feed at the over-voltage threshold is by definition ACCEPTED - the
    controller reports it as good and passes it through. So the threshold
    is not a protection limit, it is a guarantee about what the rail can
    reach, and every part on that rail has to survive it with margin.
    """
    if not windows:
        return 0
    worst_ov = max(ov for _n, _uv, ov in windows)
    # Every part in ABS_MAX is downstream of this rail BY ARCHITECTURE -
    # they are on the cards, which this rail feeds. Filtering to parts
    # present in the backplane's own netlist found none of them and passed
    # silently, which is the exact failure this whole file exists to stop:
    # a check that stops seeing the thing it checks.
    ok = 0
    for v in sorted(ABS_MAX):
        limit, cite = ABS_MAX[v]
        margin = limit - worst_ov
        if margin < 0.3:
            fails.append(
                f"{v} absolute maximum is {limit:.1f} V and the ORing stage "
                f"accepts up to {worst_ov:.2f} V - {margin*1000:.0f} mV of "
                f"margin before any transient or tolerance. {cite}")
        else:
            ok += 1
    return ok


def valid_reaches_cards(net, val, fails):
    """The feed-health outputs must arrive at a card socket.

    Without them a silent single-feed failure consumes the redundancy with
    nobody informed: the set flies on one supply believing it has two, and
    the pre-arm checks cannot include supply health because there is no
    signal to read.
    """
    valid = sorted(n for n in net if n.endswith("_VALID"))
    if not valid:
        fails.append("no *_VALID net exists - the ORing controller's "
                     "feed-health outputs go nowhere, so the MCU cannot "
                     "tell which supply it is running on")
        return 0
    ok = 0
    for n in valid:
        refs = {r for r, _p in net[n]}
        # Reaching a socket is not enough - the net has to be DRIVEN. The
        # cards' three valid inputs reach their sockets perfectly well and
        # are connected to nothing that produces a signal, which is exactly
        # as useless as not reaching them, and looks identical from the
        # card's side.
        driver = refs & {r for r, v in val.items()
                         if v.startswith("LTC4417")}
        if refs & set(SOCKETS) and driver:
            ok += 1
        elif refs & set(SOCKETS):
            fails.append(
                f"{n} reaches a card socket but nothing drives it - "
                f"connected to {sorted(refs)}, none of which is the ORing "
                f"controller. The card reads a floating pin and cannot "
                f"tell which feed it is running on.")
        else:
            fails.append(
                f"{n} reaches no card socket - it connects only to "
                f"{sorted(refs)}, so no card can read it")
    return ok


def main():
    if not SCH.exists():
        sys.exit(f"missing {SCH} - run gen_base_schematic.py first")
    net = nets()
    val = values()
    fails = []

    n_rails = rails_reach_cards(net, val, fails)
    n_win, windows = oring_window(net, val, fails)
    n_abs = absolute_maximum(windows, val, fails)
    n_valid = valid_reaches_cards(net, val, fails)

    print(f"  [{'PASS' if not fails else 'FAIL'}] backplane: "
          f"{n_rails} fused rail(s) reach a card, {n_win} ORing window(s) "
          f"checked, {n_abs} part(s) fit the window, "
          f"{n_valid} valid signal(s) reach a card")
    for w in windows:
        print(f"      channel {w[0]}: accepts {w[1]:.2f} to {w[2]:.2f} V")
    for f in fails:
        print("      -", f)

    if fails:
        return 1
    print("\nthe backplane powers the cards, within a window every part "
          "survives, and tells them which feed they are on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
