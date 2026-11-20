/* SPDX-License-Identifier: GPL-3.0-only */
.syntax unified
.cpu arm926ej-s
.arm
.section .start,"ax"

.global return_start
return_start:
    msr cpsr_c, #0xd3
1:  mrc p15, 0, r15, c7, c14, 3
    bne 1b
    mov r0, #0
    mcr p15, 0, r0, c7, c10, 4
    mrc p15, 0, r0, c1, c0, 0
    bic r0, r0, #0x1000
    bic r0, r0, #5
    bic r0, r0, #0x2000
    mcr p15, 0, r0, c1, c0, 0
    mov r0, #0
    mcr p15, 0, r0, c7, c5, 0
    mcr p15, 0, r0, c8, c7, 0

    /* Apple's ROM wrapper clears MIUCON[2:0] to map ROM at zero. */
    ldr r0, =0x38100000
    ldr r1, [r0]
    bic r1, r1, #7
    str r1, [r0]
    ldr r1, [r0]
    mov r0, #0
    mcr p15, 0, r0, c7, c10, 4
    b cold_init
    .ltorg

.global verify_rom_mapping
verify_rom_mapping:
    mov r0, #0
    ldr r1, =0x20000000
2:  ldr r2, [r0], #4
    ldr r3, [r1], #4
    cmp r2, r3
    bne mapping_failed
    cmp r0, #0xc0
    blo 2b
    bx lr
mapping_failed:
5:  b 5b
    .ltorg

cold_init:
    /* Filled from the verified device ROM before launch. */
    .word 0xeafffffe
    .asciz "REPRISE-ROM"
    .space 1024 - 16

    /* The helper occupied IRAM1, including the ROM's stacks and USB state. */
    ldr r0, =0x22020000
    ldr r1, =0x22040000
    mov r2, #0
3:  str r2, [r0], #4
    cmp r0, r1
    blo 3b
    msr cpsr_c, #0xd1
    ldr sp, =0x22022c80
    msr cpsr_c, #0xd2
    ldr sp, =0x22022c60
    msr cpsr_c, #0xd7
    ldr sp, =0x22020860
    msr cpsr_c, #0xdb
    ldr sp, =0x22020840
    msr cpsr_c, #0xd3
    ldr sp, =0x220264e8
    bl enter_dfu
4:  b 4b
    .ltorg
