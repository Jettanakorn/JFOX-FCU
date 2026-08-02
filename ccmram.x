/* ccmram.x - extra section for core-coupled memory (CCM), spliced into
   cortex-m-rt's default link.x layout. Anything tagged
   `#[link_section = ".ccmram"]` lands in the CCMRAM region defined in
   memory.x. NOLOAD: CCM is zero-initialized by hardware reset behavior is
   NOT guaranteed the way .bss is by cortex-m-rt, so code placing data here
   must not assume a zeroed initial state - this is scratch memory, not
   another .bss. */

SECTIONS
{
    .ccmram (NOLOAD) : ALIGN(4)
    {
        *(.ccmram .ccmram.*);
    } > CCMRAM
} INSERT AFTER .bss;
