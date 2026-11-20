/* SPDX-License-Identifier: GPL-3.0-only */
.syntax unified
.cpu arm926ej-s
.arm
.section .start,"ax"
.global _start
_start:
 msr cpsr_c, #0xd3
 ldr sp, =0x2201f000
 ldr r3, =100000
1: mrc p15, 0, APSR_nzcv, c7, c14, 3
 beq 2f
 subs r3, r3, #1
 bne 1b
3: b 3b /* Bounded cache maintenance failed before any flash access. */
2: mov r0, #0
 mcr p15, 0, r0, c7, c10, 4
 mrc p15, 0, r1, c1, c0, 0
 bic r1, r1, #0x1000
 bic r1, r1, #5
 mcr p15, 0, r1, c1, c0, 0
 mcr p15, 0, r0, c7, c5, 0
 mcr p15, 0, r0, c8, c7, 0
 ldr r1, =__bss_start
 ldr r2, =__bss_end
4: cmp r1,r2
 strlo r0,[r1],#4
 blo 4b
 bl main
5: b 5b
.ltorg
