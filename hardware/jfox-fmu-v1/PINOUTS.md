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
| ICM-45686 | **Verified** — TDK DS-000577, Revision 1.0 |
| FM25V02A | **Verified** — Cypress/Infineon 001-90865 Rev *I (Dec 2018) |

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

## ICM-45686 — 6-axis IMU, 14-pin LGA

TDK InvenSense, `DS-000577` Revision 1.0, section 4.1 "Pin Out Diagram and
Signal Description". Extracted across the pages that section spans.

| Pin | Name | SPI 4-wire use |
|---|---|---|
| 1 | AP_SDO / AP_AD0 | **MISO** |
| 2 | RESV / AUX1_SDIO / AUX1_SDI / MAS_DA | no connect, or VDDIO, or GND |
| 3 | RESV / AUX1_SCLK / MAS_CLK | no connect, or VDDIO, or GND |
| 4 | INT1 / INT | interrupt 1 — DRDY |
| 5 | VDDIO | IO supply |
| 6 | GND | ground |
| 7 | RESV | see note |
| 8 | VDD | supply |
| 9 | INT2 / FSYNC / CLKIN | interrupt 2 / frame sync / external clock |
| 10 | RESV / AUX1_CS | no connect, or VDDIO, or GND |
| 11 | RESV / AUX1_SDO | no connect, or VDDIO, or GND |
| 12 | AP_CS | **CS** |
| 13 | AP_SCL / AP_SCLK | **SCK** |
| 14 | AP_SDA / AP_SDIO / AP_SDI | **MOSI** |

**Do not assume this matches the ICM-42688-P.** The two are the same family
and the same 14-pin package, and pins 1 and 12–14 do line up — but pins 10 and
11 are `RESV / AUX1_CS` and `RESV / AUX1_SDO` here against plain `RESV` on the
42688-P. Close enough to look interchangeable, different enough to matter.

Every RESV pin on this part carries internal pull-ups that the datasheet says
to disable in software when the corresponding interface is active. Pin 7's
treatment is given as plain `RESV` in the table rather than the 42688-P's
explicit "Connect to GND"; **confirm pin 7 against the package figure before
committing the footprint**, since the two parts differ elsewhere.

## FM25V02A — 256 Kbit SPI F-RAM, 8-pin SOIC or DFN

Cypress/Infineon, document `001-90865` Rev *I, revised 7 December 2018,
"Pinouts" Figure 1/2 and "Pin Definitions". Same numbering for both packages.

| Pin | Name | Note |
|---|---|---|
| 1 | CS | active low |
| 2 | SO | serial output |
| 3 | WP | active low write protect |
| 4 | VSS | ground |
| 5 | SI | serial input |
| 6 | SCK | serial clock, DC–40 MHz |
| 7 | HOLD | active low, weak internal pull-up |
| 8 | VDD | 2.0–3.6 V |

Two things the datasheet is explicit about:

- **WP must be tied to VDD if unused.** Not optional — write protection of the
  status register depends on it, and the rest of the protection scheme is
  controlled through that register.
- On the DFN package the **exposed pad is not connected to the die and should
  not be soldered.** Pouring ground under it and reflowing it, which is the
  reflex for an exposed pad, is wrong here.

Chosen over the FM25V01 on the current board for four times the capacity at
the same pinout — parameters, calibration and now BIT history have to fit.

## Not yet verified

None — all four parts are verified above.

To add another part once its datasheet PDF is in
`hardware/jfox-fmu-v1/datasheets/`:

```bash
python hardware/tools/extract_datasheet_pins.py hardware/jfox-fmu-v1/datasheets/<part>.pdf
```

It scores pages for pin-table content and reports the manufacturer's document
number, so the new entry can carry real provenance. Where a datasheet spreads
its pin table over several pages, or renders it as a figure, fall back to
rendering the pages and reading them - `pypdfium2` at scale 3.0 is legible.
