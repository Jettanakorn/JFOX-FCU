#!/usr/bin/env python3
"""Generate the 3-board TMR KiCad project.

Emits, into hardware/:
  jfox-tmr.kicad_pro    project
  jfox-tmr.kicad_sch    root - three FMU sheet instances + the carrier sheet
  fmu-v2.kicad_sch      FMU board interface (placeholder until the Eagle import)
  carrier.kicad_sch     the new carrier/backplane design

Why generated rather than drawn: the carrier is mostly repetition across three
identical boards, and the pin/net facts come from
hardware/PX4FMUv2.4.5_NETS.md, which is itself derived from the FMU board's
Eagle netlist. Generating keeps the two in step and makes a correction a
one-line edit rather than 60 hand-placed labels.

Format target is KiCad 7 (version 20230819), matched against real
KiCad-emitted files in the KiCad repo's own qa/data/eeschema test set rather
than written from the format documentation alone - the docs disagree with
shipped files on at least one detail (they say the sheet properties are
"Sheet name"/"Sheet file"; real files use "Sheetname"/"Sheetfile"). KiCad 8
and 9 open this and upgrade it in place.

Run:
  python hardware/tools/gen_tmr_schematic.py
"""

import json
import re
import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware"
PROJECT = "jfox-tmr"

BOARDS = ["A", "B", "C"]

# Per-board signals: these must NOT be shared between the three FMU instances,
# so they cross the sheet boundary as hierarchical pins.
PER_BOARD = (
    [("VDD_5V_BRICK", "passive"), ("BATT_V_SENS", "output"), ("BATT_I_SENS", "output")]
    # FMU_CH* deliberately absent: motor-output arbitration is unresolved
    # (TmrVoter is not wired into motor_task), so it is not committed to copper.
)

# Genuinely shared across all three boards - these ride global labels, which is
# correct precisely because every board really is on the same net.
SHARED = [("CAN_H", "bidirectional"), ("CAN_L", "bidirectional"),
          ("GND", "passive"), ("SAFETY", "input")]

MM = 2.54


def uid():
    return str(_uuid.uuid4())


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def effects(justify=None, hide=False):
    parts = ["(font (size 1.27 1.27))"]
    if justify:
        parts.append(f"(justify {justify})")
    if hide:
        parts.append("hide")
    return "(effects " + " ".join(parts) + ")"


def hier_label(name, shape, x, y, angle=0):
    return (f'  (hierarchical_label "{esc(name)}" (shape {shape}) (at {x} {y} {angle})\n'
            f'    {effects("left")}\n'
            f'    (uuid {uid()})\n'
            f'  )')


def global_label(name, shape, x, y, angle=0):
    return (f'  (global_label "{esc(name)}" (shape {shape}) (at {x} {y} {angle}) (fields_autoplaced)\n'
            f'    {effects("left")}\n'
            f'    (uuid {uid()})\n'
            f'  )')


def local_label(name, x, y, angle=0):
    return (f'  (label "{esc(name)}" (at {x} {y} {angle})\n'
            f'    {effects("left bottom")}\n'
            f'    (uuid {uid()})\n'
            f'  )')


def no_connect(x, y):
    """Marks a pin as deliberately unused, so ERC does not report it."""
    return f'  (no_connect (at {x} {y}) (uuid {uid()}))'


def wire(x1, y1, x2, y2):
    return (f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n'
            f'    (stroke (width 0) (type default))\n'
            f'    (uuid {uid()})\n'
            f'  )')


def text_note(body, x, y):
    return (f'  (text "{esc(body)}" (at {x} {y} 0)\n'
            f'    {effects("left top")}\n'
            f'    (uuid {uid()})\n'
            f'  )')


def sheet(name, filename, x, y, w, h, pins, root_uuid, page, sheet_uuid):
    """A hierarchical sheet instance. `pins` is [(name, shape)].

    `sheet_uuid` is allocated by the caller, because symbols living inside the
    referenced file need it to build their own instance paths - the two have to
    agree or KiCad cannot place the symbol in the hierarchy.
    """
    out = [f'  (sheet (at {x} {y}) (size {w} {h}) (fields_autoplaced)',
           '    (stroke (width 0.1524) (type solid))',
           '    (fill (color 0 0 0 0.0000))',
           f'    (uuid {sheet_uuid})',
           f'    (property "Sheetname" "{esc(name)}" (at {x} {round(y - 0.7116, 4)} 0)',
           f'      {effects("left bottom")}',
           '    )',
           f'    (property "Sheetfile" "{esc(filename)}" (at {x} {round(y + h + 0.5846, 4)} 0)',
           f'      {effects("left top")}',
           '    )']
    py = y + MM
    for pname, shape in pins:
        out.append(f'    (pin "{esc(pname)}" {shape} (at {x} {round(py, 4)} 180)')
        out.append(f'      {effects("right")}')
        out.append(f'      (uuid {uid()})')
        out.append('    )')
        py += MM
    out.append('    (instances')
    out.append(f'      (project "{PROJECT}"')
    out.append(f'        (path "/{root_uuid}" (page "{page}"))')
    out.append('      )')
    out.append('    )')
    out.append('  )')
    return "\n".join(out)


def conn_symbol_def(npins):
    """A generic N-pin connector symbol, generated rather than pulled from a
    KiCad library so the file is self-contained and its pin geometry is known
    exactly (labels have to land on pin endpoints)."""
    name = f"jfox:Conn_01x{npins:02d}"
    bottom = -MM * (npins - 1) - MM
    out = [f'    (symbol "{name}" (pin_names (offset 1.016) hide) (in_bom yes) (on_board yes)',
           f'      (property "Reference" "J" (at 0 {MM} 0)',
           f'        {effects()}',
           '      )',
           f'      (property "Value" "Conn_01x{npins:02d}" (at 0 {round(bottom - 1.27, 4)} 0)',
           f'        {effects()}',
           '      )',
           f'      (property "Footprint" "" (at 0 0 0)',
           f'        {effects(hide=True)}',
           '      )',
           f'      (property "Datasheet" "~" (at 0 0 0)',
           f'        {effects(hide=True)}',
           '      )',
           f'      (symbol "Conn_01x{npins:02d}_1_1"',
           f'        (rectangle (start -1.27 {round(MM * 0.5, 4)}) (end 1.27 {round(bottom + 1.27, 4)})',
           '          (stroke (width 0.254) (type default))',
           '          (fill (type background))',
           '        )']
    for i in range(1, npins + 1):
        py = -MM * (i - 1)
        out.append(f'        (pin passive line (at -5.08 {round(py, 4)} 0) (length 3.81)')
        out.append(f'          (name "P{i}" {effects()})')
        out.append(f'          (number "{i}" {effects()})')
        out.append('        )')
    out.append('      )')
    out.append('    )')
    return name, "\n".join(out)


# Real KiCad footprints, so the carrier can go straight to a board. The DF13
# parts match what the FMU modules actually carry (see
# PX4FMUv2.4.5_NETS.md); the servo breakout is plain 0.1" header, which is
# what RC servo/ESC leads plug into.
FOOTPRINTS = {
    3: "Connector_Hirose:Hirose_DF13-03P-1.25DSA_1x03_P1.25mm_Vertical",
    4: "Connector_Hirose:Hirose_DF13-04P-1.25DSA_1x04_P1.25mm_Vertical",
    6: "Connector_Hirose:Hirose_DF13-06P-1.25DSA_1x06_P1.25mm_Vertical",
    8: "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
}


def place_conn(lib_id, ref, value, x, y, npins, inst_path, project=None):
    """Place a connector. Returns (sexpr, [(pin_index, abs_x, abs_y)]).

    `inst_path` is the hierarchy path to the sheet this symbol sits on:
    "/<root-document-uuid>/<sheet-element-uuid-in-the-root>". Not the
    containing file's own uuid - that was the first version of this and KiCad
    responded by attributing every carrier symbol to the root sheet.

    Library +Y is up, schematic +Y is down, so library pin y maps to
    schematic y - lib_y. Getting this backwards silently puts every label on
    the wrong pin, which no amount of paren-checking would catch.
    """
    out = [f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)',
           '    (in_bom yes) (on_board yes) (fields_autoplaced)',
           f'    (uuid {uid()})',
           f'    (property "Reference" "{esc(ref)}" (at {round(x + 2.54, 4)} {round(y - 2.54, 4)} 0)',
           f'      {effects("left")}',
           '    )',
           f'    (property "Value" "{esc(value)}" (at {round(x + 2.54, 4)} {round(y, 4)} 0)',
           f'      {effects("left")}',
           '    )',
           f'    (property "Footprint" "{esc(FOOTPRINTS[npins])}" (at {x} {y} 0)',
           f'      {effects(hide=True)}',
           '    )',
           '    (instances',
           f'      (project "{project or PROJECT}"',
           f'        (path "{inst_path}"',
           f'          (reference "{esc(ref)}") (unit 1)',
           '        )',
           '      )',
           '    )',
           '  )']
    pts = [(i, round(x - 5.08, 4), round(y + MM * (i - 1), 4))
           for i in range(1, npins + 1)]
    return "\n".join(out), pts


def document(root_uuid, lib_defs, body, page_one=True):
    libs = "\n".join(lib_defs) if lib_defs else ""
    return (f'(kicad_sch (version 20230819) (generator eeschema)\n\n'
            f'  (uuid {root_uuid})\n\n'
            f'  (paper "A3")\n\n'
            f'  (lib_symbols\n{libs}\n  )\n\n'
            + "\n".join(body) + "\n\n"
            + ('  (sheet_instances\n    (path "/" (page "1"))\n  )\n' if page_one else '')
            + ')\n')


# --------------------------------------------------------------------------
# sheets
# --------------------------------------------------------------------------

def build_fmu_sheet():
    """FMU board interface.

    Placeholder: real contents arrive via KiCad's File > Import > Non-KiCad
    Schematic on hardware/vendor/PX4FMUv2.4.5.sch. What this file fixes now is
    the *interface* - the exact set of hierarchical pins the root wires to -
    so the project is openable and ERC-able before the import happens, and so
    the import has a defined boundary to be wired into.
    """
    ru = uid()
    body = []
    body.append(text_note(
        "PX4FMUv2.4.5 - PLACEHOLDER.\\n"
        "Replace this sheet's contents with the real board via\\n"
        "File > Import > Non-KiCad Schematic on\\n"
        "hardware/vendor/PX4FMUv2.4.5.sch (Eagle 7.1.0, 421 parts, 12 sheets),\\n"
        "then attach the hierarchical labels below to the matching connectors:\\n"
        "  CAN_H/CAN_L -> J405 pins 2/3   VDD_5V_BRICK -> J601 pins 1/2\\n"
        "  BATT_V_SENS -> J601 pin 4      BATT_I_SENS  -> J601 pin 3\\n"
        "  SAFETY      -> J702 pin 3\\n"
        "This sheet is instantiated three times; edit it once.",
        25.4, 25.4))

    y = 76.2
    for name, shape in PER_BOARD:
        body.append(hier_label(name, shape, 50.8, y))
        y += MM * 2
    y = 76.2
    for name, shape in SHARED:
        body.append(global_label(name, shape, 152.4, y))
        y += MM * 2
    return ru, document(ru, [], body, page_one=False)


def build_carrier(root_uuid, sheet_uuid, standalone=False):
    """The carrier: CAN bus hub + per-board power pass-through.

    Two outputs from one definition:

    * as a child sheet of jfox-tmr (standalone=False) - the system view, where
      signals leaving the carrier are hierarchical labels wired to the FMU
      sheets;
    * as its own project root (standalone=True) - the *board*. The three FMU
      modules are separately manufactured hardware, not parts on this PCB, so
      the carrier has to be its own project, or a board netlist would try to
      place 421 module components on the carrier.

    Design note - why every signal has an IN and an OUT connector:
    the first version of this gave each board a single power connector, which
    read fine as a system sheet (the net continued into the FMU sheet) but left
    28 nets terminating on one pin once the carrier stood alone. A pass-through
    carrier is exactly that - a path - so brick power enters on one connector
    and leaves for the module on another.

    Deliberately NOT on this board:

    * Servo/PWM breakout. How three boards' motor commands arbitrate into one
      output is unresolved - flight::redundancy::TmrVoter is still not wired
      into motor_task. Committing a guess to copper is worse than leaving each
      module's J901 cabled straight to its ESCs.
    * The safety switch. J702's SAFETY lands on U801.PB5, the IO co-processor,
      which this project's FMU-only firmware never runs; and neither J405 nor
      J601 carries a pin to route it through. It would be decorative.
    """
    ru = uid()
    inst = "/" if standalone else f"/{root_uuid}/{sheet_uuid}"
    proj = "carrier" if standalone else PROJECT

    def boundary(name, shape, x, y, angle=0):
        return (local_label(name, x, y, angle) if standalone
                else hier_label(name, shape, x, y, angle))

    lib4, def4 = conn_symbol_def(4)
    lib6, def6 = conn_symbol_def(6)
    body = []

    body.append(text_note(
        "JFOX TMR carrier.\\n"
        "Three PX4FMUv2.4.5 modules stacked on M3 + Richco R908-5 (7.95mm) spacers,\\n"
        "cabled to this board through their existing DF13 connectors.\\n"
        "Mounting pattern is 30.0 x 30.0 mm, taken from the module's own .brd file.",
        25.4, 20.32))

    # --- CAN bus -----------------------------------------------------------
    body.append(text_note(
        "CAN1 BUS - daisy chain, NOT a star. Keep every stub short.\\n"
        "NO TERMINATION ON THIS BOARD. Each module carries R409, a fixed 120R\\n"
        "across CAN_H/CAN_L with no disable jumper (RC0402FR-07120RL, verified\\n"
        "from the FMU netlist). Three unmodified modules = 3x120R in parallel\\n"
        "= ~40R, a real signal-integrity fault.\\n"
        "REQUIRED: desolder R409 on the electrically-middle module only.\\n"
        "Verify ~60R across CAN_H/CAN_L with the bus unpowered before trusting it.",
        25.4, 38.1))

    for i, b in enumerate(BOARDS):
        y = 76.2 + i * 27.94
        s, pts = place_conn(lib4, f"J{i+1}", f"CAN {b} -> module J405",
                            76.2, y, 4, inst, proj)
        body.append(s)
        for idx, px, py in pts:
            body.append(wire(px, py, px - 7.62, py))
            if idx == 2:
                body.append(global_label("CAN_H", "bidirectional", px - 7.62, py, 180))
            elif idx == 3:
                body.append(global_label("CAN_L", "bidirectional", px - 7.62, py, 180))
            elif idx == 4:
                body.append(global_label("GND", "passive", px - 7.62, py, 180))
            else:
                # module's own filtered 5V; nothing on the carrier uses it
                body.append(no_connect(px, py))

    # --- power pass-through ------------------------------------------------
    body.append(text_note(
        "POWER - three INDEPENDENT paths, one per module. Deliberately not commoned:\\n"
        "board-level redundancy is meaningless if one supply can take all three down.\\n"
        "Each module still arbitrates its own inputs internally via LTC4417 (U1101).\\n"
        "Brick in -> module out; the only shared net here is GND.",
        177.8, 38.1))

    for i, b in enumerate(BOARDS):
        y = 76.2 + i * 45.72
        s_in, pts_in = place_conn(lib6, f"J{i+4}", f"BRICK {b} in",
                                  228.6, y, 6, inst, proj)
        s_out, pts_out = place_conn(lib6, f"J{i+7}", f"PWR {b} -> module J601",
                                    292.1, y, 6, inst, proj)
        body += [s_in, s_out]
        nets = {1: f"VBRICK_{b}", 2: f"VBRICK_{b}", 3: f"BATT_I_{b}",
                4: f"BATT_V_{b}", 5: "GND", 6: "GND"}
        for pts, dx in ((pts_in, -7.62), (pts_out, -7.62)):
            for idx, px, py in pts:
                net = nets[idx]
                body.append(wire(px, py, px + dx, py))
                if net == "GND":
                    body.append(global_label("GND", "passive", px + dx, py, 180))
                else:
                    body.append(boundary(net, "passive", px + dx, py, 180))

    return ru, document(ru, [def4, def6], body, page_one=False)

def build_root(ru, fmu_sheet_uuids, carrier_sheet_uuid, fmu_pins, carrier_pins):
    body = []
    body.append(text_note(
        "JFOX-FCU - 3-board TMR system.\\n"
        "FMU-A/B/C are three instances of ONE sheet (fmu-v2.kicad_sch). Editing it\\n"
        "edits all three; KiCad keeps their reference designators distinct via the\\n"
        "per-instance paths. CAN_H/CAN_L/GND/SAFETY are global labels because all\\n"
        "three boards genuinely share those nets. Power and servo signals are\\n"
        "hierarchical pins so each board's stay separate - which is the entire point.",
        25.4, 20.32))

    page = 2
    for i, b in enumerate(BOARDS):
        x = 38.1 + i * 88.9
        y = 76.2
        body.append(sheet(f"FMU-{b}", "fmu-v2.kicad_sch", x, y, 55.88,
                          MM * (len(fmu_pins) + 2), fmu_pins, ru, page,
                          fmu_sheet_uuids[i]))
        py = y + MM
        for pname, _shape in fmu_pins:
            body.append(wire(x, py, x - 7.62, py))
            body.append(local_label(net_for(pname, b), x - 7.62, py, 180))
            py += MM
        page += 1

    y = 190.5
    body.append(sheet("CARRIER", "carrier.kicad_sch", 38.1, y, 76.2,
                      MM * (len(carrier_pins) + 2), carrier_pins, ru, page,
                      carrier_sheet_uuid))
    py = y + MM
    for pname, _shape in carrier_pins:
        body.append(wire(38.1, py, 30.48, py))
        body.append(local_label(pname, 30.48, py, 180))
        py += MM

    return document(ru, [], body, page_one=True)


def net_for(pin_name, board):
    """Map an FMU sheet pin to the carrier-side net name for that board."""
    if pin_name == "VDD_5V_BRICK":
        return f"VBRICK_{board}"
    if pin_name == "BATT_V_SENS":
        return f"BATT_V_{board}"
    if pin_name == "BATT_I_SENS":
        return f"BATT_I_{board}"
    return f"{pin_name}_{board}"


def build_pro(name=PROJECT):
    return json.dumps({
        "board": {"design_settings": {}},
        "meta": {"filename": f"{name}.kicad_pro", "version": 1},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [],
        "text_variables": {},
    }, indent=2)


# --------------------------------------------------------------------------
# structural checks
# --------------------------------------------------------------------------

def check(files, root_uuid=None):
    """Structural validation. Not a substitute for KiCad opening the file, but
    it catches the failure modes a generator actually produces."""
    problems = []
    all_uuids = []
    for path, text in files.items():
        depth, in_str, esc_next = 0, False, False
        for ch in text:
            if esc_next:
                esc_next = False
                continue
            if ch == "\\" and in_str:
                esc_next = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        problems.append(f"{path.name}: unbalanced ')'")
                        break
        if depth != 0:
            problems.append(f"{path.name}: {depth} unclosed paren(s)")
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("(uuid "):
                all_uuids.append(s[6:].rstrip(")").strip())

    dupes = {u for u in all_uuids if all_uuids.count(u) > 1}
    if dupes:
        problems.append(f"duplicate UUIDs: {sorted(dupes)[:5]}")

    # every sheet pin must have a matching hierarchical label in its target
    for path, text in files.items():
        if not path.name.endswith(".kicad_sch"):
            continue
        blocks = re.findall(r'\(sheet \(at.*?\n  \)', text, re.S)
        for blk in blocks:
            fm = re.search(r'\(property "Sheetfile" "([^"]+)"', blk)
            if not fm:
                continue
            target = HW / fm.group(1)
            if target not in files:
                problems.append(f"{path.name}: Sheetfile {fm.group(1)} not generated")
                continue
            tgt = files[target]
            labels = set(re.findall(r'\(hierarchical_label "([^"]+)"', tgt))
            for pin in re.findall(r'^    \(pin "([^"]+)" ', blk, re.M):
                if pin not in labels:
                    problems.append(
                        f"{path.name}: sheet pin {pin!r} has no hierarchical_label "
                        f"in {fm.group(1)}")

    # Every symbol instance path must be rooted at the root document's uuid.
    # The first version of this generator used each child file's *own* uuid
    # instead; the files still parsed and the structural checks still passed,
    # but KiCad placed every carrier symbol on the root sheet. Only ERC caught
    # it, so it is now checked here.
    if root_uuid:
        for path, text in files.items():
            for p in re.findall(r'\(path "(/[0-9a-f-]{8,}[^"]*)"\s*\n\s*\(reference',
                                text):
                if not p.startswith(f"/{root_uuid}"):
                    problems.append(
                        f"{path.name}: symbol instance path {p!r} is not rooted "
                        f"at the root uuid /{root_uuid}")
    return problems


def build_sym_lib():
    """A real jfox.kicad_sym, so the project's symbols resolve to a registered
    library. Without it KiCad emits a lib_symbol_issues warning per placed
    symbol ("configuration does not include the symbol library 'jfox'") even
    though the definitions are cached in the schematic and render fine."""
    defs = []
    for n in (3, 4, 6, 8):
        _, d = conn_symbol_def(n)
        # In a .kicad_sym the symbol name carries no "lib:" prefix, and the
        # whole block sits one indent level shallower than in a schematic.
        d = d.replace(f'(symbol "jfox:Conn_01x{n:02d}"',
                      f'(symbol "Conn_01x{n:02d}"', 1)
        defs.append("\n".join(line[2:] for line in d.splitlines()))
    return ('(kicad_symbol_lib (version 20230819) (generator kicad_symbol_editor)\n'
            + "\n".join(defs) + "\n)\n")


def build_sym_lib_table():
    return ('(sym_lib_table\n'
            '  (version 7)\n'
            '  (lib (name "jfox")(type "KiCad")'
            '(uri "${KIPRJMOD}/jfox.kicad_sym")(options "")'
            '(descr "JFOX TMR carrier connectors"))\n'
            ')\n')


def main():
    HW.mkdir(parents=True, exist_ok=True)

    # Allocate the hierarchy up front: a symbol's instance path is
    # "/<root-uuid>/<sheet-element-uuid>", so the child sheets cannot be built
    # until those two are known.
    root_uuid = uid()
    fmu_sheet_uuids = [uid() for _ in BOARDS]
    carrier_sheet_uuid = uid()

    _, fmu = build_fmu_sheet()
    _, carrier = build_carrier(root_uuid, carrier_sheet_uuid)

    carrier_pins = ([(f"VBRICK_{b}", "passive") for b in BOARDS]
                    + [(f"BATT_V_{b}", "input") for b in BOARDS]
                    + [(f"BATT_I_{b}", "input") for b in BOARDS])
    root = build_root(root_uuid, fmu_sheet_uuids, carrier_sheet_uuid,
                      PER_BOARD, carrier_pins)

    files = {
        HW / "fmu-v2.kicad_sch": fmu,
        HW / "carrier.kicad_sch": carrier,
        HW / f"{PROJECT}.kicad_sch": root,
    }
    problems = check(files, root_uuid)
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    (HW / f"{PROJECT}.kicad_pro").write_text(build_pro(), encoding="utf-8")
    (HW / "jfox.kicad_sym").write_text(build_sym_lib(), encoding="utf-8")
    (HW / "sym-lib-table").write_text(build_sym_lib_table(), encoding="utf-8")

    # The carrier again, as its own project - this is the one that becomes a
    # physical board. Kept separate from jfox-tmr because the three FMU
    # modules are separately manufactured hardware; if they shared a project,
    # a board netlist would try to place 421 module components on the carrier.
    car = HW / "carrier"
    car.mkdir(exist_ok=True)
    _, carrier_standalone = build_carrier(root_uuid, carrier_sheet_uuid,
                                          standalone=True)
    (car / "carrier.kicad_sch").write_text(carrier_standalone, encoding="utf-8")
    (car / "carrier.kicad_pro").write_text(
        build_pro("carrier"), encoding="utf-8")
    (car / "jfox.kicad_sym").write_text(build_sym_lib(), encoding="utf-8")
    (car / "sym-lib-table").write_text(build_sym_lib_table(), encoding="utf-8")

    extra = [HW / f"{PROJECT}.kicad_pro", HW / "jfox.kicad_sym",
             HW / "sym-lib-table",
             car / "carrier.kicad_sch", car / "carrier.kicad_pro",
             car / "jfox.kicad_sym", car / "sym-lib-table"]
    for path in list(files) + extra:
        print(f"  wrote {path.relative_to(REPO)} ({path.stat().st_size} bytes)")
    if problems:
        print("\nSTRUCTURAL PROBLEMS:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("\nstructural checks passed "
          "(parens balanced, UUIDs unique, every sheet pin has a matching label)")


if __name__ == "__main__":
    main()
