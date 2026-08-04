#!/usr/bin/env python3
"""The single definition of every JXK-1 part number.

Every generator imports from here. A part number typed into a title block by
hand will eventually disagree with the one on the silkscreen, and the two
will be wrong in different ways at different times - which is exactly the
failure DO-254 configuration control exists to prevent.

Format and rules: docs/PART_NUMBERING.md

    python hardware/tools/part_numbers.py     # list and self-check
"""

import re
import sys

PROGRAMME = "JXK-1"
COMPANY = "JFOX Aircraft Co., Ltd."

# Revision letters skip I, O, Q, S, X and Z - misread as 1, 0, 0, 5,
# a cross-out and 2 on a marked board or a scanned drawing.
REV_LETTERS = "ABCDEFGHJKLMNPRTUVWY"

# part number -> (revision, description, block)
PARTS = {
    "1001": ("A", "FCU card assembly, 40 x 90 mm, 6-layer", "assembly"),
    "1101": ("A", "FCU bare board", "bare"),
    "1002": ("A", "Backplane assembly, 100 x 100 mm, 8-layer", "assembly"),
    "1102": ("A", "Backplane bare board", "bare"),
    "1401": (None, "FCU flight firmware - not baselined", "software"),
}

BLOCKS = {
    "assembly": (1000, 1099),
    "bare":     (1100, 1199),
    "harness":  (1200, 1299),
    "mech":     (1300, 1399),
    "software": (1400, 1499),
    "test":     (1500, 1599),
}

# Which board file carries which part number, so a generator cannot label
# itself as something else.
BOARDS = {
    "jfox-fmu": ("1001", "1101"),      # assembly, bare board
    "jfox-base": ("1002", "1102"),
}


def design(pn):
    """JXK-1-1001-A - what a drawing and a BOM line carry."""
    rev, _d, _b = PARTS[pn]
    if rev is None:
        raise SystemExit(f"{pn} has no revision - it is not baselined, so it "
                         f"cannot be put on a drawing yet")
    return f"{PROGRAMME}-{pn}-{rev}"


def article(pn, serial):
    """JXK-1-1001-A-0007 - what one physical unit carries.

    The serial follows the article for its life and is never reset when the
    revision changes. A serial that restarts per revision cannot support the
    DO-254 correlation between design data and the as-built item.
    """
    if not 1 <= int(serial) <= 9999:
        raise SystemExit(f"serial {serial} is outside 0001..9999")
    return f"{design(pn)}-{int(serial):04d}"


def check():
    bad = []
    for pn, (rev, descr, block) in sorted(PARTS.items()):
        lo, hi = BLOCKS[block]
        if not lo <= int(pn) <= hi:
            bad.append(f"{pn} is in block '{block}' ({lo}-{hi}) but its "
                       f"number is outside that range")
        if rev is not None and rev not in REV_LETTERS:
            bad.append(f"{pn} revision '{rev}' uses a letter the scheme "
                       f"excludes - {', '.join(set('IOQSXZ') & set(rev))} "
                       f"is misread on a marked board")
        if not re.fullmatch(r"\d{4}", pn):
            bad.append(f"{pn} is not four digits")

    # Every board must map to an assembly AND a bare board, and they must be
    # different numbers - they are different things with different acceptance
    # criteria, and using one number for both loses that distinction.
    for board, (asm, bare) in BOARDS.items():
        if asm == bare:
            bad.append(f"{board}: assembly and bare board share {asm}")
        for pn, want in ((asm, "assembly"), (bare, "bare")):
            if pn not in PARTS:
                bad.append(f"{board}: {pn} is not allocated")
            elif PARTS[pn][2] != want:
                bad.append(f"{board}: {pn} is a '{PARTS[pn][2]}' but is used "
                           f"as the {want}")

    print(f"  [{'PASS' if not bad else 'FAIL'}] {len(PARTS)} part numbers")
    for b in bad:
        print("      -", b)
    return 1 if bad else 0


def main():
    print(f"  {PROGRAMME}  -  {COMPANY}\n")
    for pn, (rev, descr, block) in sorted(PARTS.items()):
        ident = f"{PROGRAMME}-{pn}-{rev}" if rev else f"{PROGRAMME}-{pn}"
        print(f"  {ident:<16} {block:<9} {descr}")
    print()
    print(f"  example article identifier: {article('1001', 7)}")
    print()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
