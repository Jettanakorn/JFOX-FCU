# DO-254 alignment materials — read this first

## What this directory is

Engineering artifacts modelled on specific DO-254 objectives — traceable
hardware requirements, and verification evidence that is executed rather than
asserted — applied to the JFOX-FMU v1 board as it exists today. Useful
groundwork if this project ever pursues real certification, and it raises the
rigour of the hardware work right now.

It is the hardware counterpart to `docs/do178c/`, and it carries the same
disclaimer, for the same reasons.

## What this directory is NOT

**This is not DO-254 compliance, and nothing here should be represented as
such to a certification authority, a customer, or anyone making a safety
decision about flying this hardware.** DO-254 is a design assurance process
tied to an actual airworthiness approval. Compliance requires things no
engineering session produces by writing documents:

- **A DAL derived from a real safety assessment** (ARP4754A / ARP4761
  functional hazard assessment and PSSA), not asserted. See the note on DAL A
  below.
- **Independence.** The same session that designed this board wrote every
  check that verifies it. DO-254 expects verification independent of design at
  DAL A/B.
- **A PHAC** (Plan for Hardware Aspects of Certification) agreed with the
  authority *before* development, plus the planning suite — hardware design
  plan, validation and verification plan, configuration management plan,
  process assurance plan. None exist.
- **Process assurance and configuration management** as auditable
  organisational functions, not a git history.
- **Certification liaison** with an authority or DER.
- **A design mature enough to certify.** This board has never been fabricated.
  It has no connectors yet, the LTC4417's under/over-voltage thresholds are
  unset, and the fibre-optic actuator links its own objective requires do not
  exist. See "Known gaps" below.

## The scoping point that matters most

**DO-254's core is about custom devices. This board has none.**

DO-254 and AC 20-152A distinguish *custom devices* (ASICs, PLDs, FPGAs — the
things whose internal logic the applicant designs) from *COTS devices* and
*circuit board assemblies*. JFOX-FMU v1 is a CBA populated entirely with COTS
parts: an STM32H753, three COTS IMUs, two COTS barometers, COTS regulators and
isolators. There is no FPGA, no ASIC, no custom micro-coded component.

That changes what applies, considerably:

| Category | What it needs | Present here? |
|---|---|---|
| Complex custom devices | DO-254 App. A + AC 20-152A **CD-1…CD-12** | none on this board |
| COTS IP | AC 20-152A **IP-1…IP-7** | none |
| COTS devices | AC 20-152A **COTS-1…COTS-8** | **every active part** |
| Circuit board assembly | AC 20-152A CBA guidance | **this board** |

So the work that dominates a typical DO-254 DAL A programme — elemental
analysis, the Appendix B advanced verification methods, HDL design assurance —
targets devices this board does not contain. What genuinely applies here is
the **COTS objectives and the CBA guidance**, and those are mostly about
selection justification, procurement control, and showing that the *use* of
each part is appropriate and verified.

Note also that AC 20-152A adds **29 objectives beyond DO-254 itself**. An
applicant following DO-254 under AC 20-152A must satisfy those too.

## On the DAL A target specifically

DAL A is the level applied to hardware whose failure is catastrophic. Being
direct, as `docs/do178c/README.md` already is for software: a small UAV under
a UAS regulatory framework would typically land at DAL C or D on the actual
severity of its credible failure conditions. Whether DAL A is right here is a
question for a functional hazard assessment against this vehicle's real
operational context.

**But the harder problem for DAL A on this board is not process — it is the
COTS microcontroller.** ST does not supply a DO-254 data package for the
STM32H753. Getting a COTS device of that complexity accepted at DAL A means
demonstrating either extensive relevant service experience or sufficient
*architectural* mitigation that no single device failure is catastrophic.

That second path is the one this design is actually built for, and it is worth
stating plainly because it is the strongest DO-254 argument the project has:

- **Board-level TMR** — three independent FMUs voting, so no single board,
  and therefore no single STM32, is a catastrophic single point.
- **Sensor-level redundancy with vendor dissimilarity** — three IMUs from two
  vendors, two barometers from two vendors. A vendor-wide errata cannot take
  the whole attitude solution.
- **Fault containment** — each IMU on its own SPI bus and its own switchable
  rail, so a wedged sensor is recoverable without disturbing the others.
- **Prioritised power ORing** with per-input under/over-voltage lockout.
- **Galvanic isolation** on the off-board I/O, so external faults are barrier
  events rather than board failures.
- **Redundant Cyphal/CAN** on two independent controllers and isolated buses.

Architecture, not component pedigree, is where a DAL A case for this board
would have to be made.

## What is actually here

`HARDWARE_REQUIREMENTS.md` — hardware requirements with stable IDs, each
naming the verification that demonstrates it.

The verification is not prose. Each requirement names a check in
`hardware/tools/` that runs against the exported netlist and either passes or
fails. `check_hw_traceability.py` executes the matrix: it fails if a
requirement cites a check that does not exist, if a check does not pass, or if
a check exists that no requirement claims. That last one matters — it stops
the matrix drifting into decoration.

## Known gaps, as of this writing

These are design gaps, not documentation gaps, and the objective checker
reports them on every run:

- **Fibre-optic actuator links do not exist.** Required by the board's own
  objective; roughly 960 mA of transmitter current against a 550 mA peak
  budget, so the power architecture has to be redone with them.
- **No connectors.** Around 60 nets terminate in isolated labels.
- **LTC4417 UV/OV thresholds unset** — those nets go nowhere, so the ORing
  controller has no configured trip points.
- **No no-connect flags** on ~88 deliberately unallocated GPIO.
- **Never fabricated, never tested.** Every claim in this directory is about a
  design, not a board.

## References

- RTCA DO-254 / EUROCAE ED-80, *Design Assurance Guidance for Airborne
  Electronic Hardware*
- FAA AC 20-152A, *Development Assurance for Airborne Electronic Hardware*
- EASA AMC 20-152A
- ARP4754A / ARP4761 for the hazard assessment this document does not replace
