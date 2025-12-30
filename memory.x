/* memory.x - Updated for PX4FMUv2.4.5 with Bootloader Offset */

MEMORY
{
    /* 2MB Flash minus 16KB Bootloader area */
    /* Origin shifted from 0x08000000 to 0x08004000 */
    FLASH (rx)  : ORIGIN = 0x08004000, LENGTH = 2032K

    /* 192KB main SRAM */
    RAM (rwx)   : ORIGIN = 0x20000000, LENGTH = 192K
}