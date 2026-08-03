# DO-160G environmental qualification — plan and current standing

Read `README.md` in this directory first.

## What this can and cannot be

**DO-160G is a test standard.** Qualification means an accredited lab, a
thermal chamber, a shaker table, an anechoic chamber, and a real board. No
document produces it, and nothing here should be read as a qualification
statement. This board has never been fabricated.

What *is* possible before hardware exists, and is what this document does:

1. **Choose the categories** the equipment will be qualified to, with the
   reasoning recorded rather than assumed.
2. **Check the parts can support them.** A temperature range is a datasheet
   fact. A part rated to −40 °C cannot pass a −55 °C category however the test
   is run, and finding that out in a chamber is the expensive way.
3. **Record the design implications** each category imposes, so they are
   constraints on layout rather than surprises after it.

`check_hw_environmental.py` does (2) on every run.

## The finding that matters most

**The MCU has already decided which categories are reachable, and nobody
chose that.**

`STM32H753IIT6` — the ordering-code suffix `6` is **−40 to +85 °C**
(ST DM00388325 p346). ST does not offer this part at −55 °C in any grade. So
every DO-160G Section 4 category with a −55 °C low operating temperature —
which is most unpressurised categories — is unreachable with this
microcontroller. Not difficult: unreachable.

That constraint was created by a part choice made for RAM and clock speed. It
is recorded here so that if a colder category is genuinely required, the
conversation is about changing the MCU, not about testing harder.

The rest of the BOM sits at the same −40/+85 industrial grade, so the MCU is
not uniquely limiting — but it is the one with no colder option.

## Section 4 — Temperature and Altitude

### Declared category: **A2** (−15 to +70 °C, pressurised)

Chosen as *the most demanding category the current BOM can actually support*,
which is an honest reason and not a good one. The correct basis is the
installation location and the aircraft's operating envelope, and **neither is
defined for this vehicle yet**. Specifically unknown:

- maximum operating altitude,
- whether the bay is pressurised, temperature-controlled, or neither,
- ground soak temperature in the intended operating geography.

Until those exist, A2 is a placeholder that the tooling enforces rather than a
justified selection. For an unpressurised UAV bay, category **B1** (−45 °C) or
a **D** category (−55 °C) would be the realistic candidates — and both are
already ruled out by the MCU. That is the point of writing it down.

### Accuracy is not the same as operation

`check_hw_environmental.py` reports this separately, because it is the kind of
thing that gets lost:

> **BMP388**: full accuracy only −20 to +65 °C, category spans −15 to +70 °C
> (BST-BMP388-DS001-07 rev 1.7 p3)

The part keeps operating past +65 °C. It simply stops meeting its altitude
accuracy specification. A barometer that is powered, responding, and quietly
out of spec is a worse failure than one that has stopped, because the flight
stack has no signal that the reading is wrong.

Two ways to address it, both real: state the accuracy limitation as a bound on
the altitude solution, or use the second barometer's disagreement to detect
the condition. The second is more in keeping with the rest of this design —
the ICP-20100 is already there for dissimilarity, and cross-checking it
against the BMP388 is exactly the sort of thing two vendors buys you.

## The other 25 sections

Categories are **not yet selected** for these. Listing them with their design
implications is the useful thing to do now; selecting them requires the
operating envelope above.

| § | Condition | Why it bites this board |
|---|---|---|
| 5 | Temperature variation | Rate of change drives solder-joint fatigue; the LQFP176 and the 2×2 mm LGA sensors are the parts to worry about. |
| 6 | Humidity | Drives conformal coating — which the BMP388 and ICP-20100 **must be masked from**, being open-cavity pressure sensors. This is a layout and process constraint, not a test result. |
| 7 | Operational shock and crash safety | Connector retention and part mass. |
| 8 | **Vibration** | The one that matters most for a flight controller: vibration couples straight into the IMUs as noise. Mounting, board stiffness and IMU placement are the design response. |
| 9 | Explosive atmosphere | Usually N/A for a UAV avionics bay. |
| 10–14 | Waterproofness, fluids, sand and dust, fungus, salt fog | Mostly enclosure-level, not board-level. |
| 15 | Magnetic effect | **Directly relevant**: the BMM150 is on this board. Current loops, and especially the switching regulator and any high-current trace, disturb it. Placement and return-path design are the mitigation. |
| 16 | Power input | The LTC4417 ORing and its (currently unset) UV/OV thresholds are the response. |
| 17 | Voltage spike | Input protection — **not currently present** on the schematic. |
| 18–19 | Audio-frequency conducted susceptibility, induced signals | Rail rejection and cable routing. |
| 20–21 | RF susceptibility and emission | The TPS62132 switches at 2.5 MHz; the ISOW1044's integrated DC-DC at 25 MHz. Both are deliberate emission sources on a board carrying a magnetometer and a GPS front end. |
| 22–23 | Lightning induced and direct effects | Depends entirely on installation and airframe material. |
| 24 | Icing | Enclosure-level. |
| 25 | **ESD** | Every off-board connector. The isolation barrier helps; the connectors themselves still need protection. |
| 26 | Fire and flammability | Material selection — PCB laminate, connector bodies. |

## Design implications already actionable

These do not need a category selected to be worth doing, and several are
absent from the current schematic:

- **No input transient protection** (§17). A TVS on the brick input is the
  usual answer and is not there.
- **No ESD protection on connectors** (§25). Also not there — although the
  connectors themselves are not there yet either.
- **Conformal-coating keep-outs** (§6) around U4 and U7. Both are open-cavity
  pressure sensors and coating them destroys the measurement. This must reach
  the fabrication drawing.
- **Magnetometer keep-out** (§15) from the switching regulator and any
  high-current path.
- **Vibration** (§8): IMU placement and mounting stiffness are a layout
  decision that has not been made.

## Environmental Qualification Form

DO-160G expects an EQF summarising the categories the equipment holds. The
skeleton is below, deliberately empty: every row requires a test that has not
been performed, on hardware that does not exist.

| § | Condition | Category | Result |
|---|---|---|---|
| 4 | Temperature and altitude | A2 *(provisional)* | not tested |
| 5 | Temperature variation | TBD | not tested |
| 6 | Humidity | TBD | not tested |
| 7 | Shock and crash safety | TBD | not tested |
| 8 | Vibration | TBD | not tested |
| 15 | Magnetic effect | TBD | not tested |
| 16 | Power input | TBD | not tested |
| 17 | Voltage spike | TBD | not tested |
| 20 | RF susceptibility | TBD | not tested |
| 21 | RF emission | TBD | not tested |
| 25 | ESD | TBD | not tested |

Sections not listed are either not applicable at board level or await the
installation definition.

## What has to happen before any of this is real

1. Define the vehicle's operating envelope and the installation location.
   Everything above is downstream of it.
2. Select categories against that envelope — and if any of them go below
   −40 °C, change the MCU before anything else.
3. Close the datasheet gaps the checker reports: BMI088, LTC4417, AP2112K and
   AP22804 currently carry **assumed** temperature data, which is not
   evidence.
4. Build hardware. Then test it.
