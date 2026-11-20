/* SPDX-License-Identifier: GPL-3.0-only */
.syntax unified
.cpu arm926ej-s
.arm
.text
.balign 4
.global iop_preferences_hook
.type iop_preferences_hook,%function
iop_preferences_hook:
    push {r4, lr}
    ldr r12, =0x0809c69c
    blx r12
    mov r4, r0
    bl iop_appearance_load
    mov r0, r4
    pop {r4, pc}
.global iop_appearance_clock_tick
.type iop_appearance_clock_tick,%function
iop_appearance_clock_tick:
    /* Only the clock model's own timer event in the native UI queue. Keep
     * Apple's refresh/rearm and return value, then evaluate Auto appearance. */
    push {r4, lr}
    ldr r12, =0x0817d6e8
    blx r12
    mov r4, r0
    bl iop_appearance_poll
    mov r0, r4
    pop {r4, pc}
.global iop_resource_get_original
.type iop_resource_get_original,%function
iop_resource_get_original:
    /* Relocate the two overwritten non-PC-relative entry instructions. */
    push {r3, r4, r5, r6, r7, lr}
    mov r5, r1
    ldr pc, =0x08268b6c
.ltorg
