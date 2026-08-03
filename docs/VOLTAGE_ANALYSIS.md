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
