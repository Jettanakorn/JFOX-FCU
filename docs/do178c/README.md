# DO-178C alignment materials — read this first

## What this directory is

Engineering artifacts modeled on specific DO-178C objectives — traceable
requirements, a coding standard, and structural coverage reporting — applied
to JFOX-FCU as it exists today. They are useful groundwork if this project
ever pursues real certification, and they raise the rigor of development
right now.

## What this directory is NOT

**This is not DO-178C compliance, and nothing in this directory should be
represented as such to a certification authority, a customer, or anyone
making a safety decision about flying this software.** DO-178C is a
certification process tied to an actual airworthiness approval, not a set of
documents a codebase can contain. Compliance requires things no engineering
session (human or AI) produces by writing artifacts:

- **A Design Assurance Level derived from an actual safety assessment**
  (ARP4754A / ARP4761 functional hazard assessment), not asserted. The
  project's current direction is DAL A (Catastrophic) — see the note below on
  why that warrants a real hazard assessment, not this document, as its
  basis.
- **Independence.** Above DAL D, DO-178C requires verification independent
  of development — different people, not the same engineer (or the same AI
  session) writing the code and then certifying it's correct. Every artifact
  in this directory was produced in the same sessions that wrote the code it
  describes.
- **A Plan for Software Aspects of Certification (PSAC)** agreed with the
  certification authority (FAA/EASA) before development, plus the full
  planning suite (SDP, SVP, SCMP, SQAP) - none of which exist here.
- **MC/DC structural coverage**, the DAL A requirement - substantially more
  than the statement/branch coverage `docs/do178c/COVERAGE_REPORT.md`
  reports. See that document for exactly what gap remains.
- **Certification liaison** with an actual authority or a Designated
  Engineering Representative - an organizational and regulatory
  relationship, not an engineering artifact.
- **A software baseline mature enough to certify.** JFOX-FCU has never flown,
  carries placeholder/unvalidated control gains throughout (see
  `firmware/src/main.rs`'s tuning constants), and has known incomplete
  safety-relevant paths (no RC/command link yet, `TmrVoter`'s output not yet
  wired into `motor_task`'s final gate - see `HARDWARE_BRINGUP.md`).

## On the DAL A target specifically

DAL A (Catastrophic failure condition - the level applied to primary flight
control computers on transport-category aircraft) was given as this
project's target. Worth being direct about: a small quad-X UAV with no
position control, flying under a UAS regulatory framework rather than
transport-category type certification, would typically land at DAL C or D
based on the actual severity of its credible failure conditions - DAL A is
usually reserved for failures that can cause hull loss with multiple
fatalities. Whether DAL A is genuinely the right target here is a question
for an actual functional hazard assessment against this vehicle's real
operational context, not an engineering-time default. The requirements and
coding-standard work in this directory is written to be useful regardless of
which level is ultimately correct; the coverage gap analysis specifically
flags what additional work DAL A (vs. C/D) would demand.

## What's in this directory

| File | DO-178C objective it's aligned with |
|---|---|
| `SOFTWARE_REQUIREMENTS.md` | Software requirements process (traceable, verifiable requirements) |
| `TRACEABILITY_MATRIX.md` | Requirements-to-code-to-test bidirectional traceability |
| `CODING_STANDARD.md` | Software Coding Standards (SCS) |
| `COVERAGE_REPORT.md` | Structural coverage analysis |

## Current scope

Covers the `flight` crate (the portable, host-testable control/safety logic)
and the `firmware` crate's task-level orchestration. Does not cover `hal`,
`bsp`, or `drivers` (embedded-only, unverified beyond "compiles for the
target" - see the project's own prior analysis for why that matters) or
`math` in detail beyond what `flight`'s requirements depend on.
