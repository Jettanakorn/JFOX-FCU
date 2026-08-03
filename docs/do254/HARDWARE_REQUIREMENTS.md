# JFOX-FMU v1 — hardware requirements

Read `README.md` in this directory first. This is not a certification
artifact.

Each requirement has a stable ID, a rationale, and a **verification** naming a
check in `hardware/tools/` that demonstrates it against the exported netlist.
`check_hw_traceability.py` runs the matrix and fails if any requirement's
check is missing or failing, or if a check exists that no requirement claims.

Verification is written as `tool :: check label`, where the label is the text
the tool prints. The label is the contract — renaming it breaks traceability
loudly, which is the intent.

Legend for **Status**: `V` verified by an executing check · `D` design intent
recorded but not yet verifiable · `X` not met, gap is open.

---

## Redundancy and fault containment

These are the requirements the DAL A architectural argument rests on. See
`README.md`, "On the DAL A target specifically".

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-RED-001 | The board shall carry three inertial measurement units. | Two allow fault *detection*; three allow fault *isolation* by majority vote. | `check_fmu_objective :: 3 IMUs from 2 vendors` | V |
| HWR-RED-002 | The three IMUs shall come from at least two independent vendors. | A vendor-wide errata or process fault must not remove the whole attitude solution. Common-mode failure is the reason redundancy alone is not enough. | `check_fmu_objective :: 3 IMUs from 2 vendors` | V |
| HWR-RED-003 | Each IMU shall be on its own SPI bus. | A sensor that hangs its bus must not take the other two with it. | `check_fmu_objective :: each IMU on its own SPI bus and its own switchable rail` | V |
| HWR-RED-004 | Each IMU shall be powered from its own independently switchable rail. | A wedged sensor must be recoverable by power cycling it alone. | `check_fmu_schematic :: each IMU is on its own switchable rail` | V |
| HWR-RED-005 | The board shall carry two barometers from two independent vendors. | Altitude is the one axis inertial sensing cannot hold; a second vendor makes the pair diverse rather than merely duplicated. | `check_fmu_objective :: 2 barometers from 2 vendors` | V |
| HWR-RED-006 | The board shall carry a magnetometer. | Heading reference; without it yaw is unobservable in steady flight. | `check_fmu_objective :: magnetometer present` | V |
| HWR-RED-007 | The board shall provide two CAN interfaces, each with its own transceiver, usable as a redundant Cyphal transport group. | Cyphal handles redundancy at the transport layer across independent interfaces; two controllers give controller-level redundancy, not merely isolator-level. | `check_fmu_objective :: 2 CAN buses, both with transceivers` | V |
| HWR-RED-008 | The board shall carry no IO co-processor. | Deliberate: board-level TMR already provides the independent failure path an IO chip is usually there for, and removing it removes a whole MCU and a class of pin-ownership ambiguity. Listed so that adding one is a visible decision. | `check_fmu_objective :: no IO co-processor` | V |

## Power integrity

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-PWR-001 | Every supply rail shall be a distinct net; no two rails may share a node. | A rail short is catastrophic and structurally invisible — ERC accepts a short as well-formed. This requirement exists because the board *was* built for a while with GND merged into +3V3. | `check_fmu_schematic :: supply rails are separate nets` | V |
| HWR-PWR-002 | Every MCU supply pin shall connect to its rail in the netlist. | Fourteen VDD pins were once floating while the schematic plotted as a connected rail. Drawings can lie; netlists are what the board is made from. | `check_fmu_schematic :: all MCU supply pins sit on their rail` | V |
| HWR-PWR-003 | Each rail shall produce the voltage its net name claims. | A net named `+3V3` fed by a divider computing 2.24 V passes every structural check. Rail names are claims, and this makes them testable. | `check_fmu_schematic :: rails produce the voltage their name claims` | V |
| HWR-PWR-004 | Power input selection shall be prioritised with per-input under- and over-voltage lockout. | A failing source must be shed rather than dragged along, and priority must be deterministic. | `check_fmu_schematic :: power tree: 4 independent sensor rails, ORing intact` | V |
| HWR-PWR-005 | The LTC4417 under/over-voltage thresholds shall be set by resistor dividers. | **Open gap.** `UV1_SET`/`OV1_SET` and their siblings terminate in isolated labels; the ORing controller currently has no configured trip points, so HWR-PWR-004 is met structurally but not parametrically. | none — gap | X |
| HWR-PWR-006 | Decoupling shall be provided per MCU supply pin, plus bulk per rail, plus the regulator's mandated capacitors. | Absence fails no rule and stops no fabrication; it shows up as an MCU that resets under load. | `check_fmu_schematic :: decoupling, VCAP caps, crystals and CAN terminators present` | V |

## Isolation

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-ISO-001 | Off-board I/O shall cross a galvanic isolation barrier. | External wiring is where the energy and the faults are; isolation turns a shorted motor lead into a barrier event rather than a dead flight computer. | `check_fmu_objective :: off-board I/O crosses a galvanic barrier` | V |
| HWR-ISO-002 | The isolated side of each barrier shall have its own supply, not a rail borrowed from the digital side. | Sharing the rail defeats the barrier entirely. | `check_fmu_objective :: isolated side has its own supply` | V |
| HWR-ISO-003 | Each isolated link shall report failure of its isolated supply. | A redundant link whose failure is silent is not redundant. Implemented as the ISOW1044 `EN/FLT` fault output with a pull-up. | none yet — `CAN1_FLT`/`CAN2_FLT` reach no MCU pin | D |
| HWR-ISO-004 | Actuator links shall be fibre-optic. | **Open gap.** No fibre transmitters or receivers exist. ~960 mA of transmitter current against a 550 mA peak budget means the power architecture must be redone to meet this. | `check_fmu_objective :: actuator links are fibre-optic` | X |
| HWR-ISO-005 | Every off-board signal shall cross the barrier by two independent paths. | One failed isolator must not lose the link — the same argument as three IMUs, applied to I/O. | none yet | D |

## Interface correctness

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-IFC-001 | Every sensor signal shall land on the pin its datasheet specifies. | Both pin 11 and pin 12 are electrically plausible; only the datasheet says which is right. | `check_fmu_schematic :: signals land on the datasheet's pins` | V |
| HWR-IFC-002 | Pins the datasheets *require* to be tied shall be tied. | "Connect to GND" is not "may be left open" — several of these parts are damaged or silent otherwise. | `check_fmu_schematic :: datasheet-mandated ties are tied` | V |
| HWR-IFC-003 | Every MCU peripheral signal shall reach the pin the allocator assigned. | The previous board's hand-written pin map put five of eight PWM channels on top of SPI1 and SPI2. Allocation is mechanical; this asserts the schematic honoured it. | `check_fmu_schematic :: MCU signals reach the pin the allocator chose` | V |
| HWR-IFC-004 | The shared I2C bus shall have pull-up resistors. | Open-drain: without them the bus never idles high and no sensor answers. Both sensor datasheets state it explicitly. | `check_fmu_objective :: shared I2C bus has pull-ups` | V |
| HWR-IFC-005 | The design shall be one electrically connected circuit across all sheets. | Global labels connect only once the sheets are children of a common root; before that they read as isolated on both ends. | `check_fmu_schematic :: nets span sheets - the design is one circuit` | V |
| HWR-IFC-006 | Non-volatile storage shall be provided for parameters and calibration. | Calibration that does not survive power-down is not calibration. | `check_fmu_objective :: FRAM present` | V |

## Manufacturability

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-MFG-001 | Every component shall have a footprint that resolves through the project's library tables. | "Does this file exist" and "can KiCad find it" are different questions, and only the second decides whether a board can be built. | `check_fmu_footprints :: components have a footprint that resolves` | V |
| HWR-MFG-002 | Every sheet's content shall fit inside its drawing frame and clear the title block. | A sheet that overflows is silently cropped by the plotter, and the drawing then misrepresents the board. | `check_fmu_sheets :: sheets fit inside the frame and clear the title block` | V |
| HWR-MFG-003 | Custom footprints shall be derived from the manufacturer's package drawing, with pad centres re-derived from an independent dimension. | A footprint whose name matches and whose geometry does not is worse than a missing one. | `gen_fmu_footprints :: check()` (runs at generation) | V |

---

## Requirements not yet written

Deliberately listed rather than omitted, because an incomplete matrix that
looks complete is the failure mode this whole directory exists to avoid:

- Environmental qualification (DO-160) — temperature, vibration, EMC. None.
- Component derating and worst-case analysis. None.
- Thermal analysis. The TPS62132 and the ISOW1044s are the candidates.
- Signal integrity for USB and CAN FD — impedance control, length matching.
- Manufacturing test and acceptance criteria.
- Part obsolescence and procurement control (AC 20-152A COTS-1…COTS-8).
