SECTIONS
{
    .bds_bridge 0x1480 : { *(.bds_bridge) }
    ASSERT(SIZEOF(.bds_bridge) <= 128, "Bds bridge exceeds existing debug space")
    /DISCARD/ : { *(.comment) *(.ARM.attributes) }
}
