#!/usr/bin/env python3
"""Courtyard geometry, read properly rather than by regex window.

Both the board generator and the layout scorer need one thing from a
footprint: how much board area it occupies. Both got it wrong, in the same
way, twice.

The first version matched only ``fp_rect``. Almost no KiCad footprint draws
its courtyard as a rectangle - they use four ``fp_line`` segments - so nearly
every part fell through to a placeholder size. A 60-pin mezzanine and a 27 mm
LQFP176 were both scored as 3 x 3 mm squares.

The second version added ``fp_line`` but kept the shape of the regex:

    \\(fp_line \\(start ...\\) \\(end ...\\)[\\s\\S]{0,300}?\\(layer "F.CrtYd"\\)

which does not ask whether THAT line is on the courtyard layer. It asks
whether a courtyard layer token appears somewhere in the next 300 characters,
which for a small footprint is true of nearly every silkscreen and fab line
in the file. R8 came out 0.308 x 0.000 mm - an 0402 measured as a zero-height
sliver - and the scorer duly reported no overlaps on a board where DRC found
123.

So: parse the s-expression. Find each graphic token, take its balanced
bracket range, and check the layer inside that range and nowhere else. It is
barely more code than the regex and it cannot silently agree with itself.
"""

import math
import re

GRAPHICS = ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc")


def sexprs(text, token):
    """Yield the balanced (token ...) expressions in text."""
    for m in re.finditer(r'\(%s[\s(]' % re.escape(token), text):
        start = m.start()
        depth, i, instr, esc = 0, start, False, False
        while i < len(text):
            c = text[i]
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
                        yield text[start:i + 1]
                        break
            i += 1


def courtyard_bbox(text):
    """(min_x, min_y, max_x, max_y) of the courtyard, or None if none drawn.

    Only graphics whose OWN layer is F.CrtYd or B.CrtYd contribute. Both
    courtyard layers are read together: a footprint placed on the back has
    its courtyard on B.CrtYd, and the extent is the same either way.
    """
    xs, ys = [], []
    for token in GRAPHICS:
        for e in sexprs(text, token):
            if not re.search(r'\(layer "[FB]\.CrtYd"\)', e):
                continue
            if token == "fp_circle":
                c = re.search(r'\(center (-?[\d.]+) (-?[\d.]+)\)', e)
                d = re.search(r'\(end (-?[\d.]+) (-?[\d.]+)\)', e)
                if c and d:
                    cx, cy = float(c.group(1)), float(c.group(2))
                    r = math.hypot(float(d.group(1)) - cx,
                                   float(d.group(2)) - cy)
                    xs += [cx - r, cx + r]
                    ys += [cy - r, cy + r]
                continue
            # fp_line, fp_rect and fp_arc all carry plain coordinate pairs;
            # fp_poly carries a pts list. Taking every pair in the
            # expression covers all of them, and an arc's midpoint is on the
            # arc so it cannot push the box outside the true extent by more
            # than the sagitta - which for a courtyard is zero, they are
            # straight.
            for p in re.finditer(r'\((?:start|end|mid|center|xy) '
                                 r'(-?[\d.]+) (-?[\d.]+)\)', e):
                xs.append(float(p.group(1)))
                ys.append(float(p.group(2)))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def pad_bbox(text, excess=0.25):
    """Fallback extent: the pad bounding box plus the IPC courtyard excess.

    Used only for footprints that genuinely draw no courtyard. It is smaller
    than a real courtyard would be, so it is a floor, not a substitute.
    """
    xs, ys = [], []
    for e in sexprs(text, "pad"):
        a = re.search(r'\(at (-?[\d.]+) (-?[\d.]+)', e)
        s = re.search(r'\(size ([\d.]+) ([\d.]+)\)', e)
        if not (a and s):
            continue
        x, y = float(a.group(1)), float(a.group(2))
        w, h = float(s.group(1)), float(s.group(2))
        xs += [x - w / 2 - excess, x + w / 2 + excess]
        ys += [y - h / 2 - excess, y + h / 2 + excess]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def extent(text):
    """(offset_x, offset_y, width, height), courtyard first, pads second.

    Raises rather than inventing a size. A placement scored against a
    made-up extent is worse than no score, because it reads as agreement.
    """
    b = courtyard_bbox(text) or pad_bbox(text)
    if b is None:
        raise ValueError("footprint has neither a courtyard nor pads")
    x0, y0, x1, y1 = b
    return x0, y0, x1 - x0, y1 - y0


if __name__ == "__main__":
    import sys
    from pathlib import Path
    for arg in sys.argv[1:]:
        t = Path(arg).read_text(encoding="utf-8")
        ox, oy, w, h = extent(t)
        print(f"{Path(arg).stem}: {w:.3f} x {h:.3f} mm at ({ox:.3f}, {oy:.3f})")
