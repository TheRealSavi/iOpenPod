/* SPDX-License-Identifier: GPL-3.0-only */

#include "record.h"
#define WORD(a) (*(volatile uint32_t *)(a))
#define CALL0(a) ((void (*)(void))(a))()
#define CALL1(a, x) ((void (*)(uint32_t))(a))(x)
#define CALL2(a, x, y) ((void (*)(uint32_t, uint32_t))(a))(x, y)
#define CALL3(a, x, y, z) ((void (*)(uint32_t, uint32_t, uint32_t))(a))(x, y, z)

extern void verify_rom_mapping(void);

void enter_dfu(void)
{
    verify_rom_mapping();
    /* Same context/config locations as ROM main + DFUBoot, below its SVC stack. */
    const uint32_t context = 0x2202653c;
    const uint32_t config = 0x220264f0;
    WORD(0x2203fff8) = context;
    WORD(0x2203fffc) = 0x22028000;
    CALL0(0x200017ac); /* Read clock configuration into the context. */
    CALL0(0x200011bc); /* Initialize interrupt dispatch. */
    CALL1(0x2000147c, 10);
    CALL1(0x2000147c, 0);
    CALL1(0x2000147c, 45);
    CALL1(0x200031dc, config); /* Populate stock DFU descriptors. */
    WORD(config) = context;
    WORD(config + 4) = 0x22028000;
    WORD(config + 0x28) = 0x20000;
    WORD(config + 0x2c) = 0x22000000;
    WORD(config + 0x34) = 0x00010101;
    WORD(config + 0x38) = 1;
    WORD(context + 0x738) = config;

    /* Enter the USB branch of ROM DFUBoot, skipping all boot-media selection. */
    CALL2(0x2000106c, 19, 0x20003790);
    CALL3(0x20001198, 0, 2, 0x20003798);
    CALL1(0x200035a8, config);
    CALL1(0x20000ef0, 19);
    CALL1(0x20000ef0, 33);
    CALL2(0x20000fd4, 0, 2);
    CALL0(0x200090e8);
    RECORD->returns++;
    verify_rom_mapping();
    /* USB requests can run once the complete return state is ready. */
    asm volatile("msr cpsr_c, #0x13" ::: "memory");
    CALL0(0x200036c8);
    for (;;)
        ;
}
