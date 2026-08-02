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
| `fmu-v2/` | **Generated.** The real board, safe to instantiate 3x. |
| `carrier.kicad_sch` | **Generated.** The new carrier/backplane design. |
| `jfox.kicad_sym` / `sym-lib-table` | **Generated.** Connector symbols, registered as a project library. |
| `tools/check_tmr_netlist.py` | Asserts the redundancy invariants against KiCad's netlist. |
| `tools/gen_fmu_hierarchical.py` | Converts the import for safe 3× instantiation → `fmu-v2/`. |
| `tools/annotate_tmr_instances.py` | Gives each FMU instance its own reference designators. |
| `tools/check_fmu_conversion.py` | Proves the conversion changed no connectivity. |
| `tools/route_carrier.py` | Places the connectors and routes the carrier board. |

Full pipeline — regenerate and verify everything:

```bash
python hardware/tools/extract_eagle_nets.py
python hardware/tools/repair_import_hierarchy.py
python hardware/tools/gen_fmu_hierarchical.py
python hardware/tools/gen_tmr_schematic.py
python hardware/tools/annotate_tmr_instances.py
python hardware/tools/gen_carrier_pcb.py
#   ... then F8 in KiCad to load the netlist onto the board ...
python hardware/tools/route_carrier.py
python hardware/tools/check_fmu_conversion.py
python hardware/tools/check_tmr_netlist.py
```

Order matters: `annotate_tmr_instances.py` reads sheet UUIDs that
`gen_tmr_schematic.py` allocates, so it has to run after it.

(On this machine `python` on `PATH` is the Microsoft Store stub — use
`C:\Users\Jetta\AppData\Local\Programs\Python\Python312\python.exe`.)

## How to verify all of it

```bash
python hardware/tools/verify_all.py
```

Eight checks, each asking KiCad itself rather than the generators — the point
is to catch a generator that produced something plausible but wrong. Expect:

```
Imported FMU board
  [PASS] conversion preserved every connection  -- 262 nets in the import, 262 in the converted copy

3-board TMR system
  [PASS] every component has a unique designator  -- 885 instances, 885 distinct
  [PASS] the three supplies share no node
  [PASS] CAN_H reaches all three modules  -- via each module's own MAX3051
  [PASS] all three module terminators are on the bus  -- ['R409A', 'R409B', 'R409C']

Carrier board
  [PASS] DRC clean  -- 0 violations
  [PASS] fully routed  -- 0 unconnected
  [PASS] no net dead-ends on the board  -- 15 nets, all with a path across

all 8 checks passed
```

It exits non-zero on failure, and it is negative-tested: deleting a single
routed trace turns "fully routed" into `[FAIL] 1 unconnected`.

**Close KiCad before trusting a FAIL.** The script reads what is on disk; if
KiCad has unsaved changes the two disagree, and it prints a note when it sees
a lock file.

Everything here is saved in **KiCad 10** format. Each file type carries its own
version number — schematics `20260306`, boards `20260206`, symbol libraries
`20251024` — so those differing numbers are expected, not a mix of versions.
`gen_tmr_schematic.py` runs `kicad-cli sch upgrade` / `sym upgrade` on its
output, so opening the project does not rewrite anything.

### Looking at it by hand

| To see | Open |
|---|---|
| The board | `hardware/carrier/carrier.kicad_pro` → PCB editor |
| The carrier schematic | same project → schematic editor |
| The whole 3-board system | `hardware/jfox-tmr.kicad_pro` → schematic only |
| One module's real internals | `hardware/fmu-v2/fmu-v2.kicad_sch` (12 pages) |

In the TMR schematic, open the hierarchy navigator to move between `FMU-A`,
`FMU-B`, `FMU-C` and `CARRIER`. The three FMU sheets are the *same file* — a
change to one is a change to all three, which is the point.

## Two projects, and why

| Project | What it is | Has a PCB? |
|---|---|---|
| `jfox-tmr.kicad_pro` | The **system** schematic — three FMU modules + the carrier, showing how the array is wired | **No, deliberately** |
| `carrier/carrier.kicad_pro` | The **board** — the only new hardware here | Yes |

Opening `jfox-tmr` and clicking **Switch to PCB Editor** pops up *"file does
not exist"* and offers to create one. **Say no.** That project has no board on
purpose: the three FMU modules are separately manufactured hardware, not parts
to be placed. A board made from that schematic would try to lay out ~885
components — three copies of a board that already exists. The same warning is
printed on the schematic's own root sheet.

The PCB is the carrier alone. Open `hardware/carrier/carrier.kicad_pro`.

## The TMR project

`jfox-tmr.kicad_sch` is the root. It instantiates **one** sheet file
(`fmu-v2/fmu-v2.kicad_sch`) three times as FMU-A/B/C — that is KiCad's own idiom for
identical repeated blocks, and it means editing the board design once edits
all three while KiCad still keeps their reference designators distinct via
per-instance paths.

Signal split, which is the load-bearing design decision:

- `CAN_H`, `CAN_L`, `GND`, `SAFETY` are **global labels** — correct precisely
  because all three boards genuinely share those nets.
- Power signals are **hierarchical pins**, so each board's stay
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
- no net terminates on a single pin,
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

Note for anyone hand-editing these files: **instance-path forms differ between
KiCad versions and between these files.** KiCad 10 roots symbol paths at the
root document's UUID; KiCad 7 did not; the imported pages use a third form.
`annotate_tmr_instances.py` derives the prefix from the files rather than
assuming - assuming any one of them silently gave all three boards the same
reference designators.

### The global-label problem, and how it was fixed

The import represents every cross-page net as a **global** label — 136
distinct, 123 spanning multiple pages, no internal hierarchy at all. A global
label is global across the *whole project*, so instantiating this design three
times would have shorted all 120 non-shared nets together across FMU-A/B/C:
every SPI bus, every MCU pin, every internal rail. The schematic would have
looked completely normal and been electrically meaningless.

`tools/gen_fmu_hierarchical.py` generates `fmu-v2/` from the pristine import,
which it leaves untouched and re-importable:

- 120 multi-page nets → hierarchical labels plus matching sheet pins on a new
  container root, joined there by local labels. Connectivity is preserved but
  **scoped to one instance** of the board.
- 12 single-page nets → plain local labels; they never left the page.
- `CAN_H`, `CAN_L`, `GND`, `SAFETY` → left global, which is correct. They are
  the four nets the three modules genuinely share, and that is the same split
  the carrier assumes.
- `VDD_5V_BRICK`, `BATT_CURRENT_SENS`, `BATT_VOLTAGE_SENS` → also exposed on
  the root, so each board's power reaches its own carrier connector. (Those
  are the board's own net names; an earlier version of the TMR generator had
  invented `BATT_V_SENS`/`BATT_I_SENS`, which matched nothing.)

That is a lot of automated surgery on a design nobody can eyeball, so it is
checked rather than trusted. `tools/check_fmu_conversion.py` exports a netlist
from the pristine import and from the converted copy and compares them net by
net: **262 multi-pin nets on both sides, joining exactly the same pins.**

`tools/annotate_tmr_instances.py` then gives each instance its own reference
designators — `C101` becomes `C101A`/`C101B`/`C101C` — by writing one
`(path ...)` entry per instance, the same mechanism KiCad's own test project
uses for a thrice-instantiated subsheet. Without it all three boards report
the same designators and KiCad refuses to annotate.

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

ERC on the carrier reports **0 violations**. On the full TMR system it
reports 433, all inherited from the upstream board and its import - see
"System verification" above.

Two real defects were caught this way and fixed:

- **Symbol instance paths were wrong.** They used each child file's own UUID
  instead of `/<root-uuid>/<sheet-element-uuid>`. The files still parsed and
  the generator's structural checks still passed, but KiCad placed every
  carrier symbol on the root sheet. Only ERC surfaced it. The generator now
  checks instance-path rooting directly.
- **Symbols resolved to no registered library** (10 `lib_symbol_issues`
  warnings). Fixed by emitting a real `jfox.kicad_sym` plus a `sym-lib-table`.

## System verification

The whole point of the array is that three boards fail independently but vote
together. That is now demonstrable from KiCad's own netlist of
`jfox-tmr.kicad_sch`, not asserted:

- **885 component instances, 885 distinct references, 0 duplicated** — the
  three boards are genuinely separate instances, not one drawn three times.
- **The three supplies share no node.** `/VBRICK_A` reaches `C1101A`,
  `U1101A`, `J601A` and carrier `J4`/`J7`; `/VBRICK_B` reaches the `B` parts
  and `J5`/`J8`; `/VBRICK_C` the `C` parts and `J6`/`J9`. One brick failing
  cannot take the other two boards down.
- **CAN_H is one bus reaching all three modules' real hardware** — `U401A`,
  `U401B`, `U401C` (the MAX3051 transceivers), `R409A/B/C` (their fixed
  terminators), `J405A/B/C`, and the carrier's `J1`/`J2`/`J3`.

That last line is also the clearest statement of the R409 problem: three
terminators really are on one bus, so one of them really does have to come
off.

ERC on the full system reports **433 violations**, down from 1639 before the
conversion and library fixes. What remains is inherited from the upstream
board and its import, not introduced here: 363 `footprint_link_issues` (the
FMU is a manufactured module, not a part placed on our PCB, so its symbols
carry no footprints), 41 `pin_not_connected` (genuinely unused MCU pins), 22
`power_pin_not_driven` (the import has no PWR_FLAG symbols), and 7 assorted
import artifacts.

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

### Placement and routing

Done, by `tools/route_carrier.py`. **DRC: 0 violations, 0 unconnected.**

Loading the netlist into the board is the one GUI step —
**Tools → Update PCB from Schematic** (F8); `kicad-cli pcb` offers `drc`,
`export`, `import`, `render` and `upgrade` but nothing that updates a board
from a schematic. KiCad then drops the nine connectors in a heap wherever
there is room, which happens to be on top of the mounting holes, so the script
places them and lays the copper.

The layout is arranged so the routing is trivially correct rather than merely
DRC-clean:

- **The three CAN connectors sit in a column at the same x**, so their pin 2s
  line up and `CAN_H` is one straight trace down the board with `CAN_L`
  parallel 1.25 mm away. A real daisy chain, no stubs, pair stays tight.
  **No termination is placed** — each module carries a fixed 120 Ω R409.
- **Power runs left to right**, brick in on one column, out to the module on
  another, at matching pin positions. Routed straight across at pin height the
  three signals per board would collide, so each drops to the back layer at
  its own offset and comes back up: three parallel runs, no crossings, and no
  copper shared between boards.
- **Ground is routed explicitly**, not left to the pours. A zone that fails to
  fill conducts nothing while still looking poured on screen; the board is
  correct by copper and the two planes are a bonus. Ground runs as three
  vertical trunks joined by one horizontal link — a horizontal at pin height
  would cross the power stubs, and one at row+3 would land inside an M3
  keepout.

Two things worth knowing if you edit the zones: KiCad 10 names the net
(`(net "GND")`) where KiCad 7 used an index plus `net_name`, and the fill has
to be enabled explicitly with `(fill yes ...)`. Get either wrong and DRC
reports every ground pad unconnected.

### Fabrication outputs

```bash
cd hardware/carrier
kicad-cli pcb drc            carrier.kicad_pcb
kicad-cli pcb export gerbers --output fab/ carrier.kicad_pcb
kicad-cli pcb export drill   --output fab/ carrier.kicad_pcb
kicad-cli pcb export pos     --output fab/carrier-pos.csv --format csv --units mm carrier.kicad_pcb
kicad-cli sch export bom     --output fab/carrier-bom.csv carrier.kicad_sch
```

That produces a complete 24-file set — gerbers, drill, job file, placement,
and a 9-line BOM of Hirose DF13 parts. Nothing is left to interpret at the
fab house.

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
