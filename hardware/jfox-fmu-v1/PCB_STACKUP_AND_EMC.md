# PCB stackup, EMC strategy and layout constraints

The protection components on the schematic are the smaller half of EMC. The
larger half is the stackup and the return paths, and neither is a component
you can add later — they are decided the moment the board is fabricated.

## Stackup: 6 layers, and why not 4

| Layer | Use | Thickness |
|---|---|---|
| L1 | Signal — components, short escapes, no long runs | 35 µm |
| **L2** | **Solid ground.** No splits, no routing. | 18 µm |
| L3 | Signal — the bulk of routing, referenced to L2 | 18 µm |
| L4 | Power — +3V3, +5V, +3V3A, the switched sensor rails | 18 µm |
| **L5** | **Solid ground.** No splits, no routing. | 18 µm |
| L6 | Signal — components, short escapes | 35 µm |

Total ~1.6 mm, FR-4, controlled impedance.

**Why not 4 layers.** A 4-layer SIG/GND/PWR/SIG stackup gives the outer layers
a reference plane but leaves L3 as a *split* power plane — and a signal
crossing a split has no return path beneath it, so its return current detours
around the gap and the loop it encloses becomes the radiating element. This
board has four switched sensor rails plus three analog/isolated domains, so
the power layer *will* be heavily split. Six layers puts a solid ground either
side of the power layer, so every signal on L1, L3 and L6 has an unbroken
return regardless of what L4 is doing.

That is the single most consequential EMC decision on the board, and it costs
about 30% more per panel than four layers.

**The two ground layers must be solid.** Not "mostly solid". A routed track on
a ground layer is a slot, and a slot under a fast signal is a far better
antenna than any track. If a jumper is unavoidable it goes on a signal layer.

## Ground: one plane, not split

**There is no separate analog ground.** The instinct to split ground for the
IMUs and the ADC reference is wrong here and is the classic way to *create*
an EMC problem: a split forces return currents to detour to the bridge, and
the resulting loop radiates far more than the coupling the split was meant to
prevent.

Instead: one continuous ground, and control the *placement* so noisy return
currents never flow through quiet regions. Quiet parts go in a quiet corner,
noisy parts go in a noisy corner, and the plane stays whole.

The exception is genuine galvanic isolation. `GND_ISO1` and `GND_ISO2` are
separate copper regions by definition — that is the point of the ISOW1044 —
with **no** stitching capacitor to board ground unless a conducted-emissions
test later demands one. Isolation gaps must respect the ISOW1044's creepage
and clearance, and nothing may route across them on any layer.

## Placement zones

Placement determines emissions more than routing does.

```
   ┌──────────────────────────────────────────────┐
   │  NOISY                          ISOLATED     │
   │  U21 buck, input ORing FETs     U30/U31      │
   │  power connectors               CAN, barrier │
   ├──────────────────────────────────────────────┤
   │  DIGITAL                                     │
   │  U10 STM32, microSD, USB, FRAM               │
   ├──────────────────────────────────────────────┤
   │  QUIET                                       │
   │  3 IMUs, 2 baros, BMM150, crystals, VCAP     │
   └──────────────────────────────────────────────┘
```

Rules that follow from it:

- **The magnetometer is the most placement-sensitive part on the board.**
  DO-160G §15. Keep U6 as far as possible from U21's switch node, from the
  ISOW1044 converters, and from every high-current path — including the PWM
  return, which carries the motor currents. A magnetometer 10 mm from a
  switching inductor reads the inductor.
- **The buck's hot loop** — U21's input capacitor, the SW node and L1 — must
  be as small as physically possible. That loop switches at 2.5 MHz and is the
  board's primary emitter. C35's 10 nF sits within 1 mm of the pin.
- **The crystals** get a local ground pour, guard traces, and nothing routed
  underneath. They are the second most sensitive nodes after the magnetometer.
- **VCAP1/VCAP2** each get their 2.2 µF within a few millimetres of their pin.
  They are a regulator loop, not decoupling, and length is loop area.

## Controlled impedance

| Net class | Target | Notes |
|---|---|---|
| USB D+/D− | 90 Ω differential | Route as a pair, length-matched within 0.15 mm, referenced to L2 the whole way, no layer changes between U40 and U10. |
| CAN H/L (both) | 120 Ω differential | Matches the 120 Ω terminators. On the isolated side, referenced to the isolated ground pour. |
| SDMMC1 CK/CMD/D0-3 | 50 Ω single-ended | Length-match the group within 5 mm; CK is the reference. |
| Everything else | 50 Ω single-ended | Default. |

Impedance is a fabricator constraint, not a wish — it goes on the fab drawing
with the stackup, and the fabricator adjusts trace width to hit it.

## Protection placement — the requirement, not the part

Every device on the protection sheet is only as good as its position:

- **D4/D5/D6** (input TVS) mount **at** their connector, with the shortest
  possible path to the ground plane. A TVS 30 mm downstream protects the last
  30 mm of track and nothing else.
- **U40** (USB ESD) sits between J30 and L5, closest to the connector, so it
  protects the choke as well as the MCU.
- **L5** (USB common-mode choke) follows U40, before the pair leaves for the
  MCU.
- **L3/L4** (CAN chokes) and **D7/D8** sit on the isolated side, at their
  connectors, referenced to `GND_ISO`.
- **FB1-3** sit at the connector end of the 5 V feed, not at the regulator.

## What still has to happen

1. **Layout.** None of the above is drawn yet. See below.
2. **A fabrication drawing** carrying the stackup, the impedance table, and
   the conformal-coating keep-outs for U4 and U7 (both open-cavity pressure
   sensors — coating them destroys the measurement).
3. **Pre-compliance measurement** before a formal DO-160G §21 attempt. A
   near-field probe and a spectrum analyser will find the problems this
   document is trying to prevent, far more cheaply than a chamber will.

## Scope limit, stated plainly

**Routing this board is not something this workflow produces.** An LQFP176
escape, a 2.5 MHz switching regulator, 90 Ω and 120 Ω controlled-impedance
differential pairs, an isolation barrier with creepage requirements, and a
magnetometer that has to stay clean — that is interactive layout work in the
PCB editor by someone who can see the field, and generated text will not do
it credibly.

What is produced here: board outline, stackup, mounting, the netlist, design
rules and component placement zones. Everything above is the input to that
work, not a substitute for it.
