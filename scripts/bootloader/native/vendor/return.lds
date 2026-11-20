ENTRY(return_start)
SECTIONS {
 . = 0x22010000; .text : { *(.start) *(.text*) *(.rodata*) }
 .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) }
 ASSERT(SIZEOF(.bss) == 0, "return BSS")
 ASSERT(. < 0x22014000, "return size")
}
