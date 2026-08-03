#!/usr/bin/env python3
"""Check the BOM against the declared DO-160G environmental category.

DO-160G is a *test* standard. Qualification happens in a chamber, on real
hardware, and nothing in this repository can produce it. What can be done
before a board exists is to check that the parts chosen are capable of the
category being claimed - because a temperature range is a datasheet fact, and
a part that is only rated to -40 C cannot be qualified to a category whose low
operating temperature is -55 C no matter how the test is run.

That is not a hypothetical constraint here. The STM32H753IIT6's ordering-code
suffix "6" is -40 to +85 C (ST DM00388325 p346), and ST does not offer this
part at -55 C in any grade. The MCU choice therefore already decided which
DO-160 Section 4 categories this board can ever hold, before anyone chose a
category. This tool makes that visible instead of leaving it to be discovered
during qualification.

    python hardware/tools/check_hw_environmental.py

Exits non-zero if a part cannot support the declared category, or if a part on
the BOM has no temperature data recorded.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
SCH = BOARD / "jfox-fmu.kicad_sch"

# --------------------------------------------------------------------------
# The declared category. See docs/do254/DO160_ENVIRONMENTAL.md for why.
# --------------------------------------------------------------------------
# DO-160G Section 4 category A2: partially controlled temperature, pressurised
# location, -15 to +70 C operating. Chosen because it is the most demanding
# category the current BOM can actually support - not because it matches the
# installation, which is not yet defined. Changing this line is the whole
# interface: raise it and the tool names every part that cannot follow.
DECLARED = dict(category="A2", low_c=-15.0, high_c=+70.0,
                source="DO-160G Section 4, Category A2")

# --------------------------------------------------------------------------
# Operating temperature range per part, from the manufacturer's datasheet.
#
# `verified` means the range was read out of the datasheet in this repository
# (hardware/jfox-fmu-v1/datasheets/) and the citation is recorded. Anything
# marked False is a placeholder: it is NOT evidence, and this tool reports it
# as a gap rather than quietly accepting it. Assumed data is how a BOM ends up
# qualified on paper and failing in a chamber.
# --------------------------------------------------------------------------
TEMP = {
    "STM32H753IIT6": (-40, 85, True,
                      "ST DM00388325 p346, ordering code suffix 6"),
    "ICM-42688-P":   (-40, 85, True, "TDK DS-000347 rev 1.6"),
    "ICM-45686":     (-40, 85, True,
                      "TDK DS-000577 rev 1.0 p20, specified temperature range"),
    "ICP-20100":     (-40, 85, True, "TDK DS-000416 rev 1.3"),
    "BMM150":        (-40, 85, True,
                      "BST-BMM150-DS001-05 p9, operating temperature active"),
    "FM25V02A":      (-40, 85, True,
                      "Infineon 001-90865 p2, industrial temperature"),
    "ISOW1044":      (-40, 125, True, "TI SLLSFF7A"),
    "TPS62132":      (-40, 85, True, "TI SLVSAG7F"),

    # Not yet read out of a datasheet in this repo.
    "BMI088":        (-40, 85, False, "assumed - no datasheet in repo"),
    "BMP388":        (-40, 85, False,
                      "assumed - operating range is in a table this tool "
                      "could not extract; see FULL_ACCURACY"),
    "LTC4417CGN":    (-40, 85, True,
                      "ADI 4417fg p2 ordering table, I grade "
                      "(H grade is -40/+125)"),
    "AP2112K-3.3":   (-40, 85, False, "assumed - no datasheet in repo"),
    # The ORing pass devices are a generic PMOS symbol; no specific
    # part is selected yet, so there is nothing to cite.
    # EMC protection parts. Generic symbols with no specific part chosen
    # yet, so there is nothing to cite - reported as gaps, not assumed away.
    "USBLC6-2SC6":   (-40, 125, False, "assumed - ST datasheet not in repo"),
    "SMAJ6.0A":      (-55, 150, False, "assumed - no datasheet in repo"),
    "PESD2CAN":      (-55, 150, False, "assumed - no datasheet in repo"),
    "90R@100MHz":    (-40, 125, False, "assumed - no choke part selected"),
    "51uH CM":       (-40, 125, False, "assumed - no choke part selected"),
    "600R@100MHz":   (-55, 125, False, "assumed - no ferrite part selected"),
    "PMOS":          (-40, 85, False,
                      "assumed - no part selected for the ORing FETs"),
    "AP22804AW5":    (-40, 85, False, "assumed - no datasheet in repo"),
}

# Range over which a part meets its published accuracy, where that is
# NARROWER than the range over which it merely operates.
#
# This distinction matters and is easy to lose. The BMP388 operates well past
# +65 C but Bosch specifies accurate altitude measurement only from -20 to
# +65 C (BST-BMP388-DS001-07 p3). A barometer that is powered, responding, and
# quietly out of specification is a worse failure than one that has stopped:
# the flight stack has no way to know the reading is wrong. A category whose
# limits exceed this range is not disqualified, but the altitude solution's
# accuracy claim does not hold across it, and that has to be a stated
# limitation rather than an accident.
FULL_ACCURACY = {
    "BMP388": (-20, 65, "BST-BMP388-DS001-07 rev 1.7 p3"),
}

# Passives and connectors. Standard MLCC/thick-film parts comfortably exceed
# the declared category; they are excluded by class rather than listed, and
# the exclusion is stated so it is a decision rather than an oversight.
# "J" added: JST-GH connectors and the USB/SD sockets are rated well
# past this category and are excluded by class, like the passives.
# "D" covers the status LEDs.
PASSIVE_PREFIX = ("C", "R", "L", "X", "JP", "#", "J", "D")
CONNECTOR_VALUES = {"USB-C", "microSD", "SolderJumper_2_Bridged", "PWR_FLAG"}


def cli():
    for c in (Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe"),
              Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
        if c.exists():
            return str(c)
    sys.exit("kicad-cli not found")


def bom():
    out = Path(tempfile.gettempdir()) / "fmu_env.net"
    r = subprocess.run([cli(), "sch", "export", "netlist", "--format",
                        "kicadsexpr", "--output", str(out), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"netlist export failed:\n{r.stdout}\n{r.stderr}")
    txt = out.read_text(encoding="utf-8")
    parts = {}
    for b in re.split(r'\n\s*\(comp\b', txt)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', b)
        val = re.search(r'\(value "([^"]*)"\)', b)
        if ref:
            parts[ref.group(1)] = val.group(1) if val else ""
    return parts


def main():
    parts = bom()
    lo, hi = DECLARED["low_c"], DECLARED["high_c"]
    print(f"  declared: {DECLARED['source']} ({lo:+.0f} to {hi:+.0f} C)")

    fails, unverified, checked = [], [], 0
    seen = set()
    for ref, val in sorted(parts.items()):
        if ref.startswith(PASSIVE_PREFIX) or val in CONNECTOR_VALUES:
            continue
        if val in seen:
            continue
        seen.add(val)
        if val not in TEMP:
            fails.append(f"{ref} ({val}): no temperature data recorded")
            continue
        tlo, thi, verified, src = TEMP[val]
        checked += 1
        if tlo > lo:
            fails.append(f"{ref} ({val}): rated from {tlo:+d} C, category "
                         f"needs {lo:+.0f} C - {src}")
        if thi < hi:
            fails.append(f"{ref} ({val}): rated to {thi:+d} C, category "
                         f"needs {hi:+.0f} C - {src}")
        if not verified:
            unverified.append(f"{val}: {src}")

    ok = not fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {checked} active parts support "
          f"DO-160G category {DECLARED['category']}")
    for f in fails:
        print("      -", f)

    narrow = []
    for val in sorted(seen):
        if val in FULL_ACCURACY:
            alo, ahi, src = FULL_ACCURACY[val]
            if alo > lo or ahi < hi:
                narrow.append(f"{val}: full accuracy only {alo:+d} to "
                              f"{ahi:+d} C, category spans {lo:+.0f} to "
                              f"{hi:+.0f} C - {src}")
    if narrow:
        print(f"\n  [WARN] {len(narrow)} part(s) operate across the category "
              f"but are not accurate across it:")
        for n in narrow:
            print("      -", n)

    # The margin is the interesting number: it says how much category
    # headroom the BOM has before the limiting part becomes the problem.
    rated = [(v, TEMP[v][0], TEMP[v][1]) for v in seen if v in TEMP]
    if rated:
        # Tie-broken by name. Most of this BOM is -40/+85, so "the limiting
        # part" is a tie and picking arbitrarily made the line name a
        # different part on each run - which reads like the design changed
        # when nothing did.
        cold = max(rated, key=lambda r: (r[1], r[0]))
        hot = min(rated, key=lambda r: (r[2], r[0]))
        print(f"\n  limiting parts: {cold[0]} sets the cold floor at "
              f"{cold[1]:+d} C, {hot[0]} the hot ceiling at {hot[2]:+d} C")
        print(f"  so no DO-160 category below {cold[1]:+d} C is reachable "
              f"with this BOM, whatever the test regime")

    if unverified:
        print(f"\n  [FAIL] {len(unverified)} part(s) carry ASSUMED temperature "
              f"data, which is not evidence:")
        for u in unverified:
            print("      -", u)

    # ----------------------------------------------------------------------
    # Thermal management. See DO160_ENVIRONMENTAL.md, "Thermal control".
    # ----------------------------------------------------------------------
    vals = set(parts.values())

    # Board hot-spot monitoring. The five sensor dies each report their own
    # temperature, which is the right measurement for compensating a sensor
    # and the wrong one for protecting a regulator. Nothing on this board
    # measures the TPS62132 or the two ISOW1044 converters.
    monitors = [r for r, v in parts.items()
                if re.match(r'^(TMP\d|LM7[45]|ADT7|MCP98|STTS|SI705|TMP1)',
                            v, re.I)]
    have_monitor = bool(monitors)
    print(f"\n  [{'PASS' if have_monitor else 'FAIL'}] board hot-spot "
          f"temperature monitor present")
    if not have_monitor:
        print("      - no board-level temperature sensor; the only thermal "
              "data comes from sensor dies, which cannot protect the "
              "regulator or the isolators")

    # Heater, deliberately absent. Asserted the same way the absent IO
    # co-processor is: so that adding one is a visible decision that forces
    # the power budget and the baro thermal separation to be revisited,
    # rather than something that appears in a layout unannounced.
    heaters = [r for r, v in parts.items()
               if re.search(r'heat|htr', v, re.I) or r.startswith("HTR")]
    print(f"  [{'PASS' if not heaters else 'FAIL'}] no IMU heater "
          f"(deferred - see DO160_ENVIRONMENTAL.md)")
    if heaters:
        print(f"      - heater part(s) {heaters} present, but the deferred "
              "decision in DO160_ENVIRONMENTAL.md has not been revisited: "
              "power budget, baro thermal separation, rail-cycling "
              "interaction and an independent over-temperature cutout")

    if fails or unverified or not have_monitor or heaters:
        return 1
    print("\nevery active part is rated for the declared category, from a "
          "cited datasheet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
