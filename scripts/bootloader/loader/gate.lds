SECTIONS
{
    .native_failure 0x6d0 : { *(.native_failure) }
    .native_success 0x6d4 : { *(.native_success) }
    .native_header 0x7fa : { *(.native_header) }
    .mod 0x1560 : { *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.comment) *(.ARM.attributes) *(.ARM.exidx*) }
}
