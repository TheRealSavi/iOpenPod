SECTIONS {
    .mod 0x560 : { *(.text*) *(.rodata*) }
    /DISCARD/ : { *(.comment) *(.ARM.attributes) *(.ARM.exidx*) }
}
