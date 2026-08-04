/* memory.x - PX4 FMUv2 family (2.4.5 / 2.4.8) with bootloader offset */

MEMORY
{
    /* Flash bank 1 only: 1024K - 16K bootloader = 1008K.
       Origin shifted from 0x08000000 to 0x08004000 for the PX4 bootloader.

       Deliberately NOT the part's full 2MB. The STM32F427 carries a
       documented erratum on the second flash bank in silicon revisions
       before rev 3, and FMUv2-family boards - especially 2.4.8 clones,
       which are frequently older stock - ship with mixed revisions. PX4
       handles this by splitting its targets: fmu-v2 is limited to 1MB and
       only fmu-v3 uses 2MB, gated on the board revision the bootloader
       reports.

       This project cannot read that revision (no debug probe, and the
       bootloader is not reachable in practice - see BUILD_AND_FLASH.md), so
       it takes the safe half. The cost is nothing today: the largest binary
       here is jfox-fcu-flight at ~61KB, about 6% of what remains. Raise this
       to 2032K only after confirming rev 3 silicon on the specific board. */
    FLASH (rx)  : ORIGIN = 0x08004000, LENGTH = 1008K

    /* 192KB main SRAM */
    RAM (rwx)   : ORIGIN = 0x20000000, LENGTH = 192K

    /* 64KB core-coupled memory: CPU-only, not reachable by DMA. See ccmram.x
       for the .ccmram section this region backs. */
    CCMRAM (rwx) : ORIGIN = 0x10000000, LENGTH = 64K
}