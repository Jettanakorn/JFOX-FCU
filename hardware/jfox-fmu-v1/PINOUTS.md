# Verified pinouts

Pin assignments for the parts KiCad has no stock symbol for, taken from
manufacturers' own datasheets. **A wrong pin number here is silently fatal** —
it produces a schematic that passes ERC, a board that fabricates cleanly, and
a sensor that never answers. So each entry records where it came from, and
anything not yet checked says so rather than being filled in from memory.

| Part | Status |
|---|---|
| BMP388 | **Verified** — BST-BMP388-DS001-07, Revision 1.7 (11/2020) |
| ICM-42688-P | **Not verified** — see below |
| ICM-45686 | **Not verified** |
| FM25V02 | **Not verified** |

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

`ICM-42688-P` and `ICM-45686` (TDK InvenSense) and `FM25V02` (Infineon).

TDK serves its datasheet PDFs behind a 403 to direct fetches, and the
InvenSense mirror redirects to a navigation page. These need the PDFs
supplied locally, or fetching through a browser.

**These three are blocking the sensor sheet.** The MCU, power, CAN and
connector sheets do not depend on them and can be captured first — see
`ARCHITECTURE.md` for which parts have stock KiCad symbols.

To add one once its datasheet is in hand, extract rather than retype:

```bash
python hardware/tools/extract_datasheet_pins.py <datasheet.pdf>
```
