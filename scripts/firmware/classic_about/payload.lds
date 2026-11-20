ENTRY(iop_copy_entry)
SECTIONS {
    . = IOP_MOD_BASE;
    __payload_start = .;
    .text : { KEEP(*(.text.copy_entry)) *(.text*) *(.rodata*) }
    .identity : { KEEP(*(.iop.identity)) KEEP(*(.iop.version)) }
    .data : { *(.data*) }
    . = ALIGN(4);
    __payload_end = .;
    __payload_copy_bytes = __payload_end - __payload_start;
    __payload_zero_start = .;
    .scratch (NOLOAD) : { *(.iop.scratch) }
    .bss (NOLOAD) : { *(.bss*) *(COMMON) }
    . = ALIGN(4);
    __payload_zero_end = .;
    __payload_limit = ALIGN(0x1000);
    ASSERT(__payload_limit - __payload_start <= IOP_MOD_MEMORY_BYTES, "Mod payload exceeds its qualified RAM region")
    /DISCARD/ : { *(.comment) *(.ARM.attributes) *(.ARM.exidx*) *(.ARM.extab*) }
}
