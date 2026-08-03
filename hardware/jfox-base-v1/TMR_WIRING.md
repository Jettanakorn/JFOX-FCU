# JFOX FCU V1 — TMR assembly wiring

JFOX Aircraft Co., Ltd.

How the three flight control cards, the backplane and the airframe connect.
Every reference here is taken from the generated board files, not from
intent — if a connector is listed, it exists on a board that passes its
footprint check.

---

## 1. What the assembly is

```
                            ┌─────────────────────────────────────┐
        AIRFRAME            │      JFOX-BASE-v1  BACKPLANE        │
                            │           100 × 100 mm              │
   PSU 1 (RH) ──────────────▶ J50 ──┐                             │
                            │       ├─ D50/D51 ORing ─┬─ F1 ─▶ J1 ├──▶ FCU-A
   PSU 2 (LH) ──────────────▶ J51 ──┘                 ├─ F2 ─▶ J2 ├──▶ FCU-B
                            │                         └─ F3 ─▶ J3 ├──▶ FCU-C
   GPS1 ────────────────────▶ J90  (→ channel A)                  │
   RC in ───────────────────▶ J91  (→ channel B)                  │
   Telemetry 1 ─────────────▶ J92  (→ channel A)                  │
   Telemetry 2 ─────────────▶ J93  (→ channel C)                  │
   Vehicle CAN ─────────────▶ J70                                 │
                            │                                     │
   Actuators A ◀────────────  J80 ◀── from J1                     │
   Actuators B ◀────────────  J81 ◀── from J2                     │
   Actuators C ◀────────────  J82 ◀── from J3                     │
                            │                                     │
   Fibre I/O #1 ◀──────────▶  U50 TX / U51 RX   (right-hand face) │
   Fibre I/O #2 ◀──────────▶  U52 TX / U53 RX   (left-hand face)  │
                            │                                     │
   Debug ───────────────────▶ J52        Console ──▶ J54 (USB-C)  │
                            │  D1 D2 D3  channel status lamps     │
                            └─────────────────────────────────────┘
```

Three identical cards. **No card is the primary in hardware** — which
channel commands is decided by the TMR voter in firmware. A hardware
distinction would mean three part numbers, three spares holdings, and a
technician who can fit the wrong one.

---

## 2. Card interface — the gold fingers

Each card carries **58 contacts** on a 2 × 30, 1.27 mm card edge (Samtec
MECF-30 polarised). There is no connector part on the card: the contacts are
the PCB. The backplane holds the only mated half.

**Contacts 21 and 22 are the polarising key** — a 1.24 × 7.0 mm notch in the
card's south edge, offset from centre. A card inserted the wrong way round
presents the notch in the wrong place and physically will not enter. This
is the only insertion safeguard that works before power is applied, and it
is why the pinout gave up two grounds rather than two signals.

| Crossing the fingers | Contacts |
|---|---|
| +5V_CARRIER (fused, per channel) | 3 |
| GND | 18 |
| PWM / actuator, TIM1 + TIM4 | 8 |
| Serial: USART2, USART3, UART4, UART7, UART8 | 16 |
| I2C2 | 2 |
| SPI5 | 3 |
| SWD + console (SWDIO, SWCLK, NRST, USART1) | 5 |
| Power-source valid flags | 3 |
| Key (no contact) | 2 |

---

## 3. Harnesses

### 3.1 Power — two independent feeds

| From | To | Notes |
|---|---|---|
| PSU 1 (right-hand) | **J50** | 4-way; two pins VBAT_RH, two GND |
| PSU 2 (left-hand) | **J51** | 4-way; two pins VBAT_LH, two GND |

The two feeds go to **opposite bottom corners** of the backplane. That
separation is the point — two supplies entering side by side share whatever
damages one of them. They are ORed by D50/D51 into one bus, then split
three ways through F1/F2/F3 (3 A each) so a shorted card is isolated by its
own fuse rather than pulling the other two down.

> **F1–F3 are 1206 SMD, not holders.** A blown fuse is a depot repair, not
> a line replacement. Recorded rather than hidden — see open item 4.

### 3.2 Isolated CAN — six harnesses, two per card

| Card | Card connector | Backplane landing |
|---|---|---|
| FCU-A | J12 (CAN1), J13 (CAN2) | **J60**, **J61** |
| FCU-B | J12, J13 | **J62**, **J63** |
| FCU-C | J12, J13 | **J64**, **J65** |

These do **not** cross the gold fingers, deliberately. The card's ISOW1044
puts the bus on the far side of an isolation barrier referenced to
GND_ISO1/GND_ISO2, not board ground. A 1.27 mm card edge gives about 1.27 mm
of creepage — running isolated signals beside board-referenced ones would
reduce the barrier to that gap and undo the isolator.

The vehicle bus lands on **J70**.

### 3.3 CAN termination — changed, and this matters

Each card ships with **JP1 and JP2 bridged**, i.e. 120 Ω fitted. Three cards
on one bus is three terminators in parallel — about 40 Ω, a real
signal-integrity fault.

> **Cut JP1 and JP2 on all three cards.** The backplane carries the two
> 120 Ω end terminators (R40, R41), one at each physical end of the bus run.

This supersedes `HARDWARE_BRINGUP.md` Stage 3, which was written for the
PX4FMUv2.4.5 carrier where R409 could not be removed. It is better: the
terminators sit at the true electrical ends rather than on whichever cards
happen to be outermost, and no card needs modifying based on its slot.

### 3.4 Vehicle I/O — distributed across channels

| Peripheral | Backplane | Lands on |
|---|---|---|
| GPS 1 | J90 (10-way) | channel **A** |
| RC input | J91 (5-way) | channel **B** |
| Telemetry 1 | J92 (6-way) | channel **A** |
| Telemetry 2 | J93 (6-way) | channel **C** |

Spread deliberately. One peripheral shorting its host card's UART costs that
channel, and the voter carries on with the other two. All four on one card
would make that card a single point of failure for every external input.

### 3.5 Actuator outputs

| Backplane | Source | Channels |
|---|---|---|
| J80 (10-way) | J1 / FCU-A | 8 PWM + 2 GND |
| J81 | J2 / FCU-B | 8 PWM + 2 GND |
| J82 | J3 / FCU-C | 8 PWM + 2 GND |

**Headers only — no arbitration.** How three sets of PWM combine into one
actuator command is not solved here and not solved in firmware; `TmrVoter`
is still not wired into `motor_task`. Baking a guess into copper would be
worse than leaving it open.

### 3.6 Fibre-optic I/O — two channels

| Channel | Transmit | Receive | Face |
|---|---|---|---|
| #1 | U50 | U51 | right-hand |
| #2 | U52 | U53 | left-hand |

Opposite faces, not adjacent. They exist to survive each other's loss, and
two connectors 20 mm apart share every localised hazard there is — one
impact, one chafed loom, one hot bracket.

> **Part numbers are NOT yet verified.** No optical datasheet is in
> `datasheets/`. The intended family is Broadcom Versatile Link 650 nm
> plastic optical fibre, but the specific parts, their DO-160G temperature
> range and the launch-power budget over the intended fibre length must be
> confirmed before this is committed to copper.

### 3.7 Front panel

| | |
|---|---|
| J52 | SWD debug — one for the set, reaches each card over its fingers |
| J54 | USB-C console |
| D1 / D2 / D3 | Channel status lamps, one per card, each driven from **its own** card |

A single lamp driven from summary logic tells you the summary logic is
alive, which is not the question anyone asks when looking at it.

Each **card** also carries two lamps on its front edge, either side of its
USB-C: **D1 power** (hardwired to the rail, lights with no firmware running)
and **D2 heartbeat** (MCU-driven; dark means the firmware stopped).

---

## 4. Assembly sequence

1. **Before fitting any card:** cut JP1 and JP2 on all three. Verify with a
   meter — bus resistance across the backplane should read ~60 Ω, not ~40.
2. Fit the backplane into the chassis. Land the two power feeds on J50/J51
   at opposite corners; confirm they route separately.
3. Land the six CAN harnesses J60–J65 **before** the cards go in — with
   three cards fitted at 24 mm pitch, six JST-GH latches must be worked in a
   22 mm gap. See open item 3.
4. Slide the cards in. The key notch will refuse a card the wrong way round;
   **do not force one**. If a card resists, it is reversed or the wrong
   part.
5. Land vehicle I/O, actuators and fibre.
6. Power on. Each card's D1 should light immediately — it is hardwired, so
   it does not wait for firmware. D2 should begin blinking within a second.
   A card with D1 lit and D2 dark has power and no firmware.

---

## 5. What is shared, and what is not

| Common to all three | Independent per channel |
|---|---|
| Airframe supply upstream of F1–F3 | Fuse, feed, and ORing downstream of it |
| CAN bus wire | Isolated transceiver, barrier, and stub |
| Backplane copper | Card-edge socket, card, status lamp |
| — | Actuator header |
| — | Local 3V3 regulation and sensor rails |

What remains common-mode is irreducible without triplicating the airframe.
Everything the backplane *adds* is per-channel.

---

## 6. Open items

| # | Item | Blocking |
|---|---|---|
| 1 | Fibre part numbers unverified — no datasheet in repo | before fabrication |
| 2 | Card guides and retention undesigned; the key polarises but does not retain | before flight |
| 3 | J60–J65 hard to reach with cards fitted — land them first, or move them | no |
| 4 | F1–F3 not field-replaceable | no — but say so in the manual |
| 5 | Actuator arbitration undecided | no — headers are correct either way |
| 6 | FCU DRC: 16 blocking violations outstanding | before fabrication |
