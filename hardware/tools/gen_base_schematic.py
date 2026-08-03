#!/usr/bin/env python3
"""Generate the JFOX-BASE-v1 schematic: three-channel module base board.

The board three JFOX-FMU-v1 modules plug into. See
hardware/jfox-base-v1/STACK_ARCHITECTURE.md for the mechanical stack and for
why each channel gets its own connector rather than sharing a pass-through
bus.

Sheets:

  1  root
  2  mezzanine sockets    J1/J2/J3, one per channel
  3  power distribution   per-channel fuse, ORing FET and sense
  4  CAN FD bus           harness landings, shared bus, end termination
  5  actuator outputs     headers only - arbitration is NOT decided
  6  external I/O         GPS, RC, telemetry, USB to the airframe
  7  fibre-optic link     two redundant channels to the I/O side

Net naming: every signal that belongs to one module carries an A_, B_ or C_
prefix. A net with no prefix is genuinely shared, and there are deliberately
very few of them - each one is a common-cause failure path and has to earn
its place. See check_base_schematic.py, which enforces exactly that.

    python hardware/tools/gen_base_schematic.py

Writes hardware/jfox-base-v1/*.kicad_sch and the project file.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_fmu_schematic as G          # noqa: E402  page geometry and helpers

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-base-v1"
PROJECT = "jfox-base"

CHANNELS = ("A", "B", "C")

# --------------------------------------------------------------------------
# The socket pinout is the module's, mirrored. It is imported rather than
# retyped: a base board whose pin 17 disagrees with the module's pin 17 is a
# board that destroys a module on first power-up, and two hand-maintained
# copies of a 60-entry list will disagree eventually.
# --------------------------------------------------------------------------
MEZZ_PINS = G.MEZZ_PINS

# Signals that stay per-channel get a prefix. Everything else is shared, and
# the list of shared nets is short on purpose.
SHARED = {"GND", "NC"}



def no_connect(x, y):
    """An explicit no-connect flag at a pin."""
    return f'\t(no_connect\n\t\t(at {x} {y})\n\t\t(uuid "{G.uid()}")\n\t)'


def chan_net(ch, net):
    """The base-board net name for one module pin."""
    if net in SHARED:
        return net
    return f"{ch}_{net}"


# --------------------------------------------------------------------------
# Parts
# --------------------------------------------------------------------------

# Mezzanine header: the mating half of the module's DF12C3.0-60DS-0.5V.
#
# The series letter changes with the gender. DF12*C* is the socket series and
# DF12*E* is the header series - there is no such part as a DF12C-60DP, which
# is what this said first. ERC caught it as a missing footprint; ordering
# would have caught it as a part number the distributor does not stock.
# The mating half of the card's gold fingers. The card carries no connector
# at all, so this socket is the only part in the interface - one mated pair
# per channel instead of two, and nothing to work loose at the card end.
MEZZ_FP = ("Connector_PCBEdge:"
           "Samtec_MECF-30-01-L-DV_2x30_P1.27mm_Polarized_Socket_Horizontal")

# Every module signal this board routes somewhere. Populated by the sheets
# as they run, and consumed by build_expansion() to work out what is left
# over. Derived rather than listed: a hand-maintained list of "spare"
# signals goes stale the first time a port moves, and the symptom is a pin
# that quietly connects to nothing.
ROUTED = set()


def used(*nets):
    """Record that these nets reach something other than the socket."""
    ROUTED.update(nets)
    return nets

JST_FP = {
    4:  "Connector_JST:JST_GH_SM04B-GHS-TB_1x04-1MP_P1.25mm_Horizontal",
    5:  "Connector_JST:JST_GH_SM05B-GHS-TB_1x05-1MP_P1.25mm_Horizontal",
    6:  "Connector_JST:JST_GH_SM06B-GHS-TB_1x06-1MP_P1.25mm_Horizontal",
    8:  "Connector_JST:JST_GH_SM08B-GHS-TB_1x08-1MP_P1.25mm_Horizontal",
    10: "Connector_JST:JST_GH_SM10B-GHS-TB_1x10-1MP_P1.25mm_Horizontal",
}

R_FP = "Resistor_SMD:R_0603_1608Metric"
C_FP = "Capacitor_SMD:C_0603_1608Metric"


# --------------------------------------------------------------------------
# sheet 2 - the three mezzanine sockets
# --------------------------------------------------------------------------

def build_sockets():
    """J1/J2/J3, one per channel, pinout mirrored from the module.

    Three separate connectors rather than one bus. The extra copper is the
    price of channel independence: a bent contact in J2 costs channel B and
    nothing else, where the same fault on a shared bus costs all three and
    the voter has nothing left to vote on.
    """
    ru = G.uid()
    libs = G.sym_defs(G.KICAD_SYMS / "Connector_Generic.kicad_sym",
                      "Conn_02x30_Odd_Even", "Connector_Generic")
    geom = G.pin_list(libs[-1])
    pins = sorted(geom, key=lambda p: int(p[0]))

    body = [G.text(
        "Three independent sockets, one per channel.\\n"
        "\\n"
        "Pinout is imported from the module's own MEZZ_PINS, not retyped -\\n"
        "a base board whose pin 17 disagrees with the module's pin 17\\n"
        "destroys a module on first power-up.\\n"
        "\\n"
        "Every net here is prefixed A_, B_ or C_. The unprefixed ones are\\n"
        "GND only. Anything else shared between channels would be a\\n"
        "common-cause failure path.", 0, 0, 1.4)]

    for i, ch in enumerate(CHANNELS):
        ref = f"J{i + 1}"
        # Two columns, not three. A 60-pin connector carries about 35 mm of
        # global-label text on each side, so three in a row spans 195.6 mm
        # against the 182 mm A4 portrait can hold.
        cx = 50.8 + (i % 2) * 85.09
        cy = 69.85 + (i // 2) * 114.3
        body.append(G.place("Connector_Generic:Conn_02x30_Odd_Even", ref,
                            f"Mezz {ch}", cx, cy, ru, [],
                            label_dy=42.0, fp=MEZZ_FP))
        for (num, _nm, dx, dy, ang), net in zip(pins, MEZZ_PINS):
            if net == "NC":
                # An explicit marker, not silence. A pin left bare is
                # indistinguishable from a pin somebody forgot, and ERC
                # reports it as an error either way.
                body.append(no_connect(round(cx + dx, 2), round(cy + dy, 2)))
                continue
            ax, ay = round(cx + dx, 2), round(cy + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            bx, by = round(ax + sx, 2), round(ay + sy, 2)
            body.append(G.wire(ax, ay, bx, by))
            n = chan_net(ch, net)
            shape = ("input" if net.startswith(("+", "GND", "VDD"))
                     else "bidirectional")
            body.append(G.glabel(n, shape, bx, by, 0 if sx < 0 else 180))

    return libs, body, ru


# --------------------------------------------------------------------------
# sheet 3 - power distribution
# --------------------------------------------------------------------------

# Per channel: input fuse, ORing PMOS, shunt. The module already carries an
# LTC4417 that ORs its own three inputs; this stage exists for a different
# reason - to stop ONE channel's fault pulling the other two down.
POWER = [
    # ref suffix, value, purpose
    ("F", "3A", "input fuse - a shorted module must clear itself, not the bus"),
    ("Q", "SQJ431EP", "ORing PMOS, reverse-blocking"),
    ("R", "0R010", "current shunt, 10 mohm"),
]


def build_power():
    """One fuse + ORing FET + shunt per channel, from a single airframe feed.

    The airframe supply is a single source and cannot be triplicated, so it
    is a common-cause input by definition. What can be prevented is a fault
    in one module propagating back up and taking the other two with it, and
    that is all this stage does.
    """
    ru = G.uid()
    libs = []
    for lib, name, nick in (
            ("Device.kicad_sym", "Fuse", "Device"),
            ("Device.kicad_sym", "R", "Device"),
            ("Device.kicad_sym", "C", "Device"),
            ("Device.kicad_sym", "D_Schottky", "Device"),
            ("Connector_Generic.kicad_sym", "Conn_01x04", "Connector_Generic"),
    ):
        libs += G.sym_defs(G.KICAD_SYMS / lib, name, nick)
    geom = {re.search(r'\(symbol "([^"]+)"', s).group(1): G.pin_list(s)
            for s in libs}

    body = [G.text(
        "The airframe feed is ONE source. It cannot be triplicated, so it\\n"
        "is a common-cause input by definition and this sheet does not\\n"
        "pretend otherwise.\\n"
        "\\n"
        "What it does prevent: a fault inside one module propagating back\\n"
        "up the rail and browning out the other two. Each channel gets its\\n"
        "own fuse, its own reverse-blocking FET and its own shunt.\\n"
        "\\n"
        "The module's LTC4417 ORs its own three inputs. This is a\\n"
        "different job at a different place and does not replace it.",
        0, 0, 1.4)]

    # TWO airframe feeds, right-hand and left-hand, physically separated on
    # the master board. This sheet used to concede that a single supply is a
    # common-cause input by definition; with two independent feeds that is no
    # longer true, and no single supply failure takes the set down.
    #
    # They are ORed by D50/D51 into one bus before the per-channel fuses, so
    # a shorted feed is isolated by its own diode rather than pulling the
    # other one down.
    for k, (ref, lab, rail) in enumerate((
            ("J50", "PWR 1 RH", "VBAT_RH"),
            ("J51", "PWR 2 LH", "VBAT_LH"))):
        px = 30.48 + k * 44.45
        body.append(G.place("Connector_Generic:Conn_01x04", ref, lab,
                            px, 39.37, ru, [], label_dy=10.0, fp=JST_FP[4]))
        for (num, _nm, dx, dy, ang), net in zip(
                sorted(geom["Connector_Generic:Conn_01x04"],
                       key=lambda p: int(p[0])),
                [rail, rail, "GND", "GND"]):
            ax, ay = round(px + dx, 2), round(39.37 + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
            body.append(G.glabel(net, "input", round(ax + sx, 2),
                                 round(ay + sy, 2), 0 if sx < 0 else 180))
        body += (G.two_pin(f"D{50 + k}", "Device:D_Schottky", "SS54",
                           px, 66.04, rail, "VBAT_IN", ru,
                           geom, vertical=True))

    # Per-channel chain: VBAT_IN -> fuse -> shunt -> X_VDD_BRICK
    for i, ch in enumerate(CHANNELS):
        x = 39.37 + i * 48.26
        y = 96.52
        body += (G.two_pin(f"F{i + 1}", "Device:Fuse", "3A", x, y,
                              "VBAT_IN", f"{ch}_FUSED", ru,
                              geom, vertical=True))
        body += (G.two_pin(f"R{i + 1}", "Device:R", "0R010", x, y + 30.48,
                              f"{ch}_FUSED", used(f"{ch}_VDD_BRICK")[0], ru,
                              geom, vertical=True))
        body += (G.two_pin(f"C{i + 1}", "Device:C", "10u", x + 20.32,
                              y + 30.48, f"{ch}_VDD_BRICK", "GND", ru,
                              geom, vertical=True))
    return libs, body, ru


# --------------------------------------------------------------------------
# sheet 4 - CAN FD bus
# --------------------------------------------------------------------------

def build_can():
    """Harness landings for the modules' isolated CAN, plus the vehicle bus.

    CAN does NOT run through the mezzanine. Each module's CAN leaves through
    its own isolated transceiver at J12/J13 as a JST-GH harness, which is
    the entire point of putting an ISOW1044 on the module - the isolation
    barrier is on the module, so the base board never sees module ground.
    """
    ru = G.uid()
    libs = []
    for lib, name, nick in (
            ("Device.kicad_sym", "R", "Device"),
            ("Connector_Generic.kicad_sym", "Conn_01x04", "Connector_Generic"),
            ("Connector_Generic.kicad_sym", "Conn_01x05", "Connector_Generic"),
    ):
        libs += G.sym_defs(G.KICAD_SYMS / lib, name, nick)
    geom = {re.search(r'\(symbol "([^"]+)"', s).group(1): G.pin_list(s)
            for s in libs}

    body = [G.text(
        "TERMINATION CHANGED FROM THE MODULE-LEVEL SCHEME.\\n"
        "\\n"
        "Cut JP1 and JP2 on ALL THREE modules. The two 120 ohm end\\n"
        "terminators live here, one at each physical end of the bus run.\\n"
        "\\n"
        "Three modules with JP1/JP2 bridged is three terminators in\\n"
        "parallel - about 40 ohm, a real signal-integrity fault. Putting\\n"
        "them on the base board also puts them at the TRUE electrical ends\\n"
        "of the bus, and means no module has to be modified according to\\n"
        "where it happens to sit in the stack.\\n"
        "\\n"
        "This supersedes HARDWARE_BRINGUP.md Stage 3, which was written\\n"
        "for the PX4FMUv2.4.5 carrier where R409 could not be removed.",
        0, 0, 1.4)]

    # Per-channel harness landings, CAN1 and CAN2.
    for i, ch in enumerate(CHANNELS):
        for b, bus in enumerate(("CAN1", "CAN2")):
            ref = f"J{60 + i * 2 + b}"
            cx = 34.29 + b * 60.96
            cy = 55.88 + i * 40.64
            body.append(G.place("Connector_Generic:Conn_01x04", ref,
                                f"{ch} {bus}", cx, cy, ru, [],
                                label_dy=9.0, fp=JST_FP[4]))
            # Pin 4 is the BUS-side ground, not the base board's. The
            # module's ISOW1044 isolates its CAN side precisely so that the
            # bus and the flight computer do not share a return; wiring this
            # to GND shorts across the barrier and discards the isolation
            # the part was chosen for.
            #
            # Pin 1 is the module's own isolated supply, going OUT to the
            # harness. It is deliberately left unconnected here - commoning
            # three isolated supplies would defeat the barrier a second way.
            nets = [None, f"{bus}_H", f"{bus}_L", "CAN_GND_ISO"]
            for (num, _nm, dx, dy, ang), net in zip(
                    sorted(geom["Connector_Generic:Conn_01x04"],
                           key=lambda p: int(p[0])), nets):
                ax, ay = round(cx + dx, 2), round(cy + dy, 2)
                if net is None:
                    body.append(no_connect(ax, ay))
                    continue
                sx, sy = G.stub_len(ang, h=5.08)
                body.append(G.wire(ax, ay, round(ax + sx, 2),
                                   round(ay + sy, 2)))
                body.append(G.glabel(net, "bidirectional", round(ax + sx, 2),
                                     round(ay + sy, 2), 0 if sx < 0 else 180))

    # The two end terminators, and the vehicle bus connector.
    for b, bus in enumerate(("CAN1", "CAN2")):
        body += (G.two_pin(f"R{40 + b}", "Device:R", "120",
                              146.05 + b * 21.59, 60.96,
                              f"{bus}_H", f"{bus}_L", ru,
                              geom, vertical=True))
    body.append(G.place("Connector_Generic:Conn_01x05", "J70", "VEHICLE CAN",
                        146.05, 168.91, ru, [], label_dy=10.0, fp=JST_FP[5]))
    for (num, _nm, dx, dy, ang), net in zip(
            sorted(geom["Connector_Generic:Conn_01x05"],
                   key=lambda p: int(p[0])),
            ["CAN1_H", "CAN1_L", "CAN2_H", "CAN2_L", "CAN_GND_ISO"]):
        ax, ay = round(146.05 + dx, 2), round(168.91 + dy, 2)
        sx, sy = G.stub_len(ang, h=5.08)
        body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
        body.append(G.glabel(net, "bidirectional", round(ax + sx, 2),
                             round(ay + sy, 2), 0 if sx < 0 else 180))
    return libs, body, ru


# --------------------------------------------------------------------------
# sheet 5 - actuator outputs
# --------------------------------------------------------------------------

def build_actuators():
    """Three 8-channel headers. Headers, and nothing else.

    How three modules' PWM outputs combine into one actuator command is not
    decided - TmrVoter is still not wired into motor_task. So all three sets
    come out to headers and the arbitration mechanism stays a separately
    scoped decision. Baking a guess into copper would be worse than leaving
    it open, because copper is the hardest thing on this board to change.
    """
    ru = G.uid()
    libs = G.sym_defs(G.KICAD_SYMS / "Connector_Generic.kicad_sym",
                      "Conn_01x10", "Connector_Generic")
    geom = G.pin_list(libs[-1])

    body = [G.text(
        "HEADERS ONLY - NO ARBITRATION.\\n"
        "\\n"
        "How the three modules' outputs combine into one actuator command\\n"
        "is an open design question. TmrVoter is not wired into\\n"
        "motor_task, so there is no decision to implement yet.\\n"
        "\\n"
        "All three sets are brought out. The arbitration mechanism is\\n"
        "deliberately left to a separately scoped decision rather than\\n"
        "guessed at here - copper is the hardest thing on this board to\\n"
        "change later.", 0, 0, 1.4)]

    pwm = ["TIM1_CH1", "TIM1_CH2", "TIM1_CH3", "TIM1_CH4",
           "TIM4_CH1", "TIM4_CH2", "TIM4_CH3", "TIM4_CH4"]
    for i, ch in enumerate(CHANNELS):
        ref = f"J{80 + i}"
        cx = 40.64 + i * 58.42
        cy = 110.49
        body.append(G.place("Connector_Generic:Conn_01x10", ref,
                            f"ACT {ch}", cx, cy, ru, [], label_dy=16.0,
                            fp=JST_FP[10]))
        nets = used(*[f"{ch}_{p}" for p in pwm],
                    f"{ch}_VDD_SERVO", "GND")
        for (num, _nm, dx, dy, ang), net in zip(
                sorted(geom, key=lambda p: int(p[0])), nets):
            ax, ay = round(cx + dx, 2), round(cy + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
            body.append(G.glabel(net, "output", round(ax + sx, 2),
                                 round(ay + sy, 2), 0 if sx < 0 else 180))
    return libs, body, ru


# --------------------------------------------------------------------------
# sheet 6 - external I/O breakout
# --------------------------------------------------------------------------

IO_PORTS = [
    ("J90", 10, "GPS1", ["USART2_TX", "USART2_RX", "I2C2_SCL", "I2C2_SDA",
                         "SAFETY_SW", "SAFETY_LED", "+5V_CARRIER", "GND",
                         "GND", "GND"]),
    ("J91", 5,  "RC IN", ["USART3_RX", "USART3_TX", "+5V_CARRIER", "GND",
                          "GND"]),
    ("J92", 6,  "TELEM1", ["UART7_TX", "UART7_RX", "USART3_CTS",
                           "USART3_RTS", "+5V_CARRIER", "GND"]),
    ("J93", 6,  "TELEM2", ["UART8_TX", "UART8_RX", "USART2_CTS",
                           "USART2_RTS", "+5V_CARRIER", "GND"]),
]


def build_io():
    """Airframe-side I/O, brought out once rather than three times.

    Each port lands on ONE channel. A GPS wired to all three modules in
    parallel is a shared sensor, which means a shared failure - and a
    triple-redundant flight controller reading one GPS has redundant
    computers voting on identical wrong data.

    Which channel owns which port is a system decision recorded here so it
    is visible rather than implied by the routing.
    """
    ru = G.uid()
    libs, seen = [], set()
    for _ref, n, _lab, _nets in IO_PORTS:
        nm = "Conn_01x%02d" % n
        if nm not in seen:
            seen.add(nm)
            libs += G.sym_defs(G.KICAD_SYMS / "Connector_Generic.kicad_sym",
                               nm, "Connector_Generic")
    geom = {re.search(r'\(symbol "([^"]+)"', s).group(1): G.pin_list(s)
            for s in libs}

    body = [G.text(
        "Each port lands on ONE channel, named below the connector.\\n"
        "\\n"
        "A GPS wired to all three modules in parallel is a shared sensor,\\n"
        "and a shared sensor is a shared failure: three computers voting\\n"
        "on identical wrong data agree perfectly and are still wrong.\\n"
        "\\n"
        "Genuine sensor redundancy needs one receiver per channel. That is\\n"
        "an airframe-level decision about cost and weight, so this board\\n"
        "makes the current assignment explicit instead of hiding it in\\n"
        "the routing.", 0, 0, 1.4)]

    # Port -> owning channel. Spread so no single channel owns everything.
    OWNER = {"J90": "A", "J91": "B", "J92": "A", "J93": "C"}

    for i, (ref, n, lab, nets) in enumerate(IO_PORTS):
        ch = OWNER[ref]
        cx = 40.64 + (i % 2) * 69.85
        cy = 88.9 + (i // 2) * 88.9
        body.append(G.place("Connector_Generic:Conn_01x%02d" % n, ref,
                            f"{lab} ({ch})", cx, cy, ru, [],
                            label_dy=round(n * 1.27 + 6.35, 2),
                            fp=JST_FP[n]))
        for (num, _nm, dx, dy, ang), net in zip(
                sorted(geom["Connector_Generic:Conn_01x%02d" % n],
                       key=lambda p: int(p[0])), nets):
            ax, ay = round(cx + dx, 2), round(cy + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
            used(chan_net(ch, net))
            body.append(G.glabel(chan_net(ch, net), "bidirectional",
                                 round(ax + sx, 2), round(ay + sy, 2),
                                 0 if sx < 0 else 180))
    return libs, body, ru


def build_panel():
    """Master board front panel: debug, console USB-C, three status LEDs.

    One debug connector and one console for the SET, on the master board -
    per the JFOX FCU V1 arrangement. The three LEDs are one per channel, so
    a technician can see which channel is alive without a laptop. That is
    the only channel-state indication available with the lid on, which is
    why each one is driven from its own module rather than from a summary
    signal computed somewhere.
    """
    ru = G.uid()
    libs = []
    for lib, name, nick in (
            ("Connector_Generic.kicad_sym", "Conn_01x06", "Connector_Generic"),
            ("Connector_Generic.kicad_sym", "Conn_01x05", "Connector_Generic"),
            ("Device.kicad_sym", "LED", "Device"),
            ("Device.kicad_sym", "R", "Device"),
    ):
        libs += G.sym_defs(G.KICAD_SYMS / lib, name, nick)
    geom = {re.search(r'\(symbol "([^"]+)"', s_).group(1): G.pin_list(s_)
            for s_ in libs}

    body = [G.text(
        "One debug port and one console for the SET, on the master board.\\n"
        "\\n"
        "Three LEDs, one per channel, each driven from ITS OWN module.\\n"
        "A single LED driven from a summary signal tells you the summary\\n"
        "logic is alive, which is not the question anyone is asking when\\n"
        "they look at it. With the lid on, these are the only channel\\n"
        "state indication there is.", 0, 0, 1.4)]

    # SWD debug, one for the set.
    body.append(G.place("Connector_Generic:Conn_01x06", "J52", "DEBUG",
                        38.1, 60.96, ru, [], label_dy=11.43, fp=JST_FP[6]))
    for (num, _nm, dx, dy, ang), net in zip(
            sorted(geom["Connector_Generic:Conn_01x06"],
                   key=lambda p: int(p[0])),
            used("A_SPI5_SCK", "A_SPI5_MISO", "A_SPI5_MOSI",
                 "A_UART4_TX", "A_UART4_RX", "GND")):
        ax, ay = round(38.1 + dx, 2), round(60.96 + dy, 2)
        sx, sy = G.stub_len(ang, h=5.08)
        body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
        body.append(G.glabel(net, "bidirectional", round(ax + sx, 2),
                             round(ay + sy, 2), 0 if sx < 0 else 180))

    # Console USB-C, brought out as a 5-way to the master board receptacle.
    body.append(G.place("Connector_Generic:Conn_01x05", "J54", "USB-C",
                        119.38, 60.96, ru, [], label_dy=10.16, fp=JST_FP[5]))
    for (num, _nm, dx, dy, ang), net in zip(
            sorted(geom["Connector_Generic:Conn_01x05"],
                   key=lambda p: int(p[0])),
            used("A_USART2_TX", "A_USART2_RX", "A_USART2_CTS",
                 "A_USART2_RTS", "GND")):
        ax, ay = round(119.38 + dx, 2), round(60.96 + dy, 2)
        sx, sy = G.stub_len(ang, h=5.08)
        body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
        body.append(G.glabel(net, "bidirectional", round(ax + sx, 2),
                             round(ay + sy, 2), 0 if sx < 0 else 180))

    # One LED per channel, each with its own series resistor.
    for i, ch in enumerate(CHANNELS):
        x = 41.91 + i * 33.02
        body += (G.two_pin(f"R{60 + i}", "Device:R", "1k", x, 137.16,
                           used(f"{ch}_SAFETY_LED")[0], f"{ch}_LED_A", ru,
                           geom, vertical=True))
        body += (G.two_pin(f"D{i + 1}", "Device:LED", "GRN", x, 165.1,
                           f"{ch}_LED_A", "GND", ru, geom, vertical=True))
    return libs, body, ru


# --------------------------------------------------------------------------
# sheet 7 - fibre-optic link, two redundant channels
# --------------------------------------------------------------------------

def build_fibre():
    """Two independent optical channels to the I/O side.

    Each channel is a transmitter and a receiver, on separate fibres, fed
    from a different module. One fibre break or one dead emitter costs one
    channel and not the link.

    PART NUMBERS ARE NOT VERIFIED. There is no optical datasheet in
    datasheets/, so the transmitters and receivers are drawn as 3-pin
    placeholders rather than as a specific part. Drawing a real part number
    that nobody has checked would look settled and be exactly as unverified
    as this is - the difference would be that nobody could tell.
    """
    ru = G.uid()
    libs = []
    for lib, name, nick in (
            ("Connector_Generic.kicad_sym", "Conn_01x03",
             "Connector_Generic"),
            ("Device.kicad_sym", "R", "Device"),
            ("Device.kicad_sym", "C", "Device"),
    ):
        libs += G.sym_defs(G.KICAD_SYMS / lib, name, nick)
    geom = {re.search(r'\(symbol "([^"]+)"', s).group(1): G.pin_list(s)
            for s in libs}

    body = [G.text(
        "PART NUMBERS NOT YET VERIFIED - see STACK_ARCHITECTURE.md s7.\\n"
        "\\n"
        "The intended family is Broadcom Versatile Link 650 nm plastic\\n"
        "optical fibre, but there is no optical datasheet in datasheets/,\\n"
        "so the launch power budget, the fibre length and the DO-160G\\n"
        "temperature range are all unconfirmed.\\n"
        "\\n"
        "The emitters and detectors are therefore drawn as 3-pin\\n"
        "placeholders. A real part number here would look settled while\\n"
        "being exactly as unchecked - the only difference is that nobody\\n"
        "would be able to tell by looking.\\n"
        "\\n"
        "TWO channels, fed from DIFFERENT modules, on SEPARATE fibres.\\n"
        "One break or one dead emitter costs one channel, not the link.",
        0, 0, 1.4)]

    # Channel 1 driven by module A, channel 2 by module B. Module C is the
    # spare: a third optical channel would need a third fibre run, which is
    # an airframe cost decision rather than a board one.
    FIBRE = [("OPT1", "A", "UART7"), ("OPT2", "B", "UART7")]

    for i, (name, ch, uart) in enumerate(FIBRE):
        y = 80.01 + i * 88.9
        # Transmitter: driven from the module's UART TX.
        body.append(G.place("Connector_Generic:Conn_01x03", f"U{50 + i * 2}",
                            f"{name} TX", 45.72, y, ru, [], label_dy=8.0,
                            fp="OptoDevice:AGILENT_HFBR-152x"))
        for (num, _nm, dx, dy, ang), net in zip(
                sorted(geom["Connector_Generic:Conn_01x03"],
                       key=lambda p: int(p[0])),
                used(f"{ch}_{uart}_TX", f"{ch}_VDD_BRICK", "GND")):
            ax, ay = round(45.72 + dx, 2), round(y + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
            body.append(G.glabel(net, "input", round(ax + sx, 2),
                                 round(ay + sy, 2), 0 if sx < 0 else 180))
        # Receiver: returns into the same module's UART RX.
        body.append(G.place("Connector_Generic:Conn_01x03", f"U{51 + i * 2}",
                            f"{name} RX", 119.38, y, ru, [], label_dy=8.0,
                            fp="OptoDevice:AGILENT_HFBR-252x"))
        for (num, _nm, dx, dy, ang), net in zip(
                sorted(geom["Connector_Generic:Conn_01x03"],
                       key=lambda p: int(p[0])),
                used(f"{ch}_{uart}_RX", f"{ch}_VDD_BRICK", "GND")):
            ax, ay = round(119.38 + dx, 2), round(y + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
            body.append(G.glabel(net, "output", round(ax + sx, 2),
                                 round(ay + sy, 2), 0 if sx < 0 else 180))
        # Supply decoupling, local to each optical part.
        body += (G.two_pin(f"C{50 + i}", "Device:C", "100n", 74.93, y + 30.48,
                              f"{ch}_VDD_BRICK", "GND", ru,
                              geom, vertical=True))
    return libs, body, ru



# --------------------------------------------------------------------------
# sheet 8 - per-channel expansion, for whatever the dedicated ports leave
# --------------------------------------------------------------------------

def build_expansion():
    """Every module signal the other sheets did not route.

    The dedicated I/O ports each land on ONE channel, so the same signal is
    a GPS line on channel A and unused on B and C. Without this sheet those
    pins reach the socket and stop there - 51 of them, which ERC reports as
    isolated labels and a bench technician discovers as a connector that
    does nothing.

    The list is DERIVED from what the other sheets recorded in ROUTED, not
    written out by hand. A hand-kept list of spares goes stale the first
    time a port moves, and the symptom is a pin that silently connects to
    nothing - which is the failure this sheet exists to prevent, reappearing
    inside the fix for it.

    Consequence worth stating: the three headers carry DIFFERENT signals,
    because the channels own different ports. Same part, same position, same
    pin count; the net names differ. The alternative - one GPS, one RC and
    one telemetry port PER channel - is genuine sensor redundancy and needs
    twelve connectors, which does not fit a 100 x 80 mm board.
    """
    ru = G.uid()
    libs = G.sym_defs(G.KICAD_SYMS / "Connector_Generic.kicad_sym",
                      "Conn_02x10_Odd_Even", "Connector_Generic")
    geom = G.pin_list(libs[-1])
    pins = sorted(geom, key=lambda p: int(p[0]))

    body = [G.text(
        "Everything the dedicated ports did not claim.\\n"
        "\\n"
        "Derived from what the other sheets actually routed, not from a\\n"
        "hand-kept list of spares - such a list goes stale the first time\\n"
        "a port moves, and the symptom is a pin connected to nothing.\\n"
        "\\n"
        "The three headers carry DIFFERENT signals: each channel owns\\n"
        "different dedicated ports, so different signals are left over.\\n"
        "Same part and same pin count; only the net names differ.",
        0, 0, 1.4)]
    # The line breaks above must be the TWO-CHARACTER escape, not real
    # newlines. A real newline inside the quoted (text "...") makes the
    # sheet unloadable; loaded on its own KiCad says "Failed to load
    # schematic", but loaded THROUGH THE ROOT it is silently skipped - the
    # root opens, the sheet is listed, and its components are simply absent
    # from the netlist. That is why this sheet appeared to change nothing:
    # ERC kept reporting the same 51 isolated labels because the fix for
    # them was never being read. main() now verifies every sheet loads.

    for i, ch in enumerate(CHANNELS):
        spare = [chan_net(ch, n) for n in dict.fromkeys(MEZZ_PINS)
                 if n not in SHARED and chan_net(ch, n) not in ROUTED]
        cx = 43.18 + i * 46.99
        cy = 88.9
        body.append(G.place("Connector_Generic:Conn_02x10_Odd_Even",
                            f"J{100 + i}", f"EXP {ch}", cx, cy, ru, [],
                            label_dy=17.78,
                            fp="Connector_PinHeader_1.27mm:"
                               "PinHeader_2x10_P1.27mm_Vertical_SMD"))
        nets = spare + ["GND"] * (len(pins) - len(spare))
        for (num, _nm, dx, dy, ang), net in zip(pins, nets):
            ax, ay = round(cx + dx, 2), round(cy + dy, 2)
            sx, sy = G.stub_len(ang, h=5.08)
            body.append(G.wire(ax, ay, round(ax + sx, 2), round(ay + sy, 2)))
            body.append(G.glabel(net, "bidirectional", round(ax + sx, 2),
                                 round(ay + sy, 2), 0 if sx < 0 else 180))
        if len(spare) > len(pins):
            raise SystemExit(
                f"channel {ch}: {len(spare)} spare signals will not fit a "
                f"{len(pins)}-pin header - widen it rather than dropping "
                f"the overflow silently")
    return libs, body, ru


# --------------------------------------------------------------------------

SHEETS = [
    ("sockets",   "Mezzanine sockets - three channels", build_sockets),
    ("power",     "Power distribution - per channel",   build_power),
    ("can",       "CAN FD bus and termination",         build_can),
    ("actuators", "Actuator outputs - headers only",    build_actuators),
    ("io",        "External I/O breakout",              build_io),
    ("fibre",     "Fibre-optic link - two channels",    build_fibre),
    ("panel",     "Master board panel - debug, USB, LEDs", build_panel),
    # Last: it consumes what every sheet above recorded in ROUTED.
    ("expansion", "Per-channel expansion header",       build_expansion),
]


def main():
    BOARD.mkdir(parents=True, exist_ok=True)
    # The helpers stamp the project name into every symbol instance path.
    # Left as the module's name, KiCad opens the sheets with no annotation.
    G.PROJECT = PROJECT

    # Footprints for the parts this board uses and the module does not. The
    # mapper raises rather than defaulting, which is why these have to be
    # declared - a passive with no footprint silently reaches the board as a
    # component that cannot be placed.
    G.FOOTPRINTS.update({
        # 1206 rather than 0603: this fuse carries a whole channel's supply,
        # and the 0603 parts in this family top out below the 3 A needed.
        "Device:Fuse": "Fuse:Fuse_1206_3216Metric",
        "Device:LED": "LED_SMD:LED_0805_2012Metric",
        "Device:D_Schottky": "Diode_SMD:D_SMA",
    })

    files = {}
    root_uuid = G.uid()
    root_body = []
    for page, (stem, title, fn) in enumerate(SHEETS, start=2):
        libs, body, _ru = fn()
        body = G.fit(body, stem)
        files[BOARD / f"{PROJECT}-{stem}.kicad_sch"] = G.document(
            G.uid(), libs, body, title,
            comments=("JFOX-BASE-v1 three-channel module base board",))
        root_body.append(G.sheet_block(
            title, f"{PROJECT}-{stem}.kicad_sch",
            25.4 + ((page - 2) % 2) * 88.9,
            40.64 + ((page - 2) // 2) * 60.96, root_uuid, page))

    files[BOARD / f"{PROJECT}.kicad_sch"] = G.document(
        root_uuid, [], root_body, "JFOX-BASE-v1 - root",
        comments=("Three JFOX-FMU-v1 modules, one per channel",
                  "See STACK_ARCHITECTURE.md for the mechanical stack"))

    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    G.upgrade(list(files))
    for p in files:
        print(f"  wrote {p.relative_to(REPO)} ({p.stat().st_size} bytes)")
    verify_loadable(files)


def verify_loadable(files):
    """Load every sheet on its own and fail loudly if KiCad refuses.

    Writing the file is not evidence that it is valid. A real newline inside
    a quoted string makes a sheet unloadable, and through a root sheet KiCad
    SKIPS it silently - the hierarchy lists it, the netlist omits its
    components, and ERC keeps reporting whatever that sheet was supposed to
    fix. Loaded on its own, KiCad does say "Failed to load schematic", so
    that is how each one is checked.
    """
    cli = G.cli() if hasattr(G, "cli") else None
    if cli is None:
        for c in (Path(r"C:\Users\Jetta\AppData\Local\Programs\KiCad"
                       r"\10.0\bin\kicad-cli.exe"),
                  Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")):
            if c.exists():
                cli = c
                break
    if cli is None:
        print("  ! kicad-cli not found - sheets NOT verified as loadable")
        return

    tmp = Path(tempfile.gettempdir()) / "jfox_base_load.net"
    bad = []
    for f in files:
        tmp.unlink(missing_ok=True)
        r = subprocess.run([str(cli), "sch", "export", "netlist",
                            "-o", str(tmp), str(f)],
                           capture_output=True, text=True)
        if "Failed to load" in (r.stdout + r.stderr) or not tmp.exists():
            bad.append(f.name)
    tmp.unlink(missing_ok=True)
    if bad:
        raise SystemExit(
            "  these sheets were written but KiCad cannot load them:\n    "
            + "\n    ".join(bad)
            + "\n  Through the root sheet this is SILENT - the sheet is\n"
              "  listed and its components are absent from the netlist.")
    print(f"  verified {len(files)} sheet(s) load")


if __name__ == "__main__":
    main()
