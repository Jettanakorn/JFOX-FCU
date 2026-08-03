# JXK-1 — part numbering and traceability

JFOX Aircraft Co., Ltd. · programme **JXK-1**

How every drawing, board, assembly and delivered article is identified, and
why the format is the shape it is.

---

## 1. The two identifiers

They answer different questions and must not be conflated.

### Design identifier — *which design is this?*

```
JXK-1-1001-A
│     │    └──── revision, one letter
│     └───────── part number, 4 digits
└─────────────── programme
```

Appears on drawings, the BOM, the schematic title block and the silkscreen.
Every article built to the same design carries the same design identifier.

### Article identifier — *which physical unit is this?*

```
JXK-1-1001-A-0007
                └── serial, 4 digits
```

Marked on the individual unit. This is the one that appears in the build
record, the test log and the acceptance certificate.

---

## 2. Part number blocks

The digits are blocked so the number says what kind of thing it is without a
lookup:

| Block | Kind | Allocated |
|---|---|---|
| 1000–1099 | PCB **assemblies** (populated) | 1001 FCU card · 1002 backplane |
| 1100–1199 | **Bare boards** (fabrication) | 1101 FCU · 1102 backplane |
| 1200–1299 | Cable and harness assemblies | 1201 CAN harness · 1202 power feed |
| 1300–1399 | Mechanical (chassis, guides, standoffs) | — |
| 1400–1499 | Software and firmware loads | 1401 FCU flight firmware |
| 1500–1599 | Test equipment and fixtures | — |

An assembly and the bare board it is built on are **different part numbers**,
because they are different things: one is fabricated, the other is
fabricated *and* populated, and they have separate acceptance criteria.
JXK-1-1001 is built on JXK-1-1101.

---

## 3. Revision rules

A revision letter increments when the design changes. A **part number**
changes when the design changes in a way that breaks interchangeability.
That distinction is the entire value of the scheme:

> **If a unit at the new revision cannot replace a unit at the old revision
> in every position, in both directions, it is a NEW PART NUMBER — not a
> revision.**

| Change | Result |
|---|---|
| Silkscreen text, a fab note, a documentation fix | new revision |
| Component substitution, same footprint and spec | new revision |
| Extra decoupling capacitor, no interface change | new revision |
| Pinout change on the card edge | **new part number** |
| Board outline or mounting change | **new part number** |
| Rail voltage change | **new part number** |

Letters run A, B, C … skipping **I, O, Q, S, X and Z** — they are misread as
1, 0, 0, 5, X-as-cross-out and 2 on a marked board or a scanned drawing.
After Y, revisions become AA, AB, …

Revisions are never reused and never go backwards. A design that is
withdrawn and reinstated gets the next letter, not the old one.

---

## 4. Serial numbers

Four digits, allocated in sequence from 0001 per part number.

**A serial is never reset when the revision changes, and never reused.**
JXK-1-1001-A-0007 and JXK-1-1001-B-0007 do not exist together — unit 0007
was built to revision A, and if it is later modified up to revision B its
record says so and its identifier becomes JXK-1-1001-B-0007. The serial
follows the physical article for its life; the revision says what standard
it currently conforms to.

This is what makes the DO-254 §10.3 correlation possible: *"a correlation
between hardware detailed design data and the as-built hardware item"*. A
serial that restarts at each revision cannot support it.

---

## 5. Machine-readable marking

Per MIL-STD-130 **UII Construct 2** and IPC-1782, the 2D Data Matrix encodes
the enterprise identifier, the part number and the serial:

```
    <ENTERPRISE> <PART NUMBER> <SERIAL>
```

> **JFOX has no CAGE code.** CAGE is issued by the US DLA and applies to US
> defence suppliers. Until one is held — or an ISO/IEC 15459 issuing-agency
> code is registered — the enterprise field is a placeholder and the marking
> is **not** MIL-STD-130 conformant. Recorded as an open item rather than
> printed as though it were compliant, because a marking that looks like a
> UII and is not one is worse than none: it will be scanned and trusted.

Marking method and location are not yet specified. Laser-etched Data Matrix
on the bare board is the usual answer for a card that lives in a cage, since
a label peels and a card edge is handled.

---

## 6. Currently allocated

| Part number | Rev | Description |
|---|---|---|
| JXK-1-1001 | A | FCU card assembly, 40 × 90 mm, 6-layer |
| JXK-1-1101 | A | FCU bare board |
| JXK-1-1002 | A | Backplane assembly, 100 × 100 mm, 8-layer |
| JXK-1-1102 | A | Backplane bare board |
| JXK-1-1401 | — | FCU flight firmware — not yet baselined |

All at revision **A**: nothing has been released, so nothing has been
revised. The first revision letter is issued at the first release baseline,
not at the first commit.

---

## 7. Where the identifier appears

| Place | Form | Status |
|---|---|---|
| Schematic title block | design identifier | **generated** |
| Board silkscreen | design identifier | **generated** |
| Fabrication drawing | design + bare board number | not yet drawn |
| Assembly drawing | design identifier | not yet drawn |
| Physical unit | article identifier + Data Matrix | not yet specified |
| Build record | article identifier | no build record yet |

The generated entries come from `hardware/tools/part_numbers.py`, which is
the single definition. Anything that types a part number by hand will
eventually disagree with it.

---

## 8. Open items

| # | Item | Blocking |
|---|---|---|
| 1 | No CAGE or ISO/IEC 15459 code — marking cannot be MIL-STD-130 conformant | before delivery |
| 2 | Marking method and location unspecified | before first article |
| 3 | No Hardware Configuration Index yet (DO-254 §10.4) | before certification |
| 4 | No build record, so no article identifiers exist | before first article |
| 5 | Firmware load 1401 not baselined against a part number | before flight |

---

Sources: [DO-254 traceability](https://www.aldec.com/en/support/resources/documentation/faq/1687) ·
[MIL-STD-130 and UII](https://scanbot.io/blog/iuid-and-mil-std-130n-explained/) ·
[IPC-1782](https://pcbsync.com/ipc-1782/)
