ENTRY(_start)
SECTIONS {
 . = 0x2200030c;
 .text : { *(.start) *(.text*) *(.rodata*) }
 .data : { *(.data*) }
 . = ALIGN(4); __payload_end = .;
 .bss (NOLOAD) : { __bss_start = .; *(.bss*) *(COMMON) . = ALIGN(4); __bss_end = .; }
 ASSERT(. < 0x2201e000, "payload and scratch must leave 4KiB stack + receipt headroom")
}
