# Over- and under-voltage behaviour — JXK-1

JFOX Aircraft Co., Ltd.

What the hardware does when the supply leaves its window, taken from the
generated schematics rather than from intent. Three findings are real
defects; they are marked as such.

---

## 1. The window

The backplane's LTC4417 accepts a feed only inside a window set by its
divider chain. Both comparators sit at 1 V, so `UV = Rtot/(Rmid+Rbot)` and
`OV = Rtot/Rbot`. With 787k / 49k9 / 174k on both inputs:

| | Threshold |
|---|---|
| Under-voltage, feed rejected below | **4.52 V** |
| Over-voltage, feed rejected above | **5.81 V** |
| Accepted window | 4.52 – 5.81 V |

Applied independently to PWR 1 (RH) and PWR 2 (LH). The part holds whichever
feed it selected until that feed leaves the window — it does not chatter
between two supplies sitting close together, which a diode OR would.

---

## 2. Under-voltage

### One feed low

The LTC4417 turns off that feed's pass FET and switches to the other. The
card sees no interruption beyond the switchover, which is fast enough that
the bulk capacitance on `+5V_CARRIER` covers it.

This is the case the two-feed architecture exists for and it works.

### Both feeds low

`VBAT_IN` collapses. Every card loses power together.

**This is a common-cause failure and no amount of triple redundancy helps.**
Three channels share two feeds; two feeds out of window is total loss. It is
irreducible without triplicating the airframe supply, and it is worth
stating plainly rather than leaving implied by the block diagram.

### What the card does as its rail decays

| Rail | Part | Drop-out |
|---|---|---|
| `+3V3` | TPS62132 buck | regulates down to roughly 3.5 V in |
| `+3V3A` | AP2112K-3.3 LDO | needs ~3.6 V in |

Both hold well below the 4.52 V the LTC4417 cuts off at, so the ORing stage
is the limiting element, not the regulators. The card is switched off before
either regulator is anywhere near dropping out — which is the right way
round: a clean cut beats a slow brown-out through the MCU's operating
minimum.

**Not analysed:** what the MCU does between the supply leaving spec and the
rail actually collapsing. The STM32H753 has a programmable brown-out
detector; nothing in the firmware configures it. Until it does, behaviour in
that window is undefined rather than safe.

---

## 3. Over-voltage

### One feed high

Rejected above 5.81 V, the other feed carries. Same mechanism as
under-voltage, and it works the same way.

### FINDING 1 — the over-voltage threshold is above a part's absolute maximum

`U22` is an **AP2112K-3.3**, and it is fed from `+5V`.

| | |
|---|---|
| AP2112K absolute maximum input | **6.0 V** |
| LTC4417 accepts up to | **5.81 V** |
| Margin | **190 mV** |

So a feed sitting at 5.80 V is *accepted as good* and applied to a part
190 mV from its destruction limit — before any transient, ripple or
measurement tolerance is counted. DO-160G section 16 requires surviving
transients well beyond steady state; this has no room for one.

Two ways out:

1. **Lower the OV threshold.** 5.5 V leaves 500 mV. Costs nothing but a
   resistor value, and 5.5 V is still well above anything a healthy 5 V feed
   should reach.
2. **Feed U22 from `+3V3` instead of `+5V`.** It is a 3.3 V LDO producing a
   quiet analog rail; running it from the switched 3.3 V halves its dropout
   burden and removes the exposure entirely. Better answer, larger change.

`U21` (TPS62132) is not affected — 17 V absolute maximum.

### FINDING 2 — no transient suppression on the accepted rail

`check_fmu_objective` reports this against nets that have since moved to the
backplane, so the message is stale, but the underlying gap is not: nothing
clamps `VBAT_IN` or `+5V_CARRIER`. The LTC4417 rejects a *sustained*
out-of-window feed; it does not clamp a spike, and its own pass FETs are in
series with whatever arrives.

DO-160G section 17 (voltage spike) and section 16 (power input) both apply.
A TVS on each feed ahead of the ORing stage is the ordinary answer.

---

## 4. FINDING 3 — the MCU cannot see any of this

The card edge carries three power-valid inputs:

```
contact 55  BRICK_VALID
contact 57  SERVO_VALID
contact 58  USB_VALID
```

The backplane's LTC4417 produces two valid outputs, `RH_VALID` and
`LH_VALID`. **Neither appears as a net on either board.**

The three nets the card listens to are the names from the *previous*
architecture, when the FCU carried its own three-input ORing for brick,
servo and USB. When the power tree moved to the backplane those names came
with the pinout and nothing reconnected them.

Consequences:

- The MCU cannot tell whether it is running on the primary or the standby
  feed.
- It cannot tell that one feed has failed, so a silent single failure
  consumes the redundancy with nobody informed. The set flies on one supply
  believing it has two.
- `PreArmChecks` cannot include supply health, because there is no signal
  to read.

The fix is a rename, not a redesign: the card should listen to `PWR1_VALID`
and `PWR2_VALID`, and the third contact becomes spare or carries the
LTC4417's `STAT` output. It has to be done on both sides at once — the two
boards share `MEZZ_PINS`, so the pinout stays consistent by construction,
but the *names* only match if both are changed together.

---

## 5. Summary

| Condition | Hardware response | Adequate? |
|---|---|---|
| One feed < 4.52 V | switches to the other | yes |
| Both feeds < 4.52 V | total loss, all channels | irreducible |
| One feed > 5.81 V | switches to the other | yes |
| Feed at 5.80 V, sustained | **accepted**, applied to a 6.0 V part | **no — Finding 1** |
| Spike on either feed | not clamped | **no — Finding 2** |
| Any of the above | MCU is not told | **no — Finding 3** |
| Rail decaying through the MCU's minimum | undefined | not analysed |

---

## 6. Recommended order

1. **Finding 3** — a rename on both boards. Cheapest, and it turns the other
   two from invisible into observable.
2. **Finding 1** — change the OV divider to put the threshold at 5.5 V.
   One resistor value; the divider equation is already implemented and
   checked in `check_fmu_schematic.py`.
3. **Finding 2** — add a TVS per feed ahead of the ORing stage.
4. Configure the STM32H753 brown-out detector and define what the firmware
   does in the window between "supply out of spec" and "rail gone".

None of these is blocking for a first article on the bench. All four are
blocking before flight.

---

## 7. Correcting package — what was built

Applied in commits `2e5e6d7` and this one. Every item below is now checked
by `check_base_schematic.py`, which failed on first run — the only reason to
trust it.

### The window

`787k / 28k7 / 196k` → **UV 4.50 V, OV 5.16 V**.

Finding 1 above named the AP2112K at 6.0 V as the binding part. It was not.
The checker compared against *every* part downstream and found the
**ISOW1044 at 5.5 V absolute maximum** — the old 5.81 V threshold was
**310 mV above it**. Not thin margin: negative margin. A feed the controller
reported as good would have destroyed the isolator.

| Part | Abs max | Margin at 5.16 V |
|---|---|---|
| ISOW1044 | 5.5 V | **+338 mV** |
| AP2112K-3.3 | 6.0 V | +838 mV |
| TPS62132 | 17 V | — |

### Protection, per feed

**Assumed: DO-160G §22 pin injection Level 3.** Not specified, so it is
stated in the sheet note and here rather than left implicit. Level 4 or 5
need larger clamps and more series impedance; these parts would not survive
them.

| Ref | Part | Purpose |
|---|---|---|
| L60/L61 | 10 µH series | limits d*i*/d*t* so the clamp sees a survivable edge |
| D60/D61 | SMCJ6.0A | 1500 W, 6.0 V standoff — above the 5.16 V accepted, so off in normal operation |
| D50/D51 | SS54 (retained) | reverse blocking — the pass FETs only block in the orientation the controller drives them, and a feed connected backwards is exactly when it has no say |
| C60 | 1800 µF | feed-to-feed switchover ride-through |
| R80–82 / C80–82 | soft-start | inrush per slot |

Order is deliberate: series L, then clamp, then ORing, then bulk. A TVS with
nothing ahead of it absorbs the whole injected energy itself, which is how a
correctly chosen part still fails.

### §16 POWER INTERRUPT IS NOT MET

Stated plainly because the arithmetic is not close. Three cards at 1.2 A,
riding 5.16 V down to 4.50 V — 0.66 V of usable droop:

| Interrupt | Capacitance needed |
|---|---|
| 1 ms | 1.8 mF |
| 10 ms | 18.2 mF |
| 50 ms | 90.9 mF |
| **200 ms** | **363.6 mF** |

364 mF at 5 V is a supercapacitor bank, not a capacitor. C60 is sized for
what it *can* cover — the switchover the ORing stage itself creates, about
1 ms. Meeting §16 means holding up at a higher voltage ahead of the ORing,
or requiring the airframe to provide it. Both are decisions above this
board.

Sizing for the case you can meet and letting the requirement imply you met
the other one is how this goes wrong quietly.

### A fifth defect, found while fixing the others

**The ORing controller's output was never connected.** Its pin map was
written from the datasheet's block diagram rather than the symbol:

| Written | Actual |
|---|---|
| `VALID1..3` | `~{VALID1..3}` — active low, overbar in the name |
| `OUT` | `VOUT` |
| `HYST` | `HYS` |
| `STAT` | **does not exist on this part** |

`nets.get()` returns `None` for an unknown key, so six pins were silently
left unwired — `VOUT` among them. `PWR_ORED` was fed only by D50/D51 and the
entire prioritised-ORing stage was decorative. An unconnected pin is not a
DRC error, and nothing read this board.

### Still not met

| | |
|---|---|
| §16 power interrupt | not achievable at this voltage — see above |
| §17/§22 clamping performance | needs injection testing; the design is intended to pass, only a lab shows it does |
| §22 level | **assumed** Level 3 — confirm before fabrication |
| ORing PMOS | still the placeholder value `PMOS`; `SQJ431EP` is named in the source but no code places it |
| `VBUS_USB` suppression | U40 clamps the data lines; VBUS itself is unprotected |
| Six protection parts | carry assumed temperature data, which is not evidence |
