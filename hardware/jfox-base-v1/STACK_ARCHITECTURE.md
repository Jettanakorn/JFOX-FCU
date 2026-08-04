# JFOX-BASE-v1 — three-channel base board and module stack

JFOX Aircraft Co., Ltd.

The base board that carries three JFOX-FMU-v1 modules as a triple-redundant
flight control set, and the mechanical stack they assemble into.


> **SECTIONS 1 AND 2 ARE SUPERSEDED — read section 8 first.**
>
> They describe a horizontal base board with three riser cards, built around
> the DF12 mezzanine's fixed 3.0 mm stack height. That design no longer
> exists: the module is now a plug-in card with gold fingers on its rear
> edge, and the base board is a vertical backplane with three card-edge
> sockets. The riser cards, the 18 mm standoff pitch and the extra mated
> pair per channel are all gone with it.
>
> They are kept rather than deleted because section 1 records *why* the
> mezzanine could not do this job, and that reasoning is what led to the
> backplane. A document that quietly drops its own dead ends teaches nothing
> the second time the question comes up.

---

## 1. The constraint that shapes everything

The module's carrier connector J40 is a **Hirose DF12C3.0-60DS-0.5V**. Its
mated stack height is **3.0 mm, fixed** — the DF12 family offers 3.0, 3.5,
4.0 and 5.0 mm and nothing taller.

A board-to-board mezzanine therefore joins **two adjacent boards only**. Three
modules stacked vertically sit at roughly 0, 18 and 36 mm above the base
board, and no member of the DF12 family spans that.

So "three modules stacked, each with an independent path to one base board"
cannot be built from direct mezzanine mating. Exactly one of the two has to
give:

| | Independent paths | Direct mezzanine | Verdict |
|---|---|---|---|
| Shared pass-through bus | ✗ | ✓ | one damaged contact fails all three channels |
| Riser card per channel | ✓ | ✗ (one extra mated pair) | **chosen** |
| Move J40 to a module edge, use a true backplane | ✓ | ✗ | needs an FMU redesign |

The riser option is taken. It preserves channel independence, which is the
entire reason for triplicating the module, and it leaves JFOX-FMU-v1
unchanged — the board is already DRC-clean with J40 anchored at its centre
under the MCU.

**The cost, stated plainly:** each channel gains one extra mated connector
pair. That is a new failure point per channel, and DO-160G section 8
(vibration) applies to it. It is a *per-channel* failure point, not a common
one — a riser failure takes out one channel, which the TMR voter is built to
survive. A shared-bus failure takes out all three, which nothing survives.

### The alternative worth revisiting

Moving J40 from the module centre to its east edge would let a conventional
backplane replace all three risers: modules plug in horizontally, parallel,
like a VME rack. Fewer parts, no risers, better under vibration. The cost is
longer traces from the MCU to the carrier signals and a re-layout of a board
that currently scores 203.7 with zero DRC violations. Worth doing for a
production revision; not worth doing to reach a first article.

---

## 2. Stack geometry

```
                                        Z (mm above base board top face)
    ┌──────────────────────────────────────┐
    │           FMU-C  (channel C)         │  54.0  ─ module top face
    └───┬──────────────────────────────┬───┘  52.4  ─ module bottom face
        │                          ┌───┴───┐
        │  M3 standoff, 48.2 mm    │ RISER │
        │                          │   C   │
    ┌───┴──────────────────────────┴───────┐
    │           FMU-B  (channel B)         │  36.0
    └───┬──────────────────────────────┬───┘  34.4
        │                          ┌───┴───┐
        │  M3 standoff, 30.2 mm    │ RISER │
        │                          │   B   │
    ┌───┴──────────────────────────┴───────┐
    │           FMU-A  (channel A)         │  18.0
    └───┬──────────────────────────────┬───┘  16.4
        │                          ┌───┴───┐
        │  M3 standoff, 12.2 mm    │ RISER │
        │                          │   A   │
════════╧══════════════════════════╧═══════╧════  0.0
                JFOX-BASE-v1
              J1      J2      J3
        (three independent DF12 headers)
```

**Inter-board pitch: 18.0 mm.** Derived, not chosen:

| Contribution | mm | Source |
|---|---|---|
| Module PCB thickness | 1.60 | board `(general (thickness 1.6))` |
| Tallest part, module top face | 4.25 | J6 — JST-GH SM10B-GHS-TB |
| Tallest part, module bottom face | 2.00 | J40 DF12 socket body |
| Cooling and harness clearance above the top face | 10.15 | see below |
| **Total** | **18.00** | |

The 10.15 mm of air is not padding. Each module dissipates roughly 2 W, and
in a sealed stack the middle module has boards above and below it — the only
path out is lateral airflow across that gap. DO-160G section 4 category A2
allows +55 °C ambient, so the gap has to work at 55 °C, not at 25 °C. It
also has to admit the JST-GH harnesses, which leave J6/J12/J13 horizontally
along the module's south edge.

**Base board outline: 100 × 80 mm — the same as the module.** The stack has
no overhang, the four M3 columns land on the module's own 84 × 64 mm hole
pattern, and the airframe sees one rectangular envelope rather than a
stepped one.

Overall envelope: **100 × 80 × 56 mm** including the tallest module.

---

## 2a. Compact and noise-robust, on one board

These two pull against each other. Lateral separation is the cheapest way to
control coupling, and a compact board has none to spend. So the separation
is bought in the **stackup** instead of in area.

### Why this matters more here than on the module

On an ordinary board, crosstalk is a signal-integrity problem. On this one
it is a **redundancy** problem. If channel A's switching noise corrupts
channel B's data, the two channels are no longer independent — and two
channels failing together is exactly the case triple redundancy exists to
prevent. Coupling between channels is a **common-cause failure**, so the
isolation between them is a safety requirement, not a performance one.

That reframes the layout rule. It is not "keep the noisy things away from
the quiet things". It is "keep each channel away from every other channel",
which on a compact board means vertical separation and via fencing rather
than distance.

### Eight layers, not six

The module is six. This board is **eight**, and the extra two are spent
entirely on reference planes:

| # | Layer | Role | Reference for |
|---|---|---|---|
| 1 | F.Cu | connectors, fibre front end | L2 |
| 2 | GND1 | solid ground | — |
| 3 | In2 | channel A signals | L2 |
| 4 | GND2 | solid ground | — |
| 5 | PWR | power, split per channel | — |
| 6 | In5 | channel B signals | L7 |
| 7 | GND3 | solid ground | — |
| 8 | B.Cu | channel C signals, passives | L7 |

Every signal layer is adjacent to a solid ground plane, so every return
current has an unbroken path directly beneath its own trace. That is what
makes a compact board quiet: the loop area is set by the dielectric
thickness, ~0.1 mm, rather than by how far the return has to detour.

**The three ground planes must stay solid.** A track routed across a ground
plane is a slot; a slot under a fast edge is a better antenna than any trace
on the board, and it also forces the return current of every signal crossing
it to detour around — which couples those signals to each other. On this
board that coupling would be *between channels*, so a single careless track
on L2 could create the common-cause path the whole architecture is built to
avoid.

### Each channel on its own layer

Channel A on L3, B on L6, C on L8. Two channels are never broadside-coupled
on adjacent layers, and where they must cross, they cross with a ground
plane between them.

### Via fencing between channel regions

Ground stitching vias on a 5 mm pitch — a quarter wavelength at 1.5 GHz in
FR-4 — along the boundary between each channel's routing region, and around
the fibre-optic front end. The fence ties all three ground planes together
locally, so the return current has somewhere to go at the boundary instead
of coupling across it.

### What compactness costs, stated

Two extra layers is roughly 30–40 % on bare-board price. That is the price
of the 100 × 80 outline. A 140 × 110 board could have done this in six
layers with lateral separation instead. The compact envelope was the
requirement, so the layers are where the money goes.

---

## 3. Channel independence

Independence is the whole point, so it is stated as a property to verify,
not an intention:

| Shared between channels | Independent per channel |
|---|---|
| Airframe power input (single source by definition) | Power path after the input fuse: own ORing FET, own sense, own fuse |
| CAN FD vehicle bus (single bus by definition) | Own isolated transceiver on the module (ISOW1044), own stub |
| Base board PCB itself | Own DF12 header, own riser, own standoffs |
| — | Own actuator output header |
| — | Own fibre-optic channel pair |

What remains common-mode: the base board's own copper, the airframe supply
upstream of the three fuses, and the CAN bus wire. Those are irreducible
without triplicating the airframe. Everything the base board *adds* is
per-channel.

The three modules are **identical**. No board is the "primary" in hardware;
which channel commands is decided by the TMR voter in firmware. A hardware
distinction between channels would mean three part numbers, three spares
holdings, and a bench technician who can fit the wrong one.

---

## 4. Riser card, JFOX-RISER-v1

One design, three lengths. A vertical 2-layer card:

```
   ┌─────────────────┐  DF12C3.0-60DP-0.5V  (header, mates module J40)
   │  ▄▄▄▄▄▄▄▄▄▄▄▄▄  │
   │                 │
   │   60 tracks,    │   length L: A 12.2, B 30.2, C 48.2 mm
   │   GND on L2     │
   │                 │
   │  ▀▀▀▀▀▀▀▀▀▀▀▀▀  │  DF12C3.0-60DS-0.5V  (socket, mates base J1/J2/J3)
   └─────────────────┘
```

Ground on layer 2 the full length: 60 signals running 48 mm with no return
plane is a common-mode radiator, and section 21 (RF emission) is a test this
has to pass rather than an opinion.

Retention: each riser is clamped by the standoff column beside it. A
connector is not a mechanical mount — under section 8 vibration a card held
only by its two connectors works them loose.

---

## 5. Base board content

Per the design decision recorded for this revision:

| Block | Per channel | Notes |
|---|---|---|
| Mezzanine header | 3 × DF12C3.0-60DP-0.5V | J1/J2/J3, pinout mirrored from the module's `MEZZ_PINS` |
| Power distribution | 3 × ORing FET + fuse + sense | one channel's short cannot brown out the others |
| CAN FD bus | shared bus, per-channel stub | 60 Ω end termination on the base board; module JP1/JP2 cut on all three — see below |
| Actuator outputs | 3 × 8-channel header | **headers only, no arbitration** |
| External I/O breakout | GPS, RC, telemetry, USB | airframe-side connectors |
| Fibre-optic link | 2 channels, redundant | to the I/O / actuator side |

### CAN termination — changed from the module-level scheme

Each module carries JP1/JP2 bridged, i.e. 120 Ω fitted by default. Three
modules on one bus is three terminators in parallel, about 40 Ω. With the
bus now wired on the base board, the correct arrangement is:

> **Cut JP1 and JP2 on all three modules. The base board carries the two
> 120 Ω end terminators, one at each physical end of the bus run.**

This is a change from `HARDWARE_BRINGUP.md` Stage 3, which was written for
the PX4FMUv2.4.5 carrier where R409 was not removable. It is better: the
terminators are now at the true electrical ends of the bus rather than on
whichever modules happen to be outermost, and no module needs modifying
based on its stack position.

### Actuator aggregation is headers only

How three modules' PWM outputs combine into one actuator command is **not
solved here and not solved in firmware** — `TmrVoter` is still not wired
into `motor_task`. The base board brings all three sets out to headers and
leaves the arbitration mechanism to a separately scoped decision. Baking a
guess into copper would be worse than leaving it open.

---

## 6. Fibre-optic I/O — two redundant channels

Added to the objective at the customer's direction. This closes the gap
`check_fmu_objective.py` reports as *"no fibre-optic transmitters or
receivers — actuator links are specified as fibre"* — but it closes it on
the **base board**, not on the module. The checker tests the module and will
keep failing until it is taught where the fibre now lives.

Two independent channels, each a transmitter/receiver pair, so a single
fibre break or a single emitter failure loses one channel and not the link.

**Part selection is NOT yet verified against a datasheet.** No optical
datasheet is present in `datasheets/`. The intended family is Broadcom
Versatile Link 650 nm plastic optical fibre — the industrial standard for
short rugged links — but the specific part numbers, their DO-160G
temperature range, and their launch power budget over the intended fibre
length must be confirmed before this is committed to copper. Recorded as an
open item rather than drawn as though settled.

---

## 7. Open items

| # | Item | Blocking? |
|---|---|---|
| 1 | Fibre-optic part numbers unverified — no datasheet in repo | yes, before fabrication |
| 2 | Riser card JFOX-RISER-v1 not yet designed | yes, before assembly |
| 3 | Actuator arbitration mechanism undecided | no — headers are correct either way |
| 4 | 18 mm pitch not yet checked against a thermal model at +55 °C | no — margin is generous |
| 5 | Vibration qualification of the extra mated pair per channel | yes, before flight |

---

## 8. Assembly and maintenance review

A pass over the design asking only "can this be built, and can it be
serviced". DRC and ERC answer neither question — every item below was
present on a board that passed both.

### 8.1 Fixed

**The card could not be inserted.** The gold fingers sat 7.25 mm inboard of
the board edge, so the laminate would hit the connector before the contacts
did. Cause: every part is placed by aligning its *courtyard* 1.5 mm inside
the outline, which is right for a part that sits on the board and wrong for
one that *is* the board's edge. A card-edge footprint carries its own datum —
the Edge.Cuts tongue profile — and that is what has to land on the outline.
A `FLUSH_x` placement kind now uses it; the fingers stop 0.50 mm short of
the edge, which is the setback the footprint designs in.

Worth noting how this presented: the board was DRC clean throughout. Nothing
about it violated a rule. It simply was not a card.

**The USB-C and the card slot were 2 mm inboard.** A USB-C plug's overmould
is wider than the receptacle, so it fouls the board edge before the contacts
seat; the card slot loses the support that stops a half-inserted card
levering on its own contacts. Both are now flush.

### 8.2 Open — mechanical, cannot be expressed in the PCB files

| # | Item | Why it matters |
|---|---|---|
| 1 | **No card ejector or handle** | 60 contacts at 1.27 mm need real extraction force. Without a lever the only grip is the PCB itself, and pulling on a populated card bends it. |
| 2 | **No card guides, no keying** | Three identical cards, fingers on both faces. Inserted upside down, power lands on signal pins. The connector chosen is non-polarised so the contact count matched 60 exactly — so keying *must* come from the guide rails. |
| 3 | **Gold finger fabrication** | Selective hard gold (30 µin min) and a 20–30° lead-in bevel. Drawing notes; no rule can carry them. |
| 4 | **Front-panel openings** | Ideally the USB-C and card slot overhang the outline by ~0.5 mm, which needs a notch in the board edge that this generator does not draw. |

### 8.3 Open — serviceability, on the backplane

| # | Item | Detail |
|---|---|---|
| 5 | **Status LEDs are buried** | D1–D3 sit 15 mm inboard on the front face, behind the cards. They are the only channel-state indication with the lid on, and they cannot be seen. They belong on an edge. |
| 6 | **Fuses are not field-replaceable** | F1–F3 are 1206 SMD, 15 mm inboard on the front face. Replacing one means pulling every card and reflowing. Either fit holders or state plainly that a blown fuse is a depot repair. |
| 7 | **CAN harness landings are hard to reach** | J60–J65 sit in a column on the front face between the slots. With three cards at 24 mm pitch, six JST-GH latches must be worked in a 22 mm gap. |
| 8 | **No test points anywhere** | Neither board has one. There is no way to measure a rail, or to tell a dead channel from a dead supply, without a probe on a part pin. |

Items 5–8 are all the same shape: the backplane's front face is covered once
the cards are in, and everything a technician needs was put there. Fixing
them means moving that content to the perimeter or the rear face, which is a
layout change of the same size as the one that produced this list.
