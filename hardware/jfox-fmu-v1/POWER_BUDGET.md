# Power budget

Written to settle a question the schematic flagged and would not have settled
itself: whether the 5 V → 3V3 regulator can be an LDO. It cannot.

Figures are from the manufacturers' datasheets, with the table cited. Where a
number is an estimate it says so.

## Two different regulators, do not conflate them

**The MCU's internal regulator** and **the board's 5 V → 3V3 converter** are
separate questions that both came up as "LDO or not".

### Internal: LDO, and not a choice

STM32H753xI datasheet §"Voltage regulator":

> "Scale 0: boosted performance (available only with LDO regulator)"

480 MHz needs VOS0, VOS0 needs the internal **LDO**. So the two VCAP pins and
their 2.2 µF are right, and the SMPS supply option is unavailable to this
design regardless of preference. The earlier note in `ARCHITECTURE.md` — that
KiCad's symbol exposing no SMPS pins *suggested* LDO-only — reached the right
answer for a weaker reason. This is the real one.

### External: must be a buck

See the budget below.

## 3V3 load

| Load | Current | Source |
|---|---:|---|
| STM32H753, 400 MHz VOS1, cache on, all peripherals | **160 mA typ** | ST Table 20 (rev Y) |
| same, max at T_J = 85 °C | **400 mA** | ST Table 20 |
| microSD, write burst | ~100 mA | estimate, part not yet chosen |
| 2 × TCAN332, dominant | ~20 mA | estimate |
| BMI088 + ICM-42688-P + ICM-45686 | ~7 mA | datasheets |
| BMP388 + BMM150 | ~1 mA | datasheets |
| FM25V02A, active | 2.5 mA | Infineon 001-90865 |
| LEDs | ~20 mA | design choice |

**Typical ≈ 310 mA. Peak ≈ 550 mA.**

One honest gap: **ST's rev Y tables stop at 400 MHz (VOS1)**; this datasheet
carries no run-current figure for VOS0 at 480 MHz. The budget uses the 400 MHz
number, so the real figure at 480 MHz is *higher* than stated — which only
strengthens the conclusion below. Replace this row when a VOS0 figure is in
hand.

## Why not an LDO

At 5 V in and 3.3 V out an LDO drops 1.7 V, and dissipates that times the full
load current:

- 310 mA typical → **0.53 W**
- 550 mA peak → **0.94 W**

An SOT-23-5 has θ_JA around 250 °C/W. 0.53 W is a 130 °C rise. The package
does not shed that; the part goes into thermal shutdown, or survives hot and
ages. The originally-drawn AP2112K-3.3 was wrong for this board — not
marginal, wrong by a factor of several.

## Decision

**U21 becomes a TPS62132** — 3 A synchronous buck, 3–17 V in. At ~90 % it
dissipates around 35 mW rather than 530 mW, and the input range leaves room to
feed it from something other than a regulated 5 V later.

**Fixed 3.3 V, not the adjustable TPS62130.** The family splits by ordering
code (SLVSAG7F §5): TPS62130 adjustable, TPS62131 1.8 V, **TPS62132 3.3 V**,
TPS62133 5.0 V. The first version of this design used the adjustable part with
a 180 kΩ / 100 kΩ feedback divider, carried in the schematic as "a starting
point from the datasheet's 3V3 example".

It was not. The TPS62130 regulates FB to 800 mV (§9.2.2.1, equation 6:
`R1 = R2 × (Vout/0.8 − 1)`), so that divider sets

    Vout = 0.8 × (1 + 180/100) = **2.24 V**

onto a net named `+3V3`. For 3.3 V the top resistor needed to be 312.5 kΩ.
Nothing caught it: ERC checks connectivity, not arithmetic, and every part
was correctly connected to a net whose *name* said 3.3 V. The board would
have browned out the STM32H753 and undervolted all three IMUs.

Choosing the fixed part removes the divider rather than correcting it — two
fewer components, no divider tolerance stacking on the reference, and the
output voltage becomes a property of the ordering code instead of something a
resistor substitution can silently change. `check_fmu_schematic.py` now
asserts every rail produces the voltage its name claims, and is
negative-tested against exactly this divider.

**U22 stays an LDO** (AP2112K-3.3, +3V3 → +3V3A). It carries only VDDA and
VREF+ — a few mA — so its drop is negligible, and an LDO is the right choice
there precisely because it is quiet. Putting the analog rail behind the same
switcher that feeds the digital load would inject its ripple into the ADC
reference.

## Still open

- microSD write current is an estimate; pin it down once the socket is chosen.
- VOS0 run current at 480 MHz, as above.

## Settled

The output filter is **L1 2.2 µH + C27 22 µF**, which is not a guess either:
SLVSAG7F table 9-2 lists the proven L/C combinations and marks 2.2 µH / 22 µF
as "the standard value and recommended for most applications". The rest of
the network follows the datasheet's own typical application (figure 9-1):
C26 10 µF on PVIN, C28 100 nF on AVIN, C29 3.3 nF setting the soft-start ramp
on SS/TR, and R3 100 kΩ pulling up PG — which is open-drain and, until this
pass, was wired to a net nothing on the board could drive.

FSW is tied low (2.5 MHz — smallest solution size and lowest output ripple,
§9.2.1) and DEF low (nominal output, not nominal +5%). FB goes to AGND, which
the datasheet recommends on fixed-output versions for thermal reasons.
