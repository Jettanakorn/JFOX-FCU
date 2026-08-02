#!/usr/bin/env python3
"""Pull a pin-assignment table out of a component datasheet PDF.

Retyping pin numbers out of a datasheet is exactly the kind of task that
produces a schematic which passes ERC, fabricates cleanly, and does not work.
This extracts them instead, and prints the document number so the result can
be traced back to a specific revision.

    python hardware/tools/extract_datasheet_pins.py <datasheet.pdf> [--all]

Without --all it prints the page that looks like the pin-out table; with it,
every page containing pin-like rows. Reads the tables directly where the PDF
has them, and falls back to the page text where it does not.

Needs pdfplumber (`pip install pdfplumber`).
"""

import re
import sys
from pathlib import Path

# Names that show up in almost every pin table for the parts used here.
PIN_WORDS = ("VDD", "VSS", "GND", "SCK", "SCL", "SDI", "SDA", "SDO", "CS",
             "INT", "MISO", "MOSI", "NC", "VDDIO", "RESET", "HOLD", "WP")


def score(text):
    """How much this page looks like a pin table."""
    hits = sum(1 for w in PIN_WORDS if w in text.upper())
    numbered = len(re.findall(r'^\s*\d{1,2}\s+[A-Z]', text, re.M))
    heading = 3 if re.search(r'pin[\s-]*(out|assignment|description|configuration)',
                             text, re.I) else 0
    return hits + numbered + heading


def doc_id(pdf):
    """Manufacturer document number and revision, for provenance."""
    for page in list(pdf.pages)[:3] + list(pdf.pages)[-3:]:
        t = page.extract_text() or ""
        m = re.search(r'(Document number:?\s*\S+.*?)(?:\n|$)', t, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r'\b(DS-\d+|BST-[A-Z0-9-]+|Rev(?:ision)?\.?\s*[\d.]+)\b', t)
        if m:
            return m.group(1)
    return "(document number not found - record it by hand)"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_all = "--all" in sys.argv
    if not args:
        sys.exit(__doc__)
    path = Path(args[0])
    if not path.exists():
        sys.exit(f"no such file: {path}")

    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber not installed - pip install pdfplumber")

    with pdfplumber.open(path) as pdf:
        print(f"{path.name}: {len(pdf.pages)} pages")
        print(f"provenance: {doc_id(pdf)}\n")

        scored = []
        for i, page in enumerate(pdf.pages, 1):
            t = page.extract_text() or ""
            if t:
                scored.append((score(t), i, page, t))
        scored.sort(reverse=True, key=lambda r: r[0])
        if not scored:
            sys.exit("no extractable text - this PDF is images; render and read it")

        for s, i, page, t in (scored if show_all else scored[:1]):
            print(f"=== page {i} (score {s}) ===")
            tables = page.extract_tables()
            if tables:
                for tab in tables:
                    for row in tab:
                        cells = [c.strip() for c in row if c and c.strip()]
                        if cells:
                            print("  " + " | ".join(cells))
            else:
                print(t[:2000])
            print()

    print("Check the result against the datasheet's own figure before use, and\n"
          "record it in hardware/jfox-fmu-v1/PINOUTS.md with the provenance line.")


if __name__ == "__main__":
    main()
