# Verified pinouts

Pin assignments for the parts KiCad has no stock symbol for, taken from
manufacturers' own datasheets. **A wrong pin number here is silently fatal** —
it produces a schematic that passes ERC, a board that fabricates cleanly, and
a sensor that never answers. So each entry records where it came from, and
anything not yet checked says so rather than being filled in from memory.

| Part | Status |
|---|---|
| BMP388 | **Verified** — BST-BMP388-DS001-07, Revision 1.7 (11/2020) |
| ICM-42688-P | **Verified** — TDK DS-000347, v1.6 |
| ICM-45686 | **Not verified** |
| FM25V02 | **Not verified** |

Datasheets are kept in `datasheets/` where licensing allows, so the extraction
is repeatable.

## ICM-42688-P — 6-axis IMU, 14-pin LGA

TDK InvenSense, document `DS-000347` v1.6. Extracted from the datasheet PDF.

| Pin | Name | SPI 4-wire use |
|---|---|---|
| 1 | AP_SDO / AP_AD0 | **MISO** (I²C: address LSB) |
| 2 | RESV | no connect, or GND |
| 3 | RESV | no connect, or GND |
| 4 | INT1 / INT | interrupt 1 — DRDY to the MCU |
| 5 | VDDIO | IO supply |
| 6 | GND | ground |
| 7 | RESV | **must connect to GND** |
| 8 | VDD | supply |
| 9 | INT2 / FSYNC / CLKIN | **tie to GND if FSYNC unused** |
| 10 | RESV | no connect, or GND |
| 11 | RESV | no connect, or GND |
| 12 | AP_CS | **CS** (tie to VDDIO if using I²C) |
| 13 | AP_SCL / AP_SCLK | **SCK** |
| 14 | AP_SDA / AP_SDIO / AP_SDI | **MOSI** (4-wire) |

Three details that are easy to get wrong and that the datasheet is explicit
about:

- Pin **7** is the one RESV pin that says *"Connect to GND"* rather than *"No
  Connect or Connect to GND"*. Treat it as mandatory.
- Pin **9** must go to GND when FSYNC is not used — leaving it floating is not
  an option the datasheet offers.
- VDD (8) and VDDIO (5) are separate supplies, as on the BMP388.

## BMP388 — barometer, 10-pin LGA

Bosch Sensortec, document `BST-BMP388-DS001-07`, Revision 1.7, section 6.1
"Pin-out", Table 50. Extracted from the datasheet PDF, not transcribed.

| Pin | Name | Type | SPI 4-wire | I²C |
|---|---|---|---|---|
| 1 | VDDIO | Supply | digital interface supply | |
| 2 | SCK | In | SCK | SCL |
| 3 | VSS | Supply | GND | |
| 4 | SDI | In/Out | SDI (MOSI) | SDA |
| 5 | SDO | In/Out | SDO (MISO) | SA0 (address select) |
| 6 | CSB | In | CSB | CSB (tie high for I²C) |
| 7 | INT | Out | interrupt to host, or DNC | |
| 8 | VSS | Supply | GND | |
| 9 | VSS | Supply | GND | |
| 10 | VDD | Supply | analog supply | |

Note VDD (pin 10) and VDDIO (pin 1) are **separate supplies** and may be
energised in any order. Three separate ground pins (3, 8, 9) — all must be
connected.

### Hazard this datasheet turned up

> "Holding any interface pin (SDI, SDO, SCK or CSB) at a logical high level
> when VDDIO is switched off can permanently damage the device due caused by
> excessive current flow through the ESD protection diodes."
> — BST-BMP388-DS001-07 §3.2

This lands directly on the per-bus sensor power switching in
`ARCHITECTURE.md`. Being able to power-cycle a wedged sensor is worth having,
but the firmware **must drive that bus's SPI lines low before removing its
supply**, or the recovery mechanism destroys the part it is trying to
recover. Recorded as a firmware requirement in the architecture spec.

The same ESD-diode structure is normal for this class of part, so assume the
constraint applies to the IMUs too until each datasheet says otherwise.

## Not yet verified

`ICM-45686` (TDK InvenSense) and `FM25V02` (Infineon).

TDK serves its datasheet PDFs behind a 403 to direct fetches; the ICM-42688-P
above was obtained by letting a browser download it. The same route works for
the ICM-45686. **These two block the sensor sheet only** - the MCU, power, CAN
and connector sheets do not depend on them.

To add one once its PDF is in hand:

```bash
python hardware/tools/extract_datasheet_pins.py hardware/jfox-fmu-v1/datasheets/<part>.pdf
```

It scores pages for pin-table content and reports the manufacturer's document
number, so the entry above it can carry real provenance.
