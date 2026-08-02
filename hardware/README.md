# hardware/ — TMR schematic work

Hardware design for the 3-board TMR array. Firmware lives everywhere else in
this repo; nothing here is compiled or linked into it.

## Why this directory exists

The only copy of the PX4FMUv2.4.5 schematic previously in this repo was
`docs/PX4FMUv2.4.5.pdf` — a vector PDF with **no extractable text**. Every
hardware fact taken from it had to be read off rendered page images by eye.
That is fine for orientation and bad as a foundation for a new board design.

The same design is published in machine-readable form: `PX4/Hardware`'s
`FMUv2/PX4FMUv2.4.5.sch`, Eagle 7.1.0 XML. The PDF is a plot of that file.
So connector pinouts and net membership are now **derived** from the netlist
rather than transcribed.

## Layout

| Path | What |
|---|---|
| `vendor/PX4FMUv2.4.5.sch` | Upstream Eagle source, unmodified. See `vendor/README.md`. |
| `tools/extract_eagle_nets.py` | Parses the above → `PX4FMUv2.4.5_NETS.md`. |
| `PX4FMUv2.4.5_NETS.md` | **Generated.** Connector/net reference. Do not hand-edit. |
| `tools/gen_tmr_schematic.py` | Emits the KiCad project below. |
| `jfox-tmr.kicad_pro` / `.kicad_sch` | **Generated.** Root: three FMU instances + carrier. |
| `fmu-v2.kicad_sch` | **Generated placeholder** — see "Status" below. |
| `carrier.kicad_sch` | **Generated.** The new carrier/backplane design. |
| `jfox.kicad_sym` / `sym-lib-table` | **Generated.** Connector symbols, registered as a project library. |
| `tools/check_tmr_netlist.py` | Asserts the redundancy invariants against KiCad's netlist. |

Regenerate and verify with:

```bash
python hardware/tools/extract_eagle_nets.py && python hardware/tools/gen_tmr_schematic.py && python hardware/tools/check_tmr_netlist.py
```

(On this machine `python` on `PATH` is the Microsoft Store stub — use
`C:\Users\Jetta\AppData\Local\Programs\Python\Python312\python.exe`.)

## The TMR project

`jfox-tmr.kicad_sch` is the root. It instantiates **one** sheet file
(`fmu-v2.kicad_sch`) three times as FMU-A/B/C — that is KiCad's own idiom for
identical repeated blocks, and it means editing the board design once edits
all three while KiCad still keeps their reference designators distinct via
per-instance paths.

Signal split, which is the load-bearing design decision:

- `CAN_H`, `CAN_L`, `GND`, `SAFETY` are **global labels** — correct precisely
  because all three boards genuinely share those nets.
- Power and servo signals are **hierarchical pins**, so each board's stay
  separate. That separation is the entire point of board-level redundancy; a
  global label there would silently short all three supplies together.

That second point is the kind of mistake that looks fine in a schematic and
only shows up when hardware misbehaves, so it is checked mechanically.
`tools/check_tmr_netlist.py` runs `kicad-cli sch export netlist` and asserts,
against KiCad's own output:

- the three brick supplies share no node (independent power),
- `CAN_H`/`CAN_L` reach all three modules (one bus, not three stubs),
- **no resistor sits on CAN_H/CAN_L on the carrier** — each module already has
  a fixed 120Ω R409, and a fourth in parallel would make the bus worse,
- each board's six servo channels reach only its own connector,
- `GND` is common across all modules.

Currently all five hold. Each check is negative-tested (deliberately merging
two supply nets, or dropping a module off the bus, both get caught).

## Status

**`fmu-v2.kicad_sch` is a placeholder.** It defines the correct *interface*
(the hierarchical pins the root wires to) but not the board's contents. Fill
it in with:

1. Install KiCad (see below).
2. **File → Import → Non-KiCad Schematic** on `vendor/PX4FMUv2.4.5.sch`.
3. Attach the imported design's connectors to the hierarchical labels already
   present — the placeholder's on-sheet note lists the exact mapping
   (`CAN_H`/`CAN_L` → J405 pins 2/3, and so on).

This step is manual because `kicad-cli` has **no** schematic import
subcommand — verified against the KiCad 10 CLI docs, which document
`kicad-cli pcb import` but nothing equivalent for schematics. Import is
GUI-only.

## Installing KiCad

Current stable is **10.0.5** (released 2026-07-22). Install with:

```bash
winget install -e --id KiCad.KiCad
```

This is the x86-64 NSIS installer straight from KiCad's GitHub release.
Confirm it landed:

```bash
kicad-cli version
```

**Note the install location.** winget installs KiCad at *current-user* scope,
so it lands in `%LOCALAPPDATA%\Programs\KiCad\10.0\bin` — **not**
`C:\Program Files\KiCad`. Nothing is added to `PATH`, so either add that `bin`
directory or call the executable by full path.
`tools/check_tmr_netlist.py` probes both locations plus `PATH`.

**Why 10.x**, checked rather than assumed — KiCad 10's own docs list Eagle
(Autodesk) `.sch` XML, "Eagle version 6.x and later", among the supported
import formats, and `vendor/PX4FMUv2.4.5.sch` is Eagle 7.1.0. The docs also
confirm the importer extracts symbols from the file's embedded libraries into
a generated KiCad symbol library, which matches this file's seven embedded
libraries (`pixhawk2`, `con-hirose-df13`, `SparkFun`, …).

**Expect one Eagle-specific ERC violation.** KiCad documents a *"Bus Entry
needed"* error that "only applies to projects imported from EAGLE projects" —
places where the importer could not add bus entries automatically and you have
to place them by hand. Post-import cleanup, not a broken import.

**Verified with KiCad 10.0.5**: it parses all four files and resolves the
hierarchy — ERC enumerates `/`, `/FMU-A/`, `/FMU-B/`, `/FMU-C/` and
`/CARRIER/`, so the three-instance structure works. The netlist exports
cleanly and the invariants above hold.

ERC reports **94 violations, and that is expected**: 81 `isolated_pin_label`
warnings and 13 `label_dangling` errors, all of them downstream of
`fmu-v2.kicad_sch` being an empty placeholder. Labels crossing into it have
nothing to attach to yet. These want re-judging *after* the Eagle import, not
before — chasing them against a stub would be wasted work.

Two real defects were caught this way and fixed:

- **Symbol instance paths were wrong.** They used each child file's own UUID
  instead of `/<root-uuid>/<sheet-element-uuid>`. The files still parsed and
  the generator's structural checks still passed, but KiCad placed every
  carrier symbol on the root sheet. Only ERC surfaced it. The generator now
  checks instance-path rooting directly.
- **Symbols resolved to no registered library** (10 `lib_symbol_issues`
  warnings). Fixed by emitting a real `jfox.kicad_sym` plus a `sym-lib-table`.

## Out of scope

PCB layout. The netlist, footprint assignment, board outline and routing
constraints are producible here; component placement and routing are
interactive work for KiCad's PCB editor. A generated `.kicad_pcb` would open
to a rat's nest and read as finished work.

Useful for that step when it comes: unlike schematics, **boards** *can* be
converted from the command line (`kicad-cli pcb import`). Upstream also
publishes `FMUv2/PX4FMUv2.4.5.brd`, so the module's exact M3 mounting-hole
coordinates and outline can be lifted from the real board rather than measured
off a drawing — which is what the carrier's outline has to match.

How three boards' motor outputs arbitrate into one is also unresolved and
deliberately not committed to copper — `flight::redundancy::TmrVoter` is still
not wired into `motor_task` (see `HARDWARE_BRINGUP.md`, "What's still open
after Stage 3"). The carrier brings all three out separately.

## What the netlist confirmed, and what it corrected

Checked against the claims previously made from the PDF images:

| Claim | Result |
|---|---|
| CAN1: STM32 PD0/PD1 → MAX3051 (U401) → J405 | Confirmed |
| R409 = 120Ω fixed across CAN_H/CAN_L, no jumper | Confirmed (`RC0402FR-07120RL`) |
| CAN2 on PB6/PB12 with no transceiver | Confirmed — series resistors only, out via J203 |
| Safety switch J702 belongs to the IO co-processor | Confirmed — `SAFETY` → `U801.PB5` |
| J601 is the Brick power input | Confirmed — `VDD_5V_BRICK`, plus voltage/current sense |
| 4 × M3 mounting holes for stacking | Confirmed |
| Power-source selector is "BQ24315-based" | **Wrong.** It is an **LTC4417** (U1101) driving three dual P-channel MOSFETs. The BQ24315s (U601/U602) are separate overvoltage-protection parts. |

The last row is exactly why this directory exists.

## Licensing

`vendor/PX4FMUv2.4.5.sch` is **CC BY-SA 3.0** from the Pixhawk project.
Share-alike propagates to derivative designs. A carrier board that *embeds*
converted FMU sheets is a derivative; one drawn against only the connector
pinouts is a much weaker claim. Worth a lawyer's read before this ships as
part of a commercial product — see `vendor/README.md` for the attribution.
