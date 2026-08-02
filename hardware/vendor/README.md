# Vendored third-party design files

## PX4FMUv2.4.5.sch

- **Source**: https://github.com/PX4/Hardware — `FMUv2/PX4FMUv2.4.5.sch`
- **Format**: Eagle 7.1.0 XML (421 parts, 12 sheets, 262 named nets)
- **License**: CC BY-SA 3.0 — "Pixhawk project schematics and reference
  designs are licensed under CC BY-SA 3" (PX4/Hardware README)
- **Modified**: no. Byte-identical to upstream (1,017,958 bytes).

## PX4FMUv2.4.5.brd

- **Source**: same repository, `FMUv2/PX4FMUv2.4.5.brd`
- **Format**: Eagle board file (556,382 bytes), same license
- **Modified**: no.

The board that goes with the schematic above. Its purpose here is the
mounting geometry: `kicad-cli pcb import --format eagle` converts it, and
`M3_MOUNT1101..1104` give the module's real **30.000 × 30.000 mm** M3 pattern,
which the carrier outline in `hardware/carrier/` has to match exactly. Taken
from the manufactured board rather than measured off a drawing.

Note that board import *is* available from the command line even though
schematic import is not.

---

Both files are kept verbatim for traceability, on the same basis as
`px_mkfw.py` at the repo root: this is upstream material, not JFOX code, and
this repo's own coding standard (`docs/do178c/CODING_STANDARD.md`) does not
apply to it.

`docs/PX4FMUv2.4.5.pdf` is a plot of this same file. Where the two appear to
disagree, this file is authoritative — the PDF carries no extractable text and
anything sourced from it was read off rendered images.
