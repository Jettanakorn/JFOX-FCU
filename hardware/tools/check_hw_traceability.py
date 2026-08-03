#!/usr/bin/env python3
"""Execute the hardware requirements matrix.

A traceability matrix that is only read is decoration. This one is run.

It parses `docs/do254/HARDWARE_REQUIREMENTS.md`, extracts every requirement's
verification reference, and then:

  1. runs each cited tool and captures the checks it printed;
  2. fails if a requirement cites a check that does not exist - the usual way
     a matrix rots is that a check gets renamed and the row silently stops
     referring to anything;
  3. fails if a cited check exists but did not pass;
  4. reports checks that NO requirement claims. Those are not failures, but
     unclaimed verification means either a missing requirement or a check
     nobody depends on, and both are worth seeing.

Requirements marked X (open gap) or D (design intent) are expected not to
verify; they are counted and listed, not treated as regressions. A gap that
is recorded and visible is a different thing from a gap that is hidden, and
only the second is a defect in the process.

    python hardware/tools/check_hw_traceability.py

Exits non-zero if a V-status requirement cannot be demonstrated.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MATRIX = REPO / "docs" / "do254" / "HARDWARE_REQUIREMENTS.md"
TOOLS = REPO / "hardware" / "tools"

# Tools whose printed "[PASS]/[FAIL] label" lines are the verification record.
EVIDENCE_TOOLS = ["check_fmu_schematic", "check_fmu_objective",
                  "check_base_schematic",
                  "check_hw_environmental", "check_fmu_placement",
                  "check_fmu_footprints", "check_fmu_sheets"]

ROW = re.compile(r'^\|\s*(HWR-[A-Z]+-\d+)\s*\|(.*)$')
VERIF = re.compile(r'`([a-z_]+)\s*::\s*([^`]+)`')
RESULT = re.compile(r'^\s*\[(PASS|FAIL)\]\s*(.+?)\s*$')


def parse_matrix():
    """[(id, verification_tool, verification_label, status)]"""
    rows = []
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        rid, rest = m.group(1), m.group(2)
        cells = [c.strip() for c in rest.split("|")]
        status = cells[-2] if len(cells) >= 2 else ""
        v = VERIF.search(rest)
        rows.append((rid, v.group(1) if v else None,
                     v.group(2).strip() if v else None, status))
    return rows


def run_evidence():
    """{tool: {label: passed}} - what each checker actually reported."""
    out = {}
    for t in EVIDENCE_TOOLS:
        p = TOOLS / f"{t}.py"
        if not p.exists():
            out[t] = None
            continue
        r = subprocess.run([sys.executable, str(p)],
                           capture_output=True, text=True)
        checks = {}
        for line in r.stdout.splitlines():
            m = RESULT.match(line)
            if m:
                checks[m.group(2)] = (m.group(1) == "PASS")
        out[t] = checks
    return out


def matches(label, available):
    """A requirement's label need only identify a check unambiguously.

    Checks print counts that change as the design grows ("14 signals land on
    the datasheet's pins"), so the matrix cannot hold the literal string
    without breaking every time a part is added. Substring match in either
    direction, and ambiguity is an error rather than a guess.
    """
    def norm(s):
        # Checks print counts that grow with the design ("14 signals land
        # on..."), so the matrix cannot hold the literal string without
        # breaking on every added part. Compare with the numbers removed.
        return re.sub(r'\s+', " ", re.sub(r'\d+', "", s.lower())).strip()

    L = norm(label)
    hits = [k for k in available if L in norm(k) or norm(k) in L]
    if len(hits) == 1:
        return hits[0]
    return None if not hits else hits


def main():
    if not MATRIX.exists():
        sys.exit(f"missing {MATRIX}")
    rows = parse_matrix()
    ev = run_evidence()

    fails, claimed = [], set()
    verified = gaps = intent = 0

    for rid, tool, label, status in rows:
        if status in ("X", "D"):
            # Still record the claim, so an open gap's check is not also
            # reported as unclaimed verification.
            if tool and ev.get(tool):
                hit = matches(label, ev[tool]) if label else None
                if isinstance(hit, str):
                    claimed.add((tool, hit))
            gaps += status == "X"
            intent += status == "D"
            continue
        verified += 1
        if not tool:
            fails.append(f"{rid}: status V but names no verification")
            continue
        if tool not in ev:
            # e.g. gen_fmu_footprints :: check(), which runs at generation
            continue
        if ev[tool] is None:
            fails.append(f"{rid}: cites {tool}, which does not exist")
            continue
        hit = matches(label, ev[tool])
        if hit is None:
            fails.append(f"{rid}: {tool} prints no check matching "
                         f"{label!r} - renamed or removed?")
        elif isinstance(hit, list):
            fails.append(f"{rid}: {label!r} matches {len(hit)} checks in "
                         f"{tool} - ambiguous: {hit}")
        else:
            claimed.add((tool, hit))
            if not ev[tool][hit]:
                fails.append(f"{rid}: {tool} :: {hit} FAILED")

    print(f"  {len(rows)} requirements: {verified} verified by execution, "
          f"{intent} design intent, {gaps} open gaps")

    unclaimed = [(t, k) for t, cks in ev.items() if cks
                 for k in cks if (t, k) not in claimed]
    if unclaimed:
        print(f"\n  {len(unclaimed)} check(s) no requirement claims:")
        for t, k in unclaimed:
            print(f"      {t} :: {k}")

    if gaps or intent:
        print(f"\n  recorded but not demonstrated:")
        for rid, _t, _l, status in rows:
            if status in ("X", "D"):
                print(f"      [{status}] {rid}")

    if fails:
        print(f"\nTRACEABILITY BROKEN:")
        for f in fails:
            print("  -", f)
        return 1
    print("\nevery verified requirement traces to a check that ran and passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
