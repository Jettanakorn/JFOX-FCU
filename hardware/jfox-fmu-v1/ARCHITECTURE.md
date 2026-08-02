# JFOX-FMU v1 — architecture

A ground-up flight controller to replace the PX4FMUv2.4.5 modules. That board
is a **guideline only**: its proven ideas are kept (prioritised power ORing,
stacking, CAN voting bus) and its limitations are not.

Status: **specification**. No schematic captured yet.

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

*To confirm against the datasheet before layout:* whether to use the SMPS
supply option instead of the LDO. KiCad's symbol exposes no SMPS pins, which
suggests LDO-only for this package, but power architecture is not something to
settle from a schematic symbol. It matters for thermal design, not
correctness.

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

Rails: 5 V from the brick → 3V3 main → separately switchable 3V3 per sensor
bus (so a wedged IMU can be power-cycled) → clean 3V3 analog for VDDA/VREF+.

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
| ICM-42688-P | **draw** — pinout verified, see `PINOUTS.md` |
| ICM-45686 | **draw** — pinout verified |
| BMP388 | **draw** — pinout verified |
| FM25V02A | **draw** — pinout verified |

Four custom symbols, all small parts (14-pin LGA or 8-pin SOIC/DFN). **All
four pinouts are now verified** against the manufacturers' own datasheets and
recorded with provenance in `PINOUTS.md` - the one place in this design where
getting a number wrong is silently fatal. Nothing blocks schematic capture.

## Open, before schematic capture

1. SMPS vs LDO supply configuration (above).
2. ADIS16470 for genuine three-vendor IMU diversity — cost vs benefit.
3. The board-to-board connector part, which fixes the mechanical envelope.
4. Whether to keep the 30 × 30 mm M3 pattern for continuity with existing
   mounting hardware.
