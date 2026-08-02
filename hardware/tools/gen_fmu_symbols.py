#!/usr/bin/env python3
"""Generate the JFOX-FMU project symbol library.

Four parts on this board have no stock KiCad symbol. Their pin assignments are
transcribed here **once**, from the verified tables in
`hardware/jfox-fmu-v1/PINOUTS.md`, each with the datasheet document number it
came from. Generating the symbols from that data rather than drawing them by
hand means the schematic and the datasheet cannot drift apart silently.

Pin electrical types are chosen to make ERC useful rather than decorative:
supplies are `power_in`, outputs are `output`, and pins the datasheet says must
be tied somewhere are typed so that leaving them floating is reported.

    python hardware/tools/gen_fmu_symbols.py

Writes hardware/jfox-fmu-v1/jfox-fmu.kicad_sym.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "hardware" / "jfox-fmu-v1"
OUT = BOARD / "jfox-fmu.kicad_sym"

MM = 2.54

# (name, number, electrical type, side)
# side: "L" signals in, "R" signals out, "T" power, "B" ground
PARTS = [
    dict(
        name="ICM-42688-P",
        desc="TDK InvenSense 6-axis IMU, SPI/I2C, 14-pin LGA",
        source="TDK DS-000347 v1.6",
        keywords="IMU accelerometer gyroscope SPI",
        fp="Sensor_Motion:InvenSense_QFN-14_3x3mm_P0.5mm",
        pins=[
            ("AP_SCLK", "13", "input", "L"),
            ("AP_SDI", "14", "input", "L"),
            ("AP_SDO", "1", "output", "R"),
            ("~{AP_CS}", "12", "input", "L"),
            ("INT1", "4", "output", "R"),
            ("INT2/FSYNC", "9", "input", "L"),
            ("VDD", "8", "power_in", "T"),
            ("VDDIO", "5", "power_in", "T"),
            ("GND", "6", "power_in", "B"),
            # Datasheet: pin 7 says "Connect to GND", not "may". Typed
            # power_in so ERC complains if it is left unconnected.
            ("RESV_GND", "7", "power_in", "B"),
            ("RESV", "2", "passive", "B"),
            ("RESV", "3", "passive", "B"),
            ("RESV", "10", "passive", "B"),
            ("RESV", "11", "passive", "B"),
        ],
        note="Pin 7 must go to GND. Pin 9 to GND if FSYNC unused. VDD/VDDIO separate.",
    ),
    dict(
        name="ICM-45686",
        desc="TDK InvenSense 6-axis IMU, SPI/I2C, 14-pin LGA",
        source="TDK DS-000577 rev 1.0",
        keywords="IMU accelerometer gyroscope SPI",
        fp="Sensor_Motion:InvenSense_QFN-14_2.5x3mm_P0.5mm",
        pins=[
            ("AP_SCLK", "13", "input", "L"),
            ("AP_SDI", "14", "input", "L"),
            ("AP_SDO", "1", "output", "R"),
            ("~{AP_CS}", "12", "input", "L"),
            ("INT1", "4", "output", "R"),
            ("INT2/FSYNC", "9", "input", "L"),
            ("VDD", "8", "power_in", "T"),
            ("VDDIO", "5", "power_in", "T"),
            ("GND", "6", "power_in", "B"),
            # NOT the same as the ICM-42688-P: pins 10/11 are AUX1 here, and
            # pin 7's treatment is given as plain RESV. See PINOUTS.md.
            ("RESV", "7", "passive", "B"),
            ("RESV/AUX1_SDI", "2", "passive", "B"),
            ("RESV/AUX1_SCLK", "3", "passive", "B"),
            ("RESV/AUX1_CS", "10", "passive", "B"),
            ("RESV/AUX1_SDO", "11", "passive", "B"),
        ],
        note="Pins 10/11 differ from ICM-42688-P. Confirm pin 7 vs package figure.",
    ),
    dict(
        name="BMP388",
        desc="Bosch barometric pressure sensor, SPI/I2C, 10-pin LGA",
        source="Bosch BST-BMP388-DS001-07 rev 1.7",
        keywords="barometer pressure altimeter SPI I2C",
        fp="Sensor_Pressure:Bosch_LGA-10_2x2mm_P0.35mm",
        pins=[
            ("SCK", "2", "input", "L"),
            ("SDI", "4", "bidirectional", "L"),
            ("SDO", "5", "bidirectional", "R"),
            ("~{CSB}", "6", "input", "L"),
            ("INT", "7", "output", "R"),
            ("VDD", "10", "power_in", "T"),
            ("VDDIO", "1", "power_in", "T"),
            ("VSS", "3", "power_in", "B"),
            ("VSS", "8", "passive", "B"),
            ("VSS", "9", "passive", "B"),
        ],
        note="Interface pins high while VDDIO off destroys the part - see ARCHITECTURE.md.",
    ),
    dict(
        name="FM25V02A",
        desc="Infineon 256-Kbit SPI F-RAM, 8-pin SOIC/DFN",
        source="Cypress/Infineon 001-90865 Rev *I",
        keywords="FRAM NVRAM SPI nonvolatile",
        fp="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        pins=[
            ("SCK", "6", "input", "L"),
            ("SI", "5", "input", "L"),
            ("SO", "2", "output", "R"),
            ("~{CS}", "1", "input", "L"),
            ("~{WP}", "3", "input", "L"),
            ("~{HOLD}", "7", "input", "L"),
            ("VDD", "8", "power_in", "T"),
            ("VSS", "4", "power_in", "B"),
        ],
        note="WP must be tied to VDD if unused. DFN exposed pad: do NOT solder.",
    ),
]


def effects(size=1.27):
    return f"(effects (font (size {size} {size})))"


def prop(name, value, x, y, hide=False):
    """A symbol property.

    `hide` is a sibling of `(at ...)`, not something inside `(effects ...)`.
    Putting it in the wrong place makes KiCad reject the whole library with
    nothing more useful than "Unable to load library".
    """
    h = "\n\t\t\t(hide yes)" if hide else ""
    return (f'\t\t(property "{name}" "{value}"\n'
            f'\t\t\t(at {x} {y} 0){h}\n'
            f'\t\t\t{effects()}\n\t\t)')


def symbol(part):
    left = [p for p in part["pins"] if p[3] == "L"]
    right = [p for p in part["pins"] if p[3] == "R"]
    top = [p for p in part["pins"] if p[3] == "T"]
    bot = [p for p in part["pins"] if p[3] == "B"]

    h = max(len(left), len(right)) * MM + MM * 2
    w = max(MM * 8, (max(len(top), len(bot)) + 1) * MM)
    top_y = h / 2
    name = part["name"]

    o = [f'\t(symbol "{name}"',
         '\t\t(pin_names\n\t\t\t(offset 1.016)\n\t\t)',
         '\t\t(exclude_from_sim no)',
         '\t\t(in_bom yes)',
         '\t\t(on_board yes)',
         prop("Reference", "U", 0, round(top_y + 2.54, 2)),
         prop("Value", name, 0, round(-top_y - 2.54, 2)),
         prop("Footprint", part["fp"], 0, 0, hide=True),
         prop("Datasheet", part["source"], 0, 0, hide=True),
         prop("Description", part["desc"], 0, 0, hide=True),
         prop("ki_keywords", part["keywords"], 0, 0, hide=True),
         # The datasheet constraint travels with the symbol, so it shows up in
         # the schematic rather than only in a document nobody opens.
         prop("Note", part["note"], 0, 0, hide=True),
         f'\t\t(symbol "{name}_0_1"',
         f'\t\t\t(rectangle (start {-w/2} {top_y}) (end {w/2} {-top_y})',
         '\t\t\t\t(stroke (width 0.254)(type default))(fill (type background)))',
         '\t\t)',
         f'\t\t(symbol "{name}_1_1"']

    def pin(nm, num, typ, x, y, angle):
        return (f'\t\t\t(pin {typ} line (at {x} {y} {angle})(length 3.81)\n'
                f'\t\t\t\t(name "{nm}" {effects()})\n'
                f'\t\t\t\t(number "{num}" {effects()})\n\t\t\t)')

    y = top_y - MM
    for nm, num, typ, _ in left:
        o.append(pin(nm, num, typ, round(-w/2 - 3.81, 2), round(y, 2), 0))
        y -= MM
    y = top_y - MM
    for nm, num, typ, _ in right:
        o.append(pin(nm, num, typ, round(w/2 + 3.81, 2), round(y, 2), 180))
        y -= MM
    x = -(len(top) - 1) * MM / 2
    for nm, num, typ, _ in top:
        o.append(pin(nm, num, typ, round(x, 2), round(top_y + 3.81, 2), 270))
        x += MM
    x = -(len(bot) - 1) * MM / 2
    for nm, num, typ, _ in bot:
        o.append(pin(nm, num, typ, round(x, 2), round(-top_y - 3.81, 2), 90))
        x += MM

    o += ['\t\t)', '\t)']
    return "\n".join(o)


EXPECTED_PINS = {"ICM-42688-P": 14, "ICM-45686": 14, "BMP388": 10, "FM25V02A": 8}


def check():
    """Catch transcription slips in the tables above.

    Every pin of these packages is accounted for, so the numbers must be
    exactly 1..N with none missing and none repeated. A duplicated or skipped
    pin number is the most likely way to mistype a datasheet table, and it
    would otherwise produce a symbol that looks entirely reasonable.
    """
    problems = []
    for part in PARTS:
        nums = [int(p[1]) for p in part["pins"]]
        n = EXPECTED_PINS[part["name"]]
        missing = sorted(set(range(1, n + 1)) - set(nums))
        dupes = sorted({x for x in nums if nums.count(x) > 1})
        if len(nums) != n:
            problems.append(f"{part['name']}: {len(nums)} pins, expected {n}")
        if missing:
            problems.append(f"{part['name']}: pin numbers missing {missing}")
        if dupes:
            problems.append(f"{part['name']}: pin numbers repeated {dupes}")
        # Every part here has separate VDD and ground; a symbol with no power
        # pin means a whole column was dropped.
        if not any(p[2] == "power_in" for p in part["pins"]):
            problems.append(f"{part['name']}: no power_in pin")
    return problems


def main():
    problems = check()
    if problems:
        print("PIN TABLE PROBLEMS:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)

    body = "\n".join(symbol(p) for p in PARTS)
    OUT.write_text(
        # 20251024 is KiCad 10's symbol-library format - the same number the
        # stock libraries carry. Symbol libraries version independently of
        # schematics and boards.
        '(kicad_symbol_lib\n\t(version 20251024)\n'
        '\t(generator "jfox gen_fmu_symbols")\n'
        + body + "\n)\n", encoding="utf-8")
    print(f"  wrote {OUT.relative_to(REPO)}")
    for p in PARTS:
        print(f"    {p['name']:<14} {len(p['pins']):>2} pins   {p['source']}")


if __name__ == "__main__":
    main()
