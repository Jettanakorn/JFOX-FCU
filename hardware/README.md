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

**The Eagle import is done** (`PX4FMUv2.4.5/`) — 12 pages, 492 symbol
placements. Verified complete: the per-page symbol counts match an independent
parse of the Eagle source exactly, page for page
(23/36/24/32/49/69/45/49/58/24/49/34), and the exported netlist reproduces
`CAN_H`, `CAN_L`, `CAN1_TX` and `SAFETY` with the same nodes the Eagle netlist
has. No "Bus Entry needed" errors appeared.

**The import's root had to be repaired.** As it landed on disk, the container
root that referenced the 12 pages had been overwritten with page 1's own
content — its symbols carried instance path `/e0a7e50b…`, the UUID
`.kicad_pro` records as sheet `_1`, which is what a child page saved over its
parent looks like. KiCad consequently saw a **one-page project**: ERC
enumerated only `Sheet /`, and a netlist export returned 8 components instead
of ~292. The other 11 files were on disk, complete, and unreachable.

`tools/repair_import_hierarchy.py` rebuilds the container (moves page 1 to
`PX4FMUv2.4.5_1.kicad_sch`, writes a root holding the 12 sheet elements with
the UUIDs from `.kicad_pro` so existing instance paths still resolve) and then
verifies the result against the Eagle source. All 13 sheets now enumerate. Run
it again after any re-import; it is idempotent.

Note for anyone hand-editing these files: **KiCad 10 writes child instance
paths as `/<sheet-element-uuid>`** — one level, without the root document's
UUID. KiCad 7 included the root UUID. The two forms are not interchangeable.

**Still open: the import uses global labels for everything.** 136 distinct
global labels, no internal hierarchy. 123 of them span multiple pages. A
global label is global across the *whole project*, so instantiating this
design three times would short all 120 non-shared nets together across
FMU-A/B/C — every SPI bus, every MCU pin, every internal rail. Only `CAN_H`,
`CAN_L`, `GND` and `SAFETY` are genuinely shared and may stay global.

So the 3× instantiation needs those 120 nets converted to hierarchical labels
plus sheet pins first. That conversion will be generated into a separate
directory rather than applied in place, so `PX4FMUv2.4.5/` stays a pristine,
re-importable capture of the board.

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

## The carrier PCB (`carrier/`)

`hardware/carrier/` is a **separate KiCad project**, and that is deliberate:
the three FMU modules are separately manufactured hardware, not parts on this
board. Sharing a project would make a board netlist try to place 421 module
components on the carrier.

What it carries — 9 connectors, 12 nets, no dangling ends:

| Ref | Part | Role |
|---|---|---|
| J1–J3 | DF13-4P | CAN1 to each module's J405, daisy-chained |
| J4–J6 | DF13-6P | brick power in, one per module |
| J7–J9 | DF13-6P | power out to each module's J601 |

**Why every signal has an IN and an OUT connector.** The first version gave
each board a single power connector. That reads fine as a system sheet — the
net continues into the FMU sheet — but once the carrier stood alone, 28 nets
terminated on a single pin. A pass-through carrier *is* a path, so power
enters on one connector and leaves for the module on another.
`kicad-cli sch export netlist` now reports zero single-pin nets.

**Deliberately not on this board:**

- *Servo/PWM breakout.* How three boards' motor commands arbitrate into one
  output is unresolved — `TmrVoter` is still not wired into `motor_task`.
  Each module's J901 cables straight to its ESCs until that is decided;
  committing a guess to copper is worse than leaving it out.
- *The safety switch.* J702's `SAFETY` lands on `U801.PB5`, the IO
  co-processor this firmware never runs, and neither J405 nor J601 carries a
  pin to route it through. It would be decorative.

### Board

`tools/gen_carrier_pcb.py` writes `carrier.kicad_pcb`: an 80 × 60 mm
two-layer outline and the four M3 mounting holes on a **30.000 × 30.000 mm**
pattern. That pattern is not a guess — it comes from the module's own
`PX4FMUv2.4.5.brd`, CLI-imported (`kicad-cli pcb import`, which *does* exist
for boards even though the schematic equivalent does not) and read off
`M3_MOUNT1101..1104`. A stacked module will line up.

Verified: **DRC reports 0 violations, 0 unconnected items**, and the full
fabrication set exports — gerbers, drill, job file. The drill file contains
exactly four 3.2 mm NPTH holes at the 30 × 30 pattern.

```bash
kicad-cli pcb drc carrier.kicad_pcb
kicad-cli pcb export gerbers --output fab/ carrier.kicad_pcb
kicad-cli pcb export drill   --output fab/ carrier.kicad_pcb
```

### To finish the board

Two steps remain, and the first is GUI-only:

1. Open `carrier/carrier.kicad_pro` and press **F8** (*Tools → Update PCB
   from Schematic*) to place the nine connectors. `kicad-cli pcb` has
   `drc`, `export`, `import`, `render` and `upgrade` — nothing that loads a
   netlist into a board, so this cannot be scripted.
2. Route it. Placement and routing are left interactive on purpose:
   generated copper on flight hardware needs reviewing trace by trace, which
   is more work than routing it properly once. The layout is small — the CAN
   pair daisy-chains down a column of three connectors, and each board's
   power is a short parallel run from its in-connector to its out-connector.

Constraints to route to:

- **CAN_H/CAN_L are a differential pair.** Keep them adjacent and equal
  length; keep stubs off the bus short (it is a daisy chain, not a star).
- **No termination on this board** — see the CAN note above; it is also on
  the silkscreen.
- **Keep the three power paths physically separate.** They are electrically
  independent by design; running them as one bundle re-introduces a common
  failure the netlist cannot see.
- `VBRICK_*` carries the module supply — widen it relative to the sense
  signals.

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
