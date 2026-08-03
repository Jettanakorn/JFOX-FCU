# JFOX-FMU v1 — architecture

A ground-up flight controller to replace the PX4FMUv2.4.5 modules. That board
is a **guideline only**: its proven ideas are kept (prioritised power ORing,
stacking, CAN voting bus) and its limitations are not.

Status: **capture in progress**. The sensor sheet is drawn and checked
against the datasheets; MCU, power and comms sheets are next.

| Sheet | State |
|---|---|
| `sensors.kicad_sch` | drawn, wiring verified against the datasheets |
| `mcu.kicad_sch` | drawn, 96 pins wired, all verified against `PINMAP.md` |
| `power.kicad_sch` | drawn, wiring verified |
| `comms.kicad_sch` | drawn - CAN FD x2 with jumpered termination, USB-C, microSD |
| `jfox-fmu.kicad_sch` | root - all four sheets are one project |

**Schematic capture is complete.** What remains before layout: PWR_FLAG
symbols on the rails, decoupling capacitors, and connectors for the UARTs and
PWM outputs, which is why ERC still reports unconnected pins on those nets.

`tools/check_fmu_schematic.py` verifies all three sheets against their
sources and is negative-tested throughout.

`tools/check_fmu_schematic.py` verifies both sheets against their sources -
sensor nets against the datasheet pin tables, MCU nets against the allocator's
choice - and is negative-tested.

## What changes, and why

| | PX4FMUv2.4.5 (current) | JFOX-FMU v1 |
|---|---|---|
| MCU | STM32F427VIT6, Cortex-M4 @180 MHz | **STM32H753IIT6**, Cortex-M7 @480 MHz |
| RAM | 256 KB (192 main + 64 CCM) | **1 MB** |
| Flash | 2 MB | 2 MB |
| IMU | 1 × MPU-6000 | **3 ×, two vendors, one SPI bus each** |
| Baro | 1 × MS5611 | 2 ×, two vendors |
| CAN | 1 × classic, **fixed 120 Ω** | 2 × CAN FD, **switchable termination** |
| Crypto | none | hardware AES/HASH (for JFOXLink) |
| Co-processor | STM32F103 IO chip, unused by this firmware | none — see below |

Two of those deserve saying plainly.

**The RAM is the point.** 256 KB is what forced `MPC_ADMM_MAX_ITERS` to be
guessed rather than sized, and what makes onboard logging impractical. 1 MB
changes what the control law and the black box can do.

**The fixed terminator is a defect being fixed.** Every v2.4.5 carries R409,
120 Ω hard across CAN_H/CAN_L with no jumper, so a three-board bus needs one
module physically desoldered — recorded all over `HARDWARE_BRINGUP.md` and on
the carrier silkscreen. v1 puts termination behind a jumper.

## Redundancy at two levels

Both, as decided:

- **Within a board** — three IMUs voted in software. A single failed sensor
  no longer removes its whole board from the system vote.
- **Across boards** — three boards exchanging command votes over CAN, which
  is what `flight::redundancy::TmrVoter` and `hal::can` already implement.

### Sensors

Following what Pixhawk FMUv6X actually ships (read from PX4's own
`boards/px4/fmu-v6x/init/rc.board_sensors` and `src/spi.cpp`, not recalled):
**three IMUs from two vendors, each on its own SPI bus, each with its own
power-enable GPIO.** The separate buses matter — one sensor hanging its bus,
or needing a power cycle to recover, must not take the other two with it.

| Bus | Part | Vendor | Why |
|---|---|---|---|
| SPI1 | BMI088 (2 CS: accel, gyro) | Bosch | Different silicon and different vendor from the other two — the real common-mode protection |
| SPI2 | ICM-42688-P | TDK InvenSense | Current Pixhawk workhorse, low noise |
| SPI3 | ICM-45686 | TDK InvenSense | Newest generation, best noise/stability |
| SPI4 | FM25V02 FRAM | Infineon | Parameters and calibration |
| SPI5 | external / spare | — | Brought to a connector |

Barometers: **BMP388** (Bosch) + **ICP-20100** (TDK) on I2C — two vendors
again. Magnetometer: **BMM150** internal, plus an external compass on the GPS
connector's I2C.

Honest note: two of the three IMUs are TDK parts, so a TDK-wide errata is not
fully covered. FMUv6X makes the same compromise. True three-vendor diversity
means an ADI **ADIS16470** in place of one of them — far better, several times
the cost, and worth revisiting if the airframe justifies it.

## Isolated I/O — objective, not yet built

**Every off-board signal crosses a galvanic isolation barrier, and every one
of them crosses it twice, by two independent paths.** Actuator links are
fiber-optic. This is a requirement on the design, added deliberately; the
board described everywhere else in this document does **not** meet it yet.

Why: a flight controller's external wiring is where the energy and the faults
are. A shorted motor lead, an ESC dumping switching noise back up its signal
wire, or a servo harness chafing against the airframe all reach the MCU
directly today. Isolation turns those into a barrier event instead of a dead
flight computer. Two paths per signal means one failed isolator does not lose
the link — the same argument that gives the board three IMUs.

### What this costs, measured rather than estimated

Checked against the part's own alternate-function table
(`plan_pinout.py`, from `STM32H753II.json`):

| Resource | Needed for 2× isolated | Available | Verdict |
|---|---|---|---|
| Timer channels (8 PWM × 2) | 16 | 32 | fits |
| GPIO (currently free) | — | 91 of 176 | fits |
| UART instances (RC + telemetry × 2) | 4–6 | 8 | fits |
| **FDCAN controllers** | **4** | **2** | **does not fit** |

The CAN row is the real constraint and it is not solvable by re-allocation.
The STM32H753 has exactly two FDCAN controllers. "Two independent paths" for
two buses needs four. Three ways out, none free:

1. **One redundant bus instead of two.** FDCAN1 and FDCAN2 become the A and B
   paths of a single TMR voting bus, each with its own isolated transceiver.
   Full controller-level redundancy, at the cost of the second bus.
2. **Two buses, isolator-level redundancy only.** Each bus keeps one
   controller and gets two isolated transceivers in parallel. Survives a dead
   isolator, not a dead controller — the controller stays a single point of
   failure.
3. **An external CAN controller** (MCP2518FD on SPI5, which is currently spare).
   Four independent controllers, at the price of a part, a bus, and a driver.

This needs a decision before the isolated design can be drawn. Option 1 is the
honest one for a TMR system: the voting bus is the thing that must not fail,
and a second unredundant bus is worth less than one redundant bus.

### Power, which is where this really bites

Fiber transmitters are current-driven. A 660 nm POF transmitter of the
HFBR-1521 class wants ~60 mA of forward current. Eight actuator links, two
paths each, is sixteen transmitters:

    16 × 60 mA ≈ 960 mA

The whole board is budgeted at **310 mA typical, 550 mA peak** today
(`POWER_BUDGET.md`). The fiber transmitters alone are roughly three times the
present total. The TPS62132 can source 3 A so the regulator survives, but the
budget, the thermal design and the input feed all have to be redone, and the
isolated side of each barrier needs its own supply — an isolated DC-DC, not a
rail borrowed from the digital side, or the isolation is decorative.

### Beyond this board

Fiber to the actuators means **every ESC needs a fiber receiver**. That is an
airframe and propulsion decision, not a flight-controller one, and it should
be settled before this board is laid out — the connector choice depends on it.

### Status

`check_fmu_objective.py` asserts these requirements. It currently **fails**,
by design: the objective is recorded so the gap is visible and measured,
rather than remembered.

## Why no IO co-processor

v2.4.5 carries an STM32F103-class IO chip owning the safety switch, RC input
and 8 PWM channels. **This project's firmware has never run code on it**, which
is why J702's safety switch does nothing today — it lands on `U801.PB5`, in a
domain the FMU never initialises.

Dropping it is deliberate: an M7 at 480 MHz with 140 GPIO can drive PWM and
decode RC directly, and board-level TMR already provides the independent
failure path an IO chip is usually there for. It removes a whole MCU, its
firmware, and a class of "which chip owns this pin" confusion.

The cost is that there is no independent processor to hold outputs safe if the
FMU hangs. That is covered by the watchdog and by the other two boards
outvoting a failed one — but it *is* a real difference from PX4 practice and
should be argued explicitly in the safety case, not assumed away.

## MCU

**STM32H753IIT6** — LQFP176, 0.5 mm pitch, hand-solderable, unlike the BGA
packages the same die is also sold in.

Verified from KiCad's own `STM32H753IITx` symbol (165 pins):

- 14 × VDD, 1 × VDDA / VSSA, 1 × VREF+, 1 × VBAT
- **2 × VCAP** — the internal LDO's decoupling, so this is the LDO supply
  configuration; each needs its own 2.2 µF close to the pin
- **VDD33_USB** — separate USB transceiver supply, decoupled independently
- **PDR_ON**, NRST, BOOT0
- **140 GPIO**

**Settled, from ST's datasheet rather than from the symbol:** the internal
regulator is the **LDO**, and not by preference. §"Voltage regulator" states
that Scale 0 - boosted performance - is *"available only with LDO regulator"*,
and 480 MHz requires VOS0. So the two VCAP pins and their 2.2 uF are right,
and the SMPS option is unavailable to this design at this clock. LQFP176 is
also confirmed as a real package for this part, from the same datasheet.

Clock: 16 MHz HSE crystal (H7 PLLs reach 480 MHz cleanly from 16 MHz and it
divides exactly to the 48 MHz USB clock — avoiding the 24 MHz problem that
made the current board's USB clock 51.4 MHz instead of 48, and forced a
second PLL). 32.768 kHz LSE for the RTC.

## CAN

Two **FDCAN** controllers, both with transceivers — v2.4.5 wired CAN2 to the
MCU with no transceiver at all, so it was never usable as a bus.

**Termination is switchable.** A 120 Ω resistor per bus behind a solder jumper
(default: fitted). The middle module of a three-board chain clears its jumper
instead of having a resistor desoldered.

## Power

Keeping v2.4.5's best idea: an **LTC4417** prioritised ORing controller
selecting between brick, servo rail and USB, with under/over-voltage lockout.
That part is correctly identified here — the current board's docs called it a
BQ24315 until the netlist proved otherwise.

Rails: 5 V from the brick → 3V3 main (**TPS62132 buck, fixed 3.3 V**) → separately
switchable 3V3 per sensor bus (so a wedged IMU can be power-cycled) → clean
3V3 analog for VDDA/VREF+ (**AP2112K LDO**, deliberately linear so its ripple
does not reach the ADC reference).

The main rail is a buck because the budget says it has to be - ~310 mA typical
and ~550 mA peak means an LDO would burn 0.53-0.94 W in a package that sheds
neither. See `POWER_BUDGET.md`, which shows the working.

### The per-bus switching has a firmware obligation attached

From the BMP388 datasheet (§3.2), and assume it holds for the IMUs too:

> "Holding any interface pin (SDI, SDO, SCK or CSB) at a logical high level
> when VDDIO is switched off can permanently damage the device due caused by
> excessive current flow through the ESD protection diodes."

So the recovery mechanism can destroy the part it is recovering. **Before
removing a sensor bus's supply the firmware must drive that bus's SCK, MOSI
and CS low** (and release MISO), then restore them only after the rail is back
up. Powering a bus down by simply clearing its enable GPIO is a latent way to
kill sensors — slowly, and only on the boards that ever had to recover one.

This is a hardware feature creating a firmware requirement, so it is written
down here rather than left to be rediscovered: see
`jfox-fmu-v1/PINOUTS.md` for the quote and its provenance.

## Form factor and the carrier

Custom, as decided — not the Pixhawk Autopilot Bus.

The one thing worth taking from PAB is the idea: replace nine DF13 cable
connectors with a **board-to-board connector** to the carrier. The existing
carrier PCB is built for v2.4.5's DF13 pinout and **will not fit this module**;
it needs a redesign alongside. Its verified content — CAN daisy chain,
independent per-board power, no on-carrier termination — carries over
unchanged.

## What this costs on the firmware side

Not free, and worth stating before anyone starts:

- Different PAC crate (`stm32h7` instead of `stm32f4`) and a different clock
  tree; `bsp/` is rewritten.
- Every driver in `hal/` is register-level and F4-specific — GPIO, SPI, UART,
  PWM, CAN (bxCAN → **FDCAN**, a different peripheral), DWT.
- Cortex-M7 adds caches and tightly-coupled memories. The D-cache and DMA
  interact in ways the M4 never did; this is a real source of bugs and needs
  deliberate handling, not a port-and-hope.

What survives untouched: `math/`, `flight/` (control law, MPC, adaptive,
redundancy, arming, BIT), `common/`, `telemetry/`, and the whole SITL rig.
That is the majority of the tested code, and it survives precisely because it
was kept free of hardware dependencies.

## Symbol availability

Checked against the installed KiCad 10 libraries, because "draw four symbols"
is real work that should be known before starting rather than discovered
mid-capture:

| Part | Symbol |
|---|---|
| STM32H753IITx | stock — `MCU_ST_STM32H7` |
| BMI088 | stock — `Sensor_Motion` |
| BMM150 | stock — `Sensor_Magnetic` |
| LTC4417 | stock — `Power_Management` |
| ICM-42688-P | **drawn** — `jfox-fmu.kicad_sym` |
| ICM-45686 | **drawn** |
| BMP388 | **drawn** |
| ICP-20100 | **drawn** — `jfox-fmu.kicad_sym` |
| FM25V02A | **drawn** |

All four are drawn, in `jfox-fmu.kicad_sym`, generated by
`tools/gen_fmu_symbols.py` from the verified tables in `PINOUTS.md` rather than
drawn by hand - so the symbols and the datasheets cannot drift apart.

Pin electrical types are chosen to make ERC do work: the ICM-42688-P's pin 7,
which the datasheet says must go to GND rather than may, is typed `power_in`,
so leaving it floating is reported rather than passing quietly. Each symbol
also carries a hidden `Note` property with its datasheet constraint, so the
warning travels with the part into the schematic instead of living only in a
document nobody opens.

KiCad accepts the library and renders all four.

## Open, before schematic capture

1. SMPS vs LDO supply configuration (above).
2. ADIS16470 for genuine three-vendor IMU diversity — cost vs benefit.
3. The board-to-board connector part, which fixes the mechanical envelope.
4. Whether to keep the 30 × 30 mm M3 pattern for continuity with existing
   mounting hardware.
