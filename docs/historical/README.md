# Historical documents (2025-12-30)

Superseded status documents and flashing scripts from the project's first
bring-up effort, kept for the record rather than for use.

**Do not follow these.** The current instructions are
[`BUILD_AND_FLASH.md`](../../BUILD_AND_FLASH.md) at the repo root.

They are archived rather than deleted for two reasons. They record what was
actually true at the time — which board was flashed, with what, and what was
verified — and that history is what corrected a later, wrong claim that no
hardware had ever been available. And the protocol detail they contain was
reverse-engineered against a real board, so it is worth more than a summary.

| File | What it was |
|---|---|
| `VERIFICATION_STATUS.md`, `V2_STATUS.md` | The record that `jfox-fcu` really was flashed and ran on real hardware |
| `BUILD_AND_FLASH_SUCCESS.md`, `FLASHING.md` | Earlier build/flash write-ups |
| `PROGRESS_SUMMARY.md`, `QUICK_FIX_GUIDE.md` | Status snapshots |
| `FLASH_INSTRUCTIONS.txt`, `FLASH_V2_INSTRUCTIONS.txt` | Step lists for those scripts |
| `px4_flash_simple.py` | First PX4-bootloader attempt; **omits the GET_CRC step**, so the bootloader refuses to boot the result |
| `px4_upload.py`, `px4_reboot_and_flash.py` | Other attempts along the way |

The working script is `px4_flash_complete.py`, still at the repo root — it is
the one that adds the `GET_CRC` verification the bootloader requires before it
will jump to new firmware. `docs/MISSION_PLANNER_ANALYSIS.md` explains why the
simpler scripts here did not work, and is kept out of this directory because
it is reference material, not a status doc.
