# JFOXGroundControl: roadmap, not implementation

This document is a sequencing plan for a possible future custom ground
control station ("JFOXGroundControl") speaking a custom secure datalink
("JFOXLink"), instead of MAVLink. **No code for either exists anywhere in
this repository today.** This is deliberately scoped as planning, not a
build - see "Why not now" below.

## Current state (as of this writing)

- **MAVLink** (see `BUILD_AND_FLASH.md` and `telemetry::mavlink`) is real,
  working, and lets Mission Planner/QGroundControl connect to
  `jfox-fcu-usb` today. It is explicitly an interim bridge, not this
  project's long-term GCS link.
- **JFOXLink** - a MAVLink-derived secure datalink concept (dual-redundant
  RF channels, AES-256-GCM session encryption, ECDH key exchange,
  FHSS/DSSS anti-jamming) - has only ever been discussed via
  skill/reference material in this project's development sessions. It has
  never been scoped against this airframe's real hardware, mission profile,
  or threat model, and no frame codec, crypto, or radio HAL code exists in
  this repo.
- **JFOXGroundControl** - a companion GCS application speaking JFOXLink -
  doesn't exist as a concept beyond its name. It would be a separate
  application outside this Rust firmware workspace entirely (a desktop or
  mobile app, likely its own repository), not something to build inside
  `JFOX-FCU`.

## Why not now

JFOXLink is a materially larger and more consequential project than
anything currently in this repo:

- **Real cryptography**, not a wire-format encoding exercise like
  `telemetry::mavlink` or `common::can_frames`. A session-key/ECDH design
  mistake is not the kind of thing a unit test catches after the fact - it
  needs to be right by design, reviewed against an actual threat model,
  before code is written.
- **A real RF link that doesn't exist yet.** No radio module has been
  chosen for this airframe. Anti-jamming/dual-redundancy design (FHSS
  hop tables, channel arbitration) is meaningless without real hardware
  characteristics (bandwidth, range, regulatory constraints) to design
  against.
- **An undefined threat model.** The jfoxlink-integration reference
  material's own profile matrix (hobbyist / commercial / defense-grade)
  spans a huge range of actual engineering effort. Picking wrong wastes
  work in both directions - over-building crypto/anti-jam for a hobbyist
  airframe, or under-building it for anything that actually needs to resist
  a capable adversary.

Starting implementation before these are pinned down risks the same
mistake this session's MAVLink work explicitly avoided elsewhere: shipping
something that "looks done" but is wrong in a way nobody notices until
someone tries to rely on it.

## Recommended sequencing

1. **Now**: keep `telemetry::mavlink` solid and minimal (see
   `BUILD_AND_FLASH.md`). Its module boundary already keeps the wire-format
   encoding (`encode_heartbeat`/`encode_sys_status`/`encode_attitude`)
   separate from `main_usb.rs`'s loop/state logic - a future JFOXLink
   transport can sit alongside or eventually replace the MAVLink encoder
   without a rewrite of the state-gathering side (`ArmingFsm`/`BitReport`/
   `MadgwickFilter` wiring), as long as that separation is preserved when
   this binary evolves.
2. **A dedicated design pass, before any JFOXLink code**: pin down the
   real requirements this repo doesn't have answers to yet -
   - Which radio hardware will this airframe actually carry (module,
     frequency band, regulatory region)?
   - What real range/link-budget/latency requirements apply to the actual
     mission profile (not a generic "drone" assumption)?
   - What threat model applies - who is JFOXLink defending against, and
     what's the actual cost of a compromise for this specific vehicle/
     mission? This determines whether the answer is "AES-128 and call it
     done" or genuinely defense-grade dual-channel FHSS/DSSS.
   These are product/mission decisions, not implementation details -
   answering them is what unblocks a real design, not more research into
   MAVLink internals.
3. **Then**: implement JFOXLink's firmware-side stack as its own phased
   effort - frame codec first (host-testable, following this codebase's
   `common::can_frames`/`telemetry::mavlink` pattern of pure, testable wire
   logic), then the session/key-exchange state machine, then the radio HAL
   - each phase verified the way this codebase verifies everything else
   (host unit tests, SITL where applicable, then real hardware) before the
   next phase starts, not implemented all at once and debugged as a whole.
4. **Then**: JFOXGroundControl itself. A separate application, separate
   repository, built once there's a real JFOXLink implementation on the
   firmware side to actually talk to - building a GCS app against a
   not-yet-final protocol is how both ends drift out of sync.

## What would change this timeline

If the user has a specific near-term need (a real mission with a real
deadline that needs JFOXLink specifically, not MAVLink) or already has
answers to the design-pass questions above (radio hardware already chosen,
threat model already clear), steps 2-3 could start immediately rather than
waiting - this sequencing assumes those answers don't exist yet, based on
nothing beyond a name and a skill reference having been discussed so far.
