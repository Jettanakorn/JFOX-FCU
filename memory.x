/* memory.x - Updated for PX4FMUv2.4.5 with Bootloader Offset */

MEMORY
{
    /* 2MB Flash minus 16KB Bootloader area */
    /* Origin shifted from 0x08000000 to 0x08004000 */
    FLASH (rx)  : ORIGIN = 0x08004000, LENGTH = 2032K

    /* 192KB main SRAM */
    RAM (rwx)   : ORIGIN = 0x20000000, LENGTH = 192K

    /* 64KB core-coupled memory: CPU-only, not reachable by DMA. See ccmram.x
       for the .ccmram section this region backs. */
    CCMRAM (rwx) : ORIGIN = 0x10000000, LENGTH = 64K
}