#!/usr/bin/env python3
"""Generate the JFOX-BASE-v1 board: 100 x 80 mm, eight layers, three channels.

Compact and noise-robust pull against each other. Lateral separation is the
cheap way to control coupling and a 100 x 80 board has none to spend, so the
separation is bought in the STACKUP instead - see
hardware/jfox-base-v1/STACK_ARCHITECTURE.md section 2a.

The reason this matters more here than on the module: if channel A's noise
corrupts channel B's data, the two channels are no longer independent, and
two channels failing together is the exact case triple redundancy exists to
prevent. Coupling between channels is a COMMON-CAUSE failure, so isolating
them is a safety requirement rather than a performance one. That changes the
layout rule from "keep noisy away from quiet" to "keep every channel away
from every other channel".

    python hardware/tools/gen_base_pcb.py

Writes hardware/jfox-base-v1/jfox-base.kicad_pcb
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_fmu_pcb as P                 # noqa: E402  helpers, reused as-is

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-base-v1"
SCH = BOARD / "jfox-base.kicad_sch"
OUT = BOARD / "jfox-base.kicad_pcb"

VERSION = 20260206

# Same outline as the module: the stack has no overhang, the four M3 columns
# land on the module's own 84 x 64 mm hole pattern, and the airframe sees one
# rectangular envelope instead of a stepped one.
# 100 wide because that is the card's rear edge. 100 tall because three
# cards at the 18 mm pitch plus panel I/O above and below does not fit in
# 80 - the second power feed, the console and the debug port used up what
# perimeter was left. Still no larger than a card, so the envelope is
# unchanged.
BX, BY, W, H = 30.0, 30.0, 100.0, 100.0
CORNER_R = 2.0
M3_INSET = 8.0

# --------------------------------------------------------------------------
# Eight layers. The module is six; the extra two here are spent entirely on
# reference planes, so that EVERY signal layer is adjacent to solid ground
# and every return current has an unbroken path directly under its own
# trace. That is what makes a compact board quiet - loop area set by the
# 0.1 mm dielectric rather than by how far the return has to detour.
#
# The three ground planes must stay solid. A track routed across one is a
# slot; a slot under a fast edge is a better antenna than any trace, and it
# forces every signal crossing it to share a return path. On this board that
# sharing would be BETWEEN CHANNELS - one careless track on In1 could create
# the common-cause coupling the whole architecture exists to avoid.
# --------------------------------------------------------------------------
LAYERS = """\t(layers
\t\t(0 "F.Cu" signal)
\t\t(1 "In1.Cu" signal "GND1")
\t\t(2 "In2.Cu" signal "CH_A")
\t\t(3 "In3.Cu" signal "GND2")
\t\t(4 "In4.Cu" power "PWR")
\t\t(5 "In5.Cu" signal "CH_B")
\t\t(6 "In6.Cu" signal "GND3")
\t\t(31 "B.Cu" signal "CH_C")
\t\t(32 "B.Adhes" user "B.Adhesive")
\t\t(33 "F.Adhes" user "F.Adhesive")
\t\t(34 "B.Paste" user)
\t\t(35 "F.Paste" user)
\t\t(36 "B.SilkS" user "B.Silkscreen")
\t\t(37 "F.SilkS" user "F.Silkscreen")
\t\t(38 "B.Mask" user)
\t\t(39 "F.Mask" user)
\t\t(40 "Dwgs.User" user "User.Drawings")
\t\t(41 "Cmts.User" user "User.Comments")
\t\t(42 "Eco1.User" user "User.Eco1")
\t\t(43 "Eco2.User" user "User.Eco2")
\t\t(44 "Edge.Cuts" user)
\t\t(45 "Margin" user)
\t\t(46 "B.CrtYd" user "B.Courtyard")
\t\t(47 "F.CrtYd" user "F.Courtyard")
\t\t(48 "B.Fab" user)
\t\t(49 "F.Fab" user)
\t)"""

SETUP = """\t(setup
\t\t(pad_to_mask_clearance 0.05)
\t\t(solder_mask_min_width 0.1)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(grid_origin {gx} {gy})
\t)"""

# --------------------------------------------------------------------------
# Placement. Each channel owns a region, and the regions do not interleave -
# a channel's connector, its fuse and its optical front end sit together so
# that its currents stay inside its own area rather than sharing a return
# with a neighbour.
#
# The three mezzanine headers sit in a row across the middle. Each one is
# reached by its own riser card from the module above, and each riser is
# clamped by the standoff column beside it (STACK_ARCHITECTURE.md s4) - a
# connector is not a mechanical mount, and a card held only by its two
# connectors works loose under DO-160G section 8 vibration.
# --------------------------------------------------------------------------
FIXED_EDGE = {
    # Company mark. board_only, so it carries no pads, no
    # reference on the assembly drawing and nothing in the
    # BOM - it is artwork, and the checkers that count
    # components should not see it as one.
    "G1":  ("XY", (6.0, 92.0), "F"),   # JFOX logo, bottom edge, below the slot column

    # --- the three card slots ---------------------------------------------
    # A COLUMN up the middle of the backplane, at the 18 mm card pitch. The
    # cards plug in edge-on and project forward, so their spacing here IS
    # their spacing in the airframe - these three numbers set the stack.
    #
    # Each is an independent connector. A bent contact in slot 2 costs
    # channel B and nothing else; on a shared pass-through bus the same
    # fault costs all three and leaves the voter nothing to vote on.
    "J1":  ("XY", (28.4, 20.0), "F"),          # slot A, top
    "J2":  ("XY", (28.4, 46.0), "F"),          # slot B, middle
    "J3":  ("XY", (28.4, 72.0), "F"),          # slot C, bottom

    # --- top edge: vehicle I/O --------------------------------------------
    "J90": ("N", 20.5, "F"),                   # GPS1
    "J91": ("N", 36.3, "F"),                   # RC in
    "J92": ("N", 49.6, "F"),                   # telem 1
    "J93": ("N", 63.5, "F"),                   # telem 2
    "J70": ("N", 76.7, "F"),                   # vehicle CAN

    # --- right edge: fibre #1, then the status LEDs -----------------------
    # Fibre optic I/O #1 is the right-hand channel in the sketch, and the
    # three channel LEDs sit below it where a technician looking at the
    # right-hand face can see them.
    "U50": ("E", 28.2, "F"),                   # OPT1 transmit
    "U51": ("E", 52.2, "F"),                   # OPT1 receive
    "J80": ("E", 82.0, "F"),                   # actuator A

    # --- left edge: fibre #2 ----------------------------------------------
    # The two optical channels stay on OPPOSITE faces. They exist to survive
    # each other's loss, and two connectors 20 mm apart share every
    # localised hazard there is - one impact, one chafed loom, one hot
    # bracket. Opposite faces costs nothing and removes that.
    "U52": ("W", 28.2, "F"),                   # OPT2 transmit
    "U53": ("W", 52.2, "F"),                   # OPT2 receive
    "J81": ("W", 82.0, "F"),                   # actuator B

    # --- bottom edge: power, debug, console -------------------------------
    # The two airframe feeds go to opposite bottom corners, RH and LH, as
    # drawn. Separating them is the point: two feeds entering side by side
    # would share whatever damages one of them.
    "J51": ("S", 20.5, "F"),                   # power supply 2 (LH)
    "J52": ("S", 40.0, "F"),                   # debug
    "J54": ("S", 56.0, "F"),                   # console USB-C
    "J82": ("S", 70.0, "F"),                   # actuator C
    "J50": ("S", 84.0, "F"),                   # power supply 1 (RH)
}


# Per-channel regions for everything not anchored. Named by channel so the
# packer cannot put channel A's fuse inside channel C's area.
ZONES = {
    # Per-channel regions beside each card slot, so a channel's fuse and
    # its status LED sit next to the connector they belong to rather than
    # being packed wherever there was room. Keeping a channel's currents
    # inside its own area is what stops one channel's noise appearing on
    # another's return - which on a TMR board is a common-cause failure,
    # not a signal-integrity nuisance.
    "CH_A":  (15.0, 16.0, 27.0, 30.0),
    "CH_B":  (15.0, 42.0, 27.0, 56.0),
    "CH_C":  (15.0, 68.0, 27.0, 82.0),
    # CAN harness landings, in the column beside the slots.
    "CAN":   (73.0, 16.0, 85.0, 82.0),
    # Bottom side: expansion headers and the fibre decoupling. Kept inboard
    # of the optical housings, which are THROUGH-HOLE - their pins occupy
    # every layer, so a bottom-side part under one collides even though
    # they are on opposite faces.
    "EXP":   (26.0, 30.0, 74.0, 44.0),
    # The ORing stage: controller, four pass FETs, six dividers, two caps.
    "ORING": (26.0, 56.0, 74.0, 70.0),
}


ZONE_OF = [
    (r'^(F1|R1|C1|R60|D1)$',  "CH_A", "F"),
    (r'^(F2|R2|C2|R61|D2)$',  "CH_B", "F"),
    (r'^(F3|R3|C3|R62|D3)$',  "CH_C", "F"),
    (r'^J6[0-5]$|^R4[01]$',   "CAN",  "F"),
    (r'^D5[01]$',             "ORING", "F"),  # feed reverse-polarity diodes
    (r'^U20$|^Q[12][AB]$',    "ORING", "F"),  # LTC4417 and its pass FETs
    (r'^R7[0-5]$|^C7[01]$',   "ORING", "B"),  # thresholds and bypass
    (r'^C5[01]$',             "EXP",  "B"),
    (r'^J10[012]$',           "EXP",  "B"),
]


NETCLASSES = [
    ("Default", 0.20, 0.15, 0.6, 0.3, 0, 0, []),
    # The channel classes exist to make the isolation auditable. A signal in
    # class CH_A that ends up beside one in CH_B is visible as a rule
    # violation rather than as a coupling nobody measured.
    ("CH_A", 0.25, 0.20, 0.6, 0.3, 0, 0, []),
    ("CH_B", 0.25, 0.20, 0.6, 0.3, 0, 0, []),
    ("CH_C", 0.25, 0.20, 0.6, 0.3, 0, 0, []),
    ("Power", 0.60, 0.25, 0.8, 0.4, 0, 0, []),
    ("HighCurrent", 1.00, 0.30, 1.0, 0.5, 0, 0, []),
    ("CAN", 0.25, 0.20, 0.45, 0.25, 0.25, 0.20,
     ["CAN1_H", "CAN1_L", "CAN2_H", "CAN2_L"]),
]

RULES = dict(P.RULES)


def zone_for(ref):
    for pat, zone, side in ZONE_OF:
        if re.match(pat, ref):
            return zone, side
    return None, "B"


def write_netclasses():
    """Net classes and constraints into the .kicad_pro, where KiCad reads.

    Not into the board's (setup): KiCad 10 rejects both (rules ...) and
    (net_class ...) there and refuses to load the file entirely.
    """
    pro = BOARD / "jfox-base.kicad_pro"
    doc = json.loads(pro.read_text(encoding="utf-8")) if pro.exists() else {}

    # Channel membership is derived from the net name prefix the schematic
    # already enforces, so the classes cannot drift from the netlist.
    patterns = [{"netclass": f"CH_{c}", "pattern": f"/^{c}_.*$/"}
                for c in ("A", "B", "C")]
    patterns += [{"netclass": "HighCurrent", "pattern": "/^.*VDD_BRICK$/"},
                 {"netclass": "HighCurrent", "pattern": "/^.*VDD_SERVO$/"},
                 {"netclass": "HighCurrent", "pattern": "VBAT_IN"}]

    doc["net_settings"] = {
        "meta": {"version": 4},
        "classes": [
            {"name": n, "clearance": cl, "track_width": w,
             "via_diameter": v, "via_drill": vd,
             "diff_pair_width": dw or 0.2, "diff_pair_gap": dg or 0.25,
             "diff_pair_via_gap": 0.25, "microvia_diameter": 0.3,
             "microvia_drill": 0.1, "wire_width": 6, "bus_width": 12,
             "line_style": 0, "pcb_color": "rgba(0, 0, 0, 0.000)",
             "schematic_color": "rgba(0, 0, 0, 0.000)"}
            for n, w, cl, v, vd, dw, dg, _ in NETCLASSES
        ],
        "net_colors": None,
        "netclass_assignments": {
            n: [name] for name, _, _, _, _, _, _, nets in NETCLASSES
            for n in nets},
        "netclass_patterns": patterns,
    }
    doc.setdefault("board", {}).setdefault("design_settings", {})
    doc["board"]["design_settings"]["rules"] = dict(RULES)
    doc.setdefault("meta", {"filename": pro.name, "version": 1})
    pro.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return len(NETCLASSES)


def main():
    # Reuse the module generator's machinery, pointed at this board.
    P.BOARD, P.SCH, P.OUT = BOARD, SCH, OUT
    P.BX, P.BY, P.W, P.H = BX, BY, W, H
    P.CORNER_R, P.M3_INSET = CORNER_R, M3_INSET
    P.LAYERS, P.SETUP = LAYERS, SETUP
    P.ZONES, P.ZONE_OF, P.FIXED_EDGE = ZONES, ZONE_OF, FIXED_EDGE
    P.NETCLASSES, P.RULES = NETCLASSES, RULES
    P.zone_for = zone_for
    P.write_netclasses = write_netclasses
    # No single part dominates this board the way the MCU dominates the
    # module, so nothing is anchored at the centre.
    P.MCU_CENTRE = None
    P.BARE_PN = "1102"
    P.PN_AT = (33.0, 35.5)     # 8.9 mm clear on this board          # this board's bare-board number
    P.main()


if __name__ == "__main__":
    main()
