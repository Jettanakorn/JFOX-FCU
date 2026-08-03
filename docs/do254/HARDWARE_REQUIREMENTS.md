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
| HWR-PWR-005 | The LTC4417 under/over-voltage thresholds shall be set by resistor dividers, and each input shall be switched by back-to-back pass devices. | Both were missing: the thresholds went nowhere and PGATE1-3 drove nothing, so the ORing controller had no trip points and no switches. Divider values from ADI's own equations, validated by reproducing the datasheet's worked example (806k/39.2k/60.4k → 9.09 V / 14.99 V). Two PMOS per input, sources common, because one would leave a permanent body-diode path. | `check_fmu_schematic :: power tree` | V |
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
| HWR-IFC-006 | Non-volatile storage for parameters and calibration shall be FRAM, not the SD card. | Calibration that does not survive power-down is not calibration — but the SD card is the wrong home for it. FRAM has unlimited write endurance, needs no filesystem, and a power loss mid-write cannot corrupt it. An SD card can be pulled, can wear out, and corrupts on power loss during a block write. `flight::calibration::storage` already targets FRAM with a magic word and an FNV-1a checksum so a blank or damaged record can never read as valid. | `check_fmu_objective :: FRAM present` | V |
| HWR-IFC-007 | A microSD socket shall be provided for flight logging, with card detect. | Logs are large, sequential and expendable — the opposite of parameters, and exactly what an SD card is good at. Card detect lets firmware distinguish "no card" (a pre-flight nag) from "card present but failing" (a logging fault); without it the two are indistinguishable. | `check_fmu_objective :: microSD socket with card detect` | V |


## Environmental (DO-160G)

See `DO160_ENVIRONMENTAL.md`. DO-160G is a test standard: everything below is
either a capability check that can be made before hardware exists, or a gap
recorded because it cannot.

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-ENV-001 | Every active component shall be rated across the declared DO-160G Section 4 category. | A temperature range is a datasheet fact. A part rated to −40 °C cannot pass a −55 °C category however the test is run, and a chamber is the expensive place to learn it. | `check_hw_environmental :: active parts support DO-160G category` | V |
| HWR-ENV-002 | Every component's temperature rating shall be cited to a datasheet, not assumed. | **Open gap.** BMI088, LTC4417CGN, AP2112K-3.3 and AP22804AW5 carry assumed data. Assumed ratings are how a BOM is qualified on paper and fails in a chamber. | `check_hw_environmental :: carry ASSUMED temperature data` | X |
| HWR-ENV-003 | The declared category shall derive from the installation location and the aircraft operating envelope. | **Open gap.** Neither is defined. Category A2 is currently the most demanding the BOM can support, which is an honest basis and not a correct one. | none — needs the vehicle envelope | X |
| HWR-ENV-004 | Where a sensor's full-accuracy range is narrower than the declared category, the limitation shall be stated and detectable. | The BMP388 operates past +65 °C but stops meeting its altitude accuracy spec. A sensor that is powered, responding and quietly out of spec is worse than one that has stopped. Cross-checking against the ICP-20100 is the intended detection. | `check_hw_environmental` reports the narrowing | D |
| HWR-ENV-005 | Open-cavity pressure sensors shall be masked from conformal coating. | Coating U4 and U7 destroys the measurement. This must reach the fabrication drawing, not just this document. | none — fabrication drawing does not exist | D |
| HWR-ENV-006 | Every power input shall carry transient suppression. | DO-160G §17 voltage spike. D4/D5/D6, 6 V standoff on each of the brick, servo and USB inputs — above the 5.5 V a valid supply reaches, below anything the LTC4417 or the buck will tolerate. Unidirectional: reverse battery is the LTC4417's job. | `check_fmu_objective :: power inputs have transient suppression` | V |
| HWR-ENV-007 | Off-board data lines shall carry ESD protection and common-mode suppression. | DO-160G §25 ESD and §21 radiated emissions. U40 (USBLC6-2SC6) sits closest to the USB connector so it protects the choke too; L5 follows it. Each CAN pair gets a common-mode choke and a TVS, both referenced to `GND_ISO`, not `GND` — referencing them to board ground would bridge the isolation barrier and undo the ISOW1044. | `check_fmu_objective :: data lines have ESD and common-mode suppression` | V |
| HWR-ENV-008 | The magnetometer shall be kept clear of switching converters and high-current paths. | DO-160G §15. The TPS62132 switches at 2.5 MHz and each ISOW1044's internal converter at 25 MHz, on a board carrying a BMM150. | none — layout not started | D |
| HWR-ENV-009 | The board shall carry a temperature monitor at its thermal hot spot, independent of the sensor dies. | **Open gap.** Five on-die sensors report their own temperature — the right measurement for compensating a sensor and the wrong one for protecting a regulator. Nothing measures the TPS62132 or the two ISOW1044 converters, which are the parts that actually dissipate. | `check_hw_environmental :: board hot-spot temperature monitor present` | X |
| HWR-ENV-010 | The board shall carry no IMU heater unless the deferred decision is revisited. | Deliberate deferral, not an omission. FMUv6X heats its IMUs and this design follows FMUv6X's sensor architecture, so a heater is a reasonable future step — but it roughly doubles board power (1–3 W against ~1–1.8 W) on a design with an unresolved 960 mA fibre demand, it fights the BMP388's −20/+65 accuracy window through local gradients, it interacts with the per-IMU switchable rails, and a stuck-on heater needs an over-temperature cutout independent of whatever failed. Asserted absent so that adding one is a visible decision. | `check_hw_environmental :: no IMU heater` | V |
| HWR-ENV-011 | Gyro bias shall be compensated against temperature using each IMU's own temperature output. | `flight/src/calibration/gyro_bias.rs` already records the problem: "bias drifts with temperature". Boot-time re-estimation does not address drift during flight as the board warms. Per-unit characterisation stored in the existing FRAM needs no board change and is the cheaper half of what a heater would buy. | none yet — firmware, not hardware | D |

## Manufacturability

| ID | Requirement | Rationale | Verification | Status |
|---|---|---|---|---|
| HWR-MFG-001 | Every component shall have a footprint that resolves through the project's library tables and carries at least as many pads as the symbol has pins. | "Does this file exist", "can KiCad find it" and "is it the right part" are three different questions. The LTC4417 is a 24-pin part and carried SSOP-16 — a real footprint, a real name, eight pads short, unbuildable. | `check_fmu_footprints :: components have a footprint that resolves` | V |
| HWR-MFG-002 | Every sheet's content shall fit inside its drawing frame and clear the title block. | A sheet that overflows is silently cropped by the plotter, and the drawing then misrepresents the board. | `check_fmu_sheets :: sheets fit inside the frame and clear the title block` | V |
| HWR-MFG-003 | Custom footprints shall be derived from the manufacturer's package drawing, with pad centres re-derived from an independent dimension. | A footprint whose name matches and whose geometry does not is worse than a missing one. | `gen_fmu_footprints :: check()` (runs at generation) | V |
| HWR-MFG-004 | Carrier I/O shall leave the module through a single board-to-board connector. | Eleven cable headers means eleven looms to make, inspect and vibrate loose. One 60-way 0.5 mm mezzanine replaces ten of them. Grounds are interleaved between signal groups rather than grouped at one end, because a 60-pin connector with no local return is the worst discontinuity on the board. | `check_fmu_schematic :: nets span sheets` | V |
| HWR-MFG-005 | The isolated CAN shall NOT cross the mezzanine. | A 0.5 mm pitch connector gives ~0.5 mm creepage between adjacent contacts. Running CAN1_H/L beside board-referenced signals would silently reduce the isolation barrier to that gap and undo the ISOW1044. CAN keeps dedicated connectors on the isolated side. | `check_fmu_objective :: isolated side has its own supply` | V |
| HWR-MFG-006 | The microSD socket shall sit on a board edge. | A card slot in the middle of a board is a card that cannot be changed without dismantling the aircraft. Aligned by courtyard, not origin — placing a 15 mm deep socket by its origin hangs it off the board. | `check_fmu_placement :: edge-mounted part(s) reach a board edge` | V |
| HWR-MFG-007 | Sensitive parts shall clear every switching source by a stated distance. | "Keep the sensors away from the noise" is untestable as written. Each sensitive part has a minimum distance with the mechanism that justifies it — 25 mm for the magnetometer because it measures exactly what a converter emits, 15 mm for the IMUs and barometers because thermal gradient shows up as gyro bias and altitude error, 10 mm for the crystals. Judgement, not datasheet numbers, and stated as such. | `check_fmu_placement :: sensitive parts clear of noise sources` | V |

---

## Requirements not yet written

Deliberately listed rather than omitted, because an incomplete matrix that
looks complete is the failure mode this whole directory exists to avoid:

- Component derating and worst-case analysis. None.
- Thermal analysis. The TPS62132 and the ISOW1044s are the candidates.
- Signal integrity for USB and CAN FD — impedance control, length matching.
- Manufacturing test and acceptance criteria.
- Part obsolescence and procurement control (AC 20-152A COTS-1…COTS-8).
