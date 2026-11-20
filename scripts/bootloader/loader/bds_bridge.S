.syntax unified
.cpu arm926ej-s
.thumb
.section .bds_bridge,"ax",%progbits
.global header_bridge
.thumb_func
header_bridge:
    push {r4, lr}
    ldr r2, [sp, #0x1c] /* Actual header read count: old SP+0x14. */
    movs r3, #8
    lsls r3, r3, #8
    cmp r2, r3
    bne header_bad
    ldr r0, [sp, #0x44] /* ROM protocol: old SP+0x3c. */
    ldr r1, [sp, #0x28] /* Header: old SP+0x20. */
    ldrb r2, [r1, #7]
    cmp r2, #0x7f
    bne 1f
    movs r2, #1
    str r2, [sp, #0x68] /* Reject unsigned errors; do not take dev fallback. */
    ldr r2, [sp, #0x54] /* Media block size: old SP+0x4c. */
    b header_call
1:  movs r2, #1
header_call:
    ldr r4, [r0, #8]
    ldr r3, [sp, #0x5c] /* File byte length: old SP+0x54. */
    blx r4
    pop {r4, pc}
header_bad:
    movs r0, #1
    str r0, [sp, #0x68]
    lsls r0, r0, #31
    adds r0, #3
    pop {r4, pc}

/* Called at native 0x3de before body allocation and Read. The virtual file
 * length includes Apple's extra block/alignment padding. Custom bodies are
 * allocated and read using their already validated, bounded declared size. */
.global allocation_bridge
.thumb_func
allocation_bridge:
    ldr r0, [sp, #0x20]
    ldrb r1, [r0, #7]
    cmp r1, #0x7f
    bne allocation_legacy
    ldr r0, [r0, #12]
    bx lr
allocation_legacy:
    ldr r1, [sp, #0x14]
    ldr r0, [sp, #0x54]
    subs r0, r0, r1
    bx lr

.global body_bridge
.thumb_func
body_bridge:
    push {r4, r5, r6, lr}
    movs r4, r3 /* Preserve original selected body callback. */
    ldr r2, [sp, #0x34] /* Body: old SP+0x24. */
    ldr r1, [sp, #0x30] /* Header: old SP+0x20. */
    ldrb r3, [r1, #7]
    cmp r3, #0x7f
    bne 2f
    ldr r3, [sp, #0x28] /* Actual body read count: old SP+0x18. */
    ldr r5, [r1, #12]
    cmp r3, r5
    bne body_bad
2:  blx r4
    pop {r4, r5, r6, pc}
body_bad:
    movs r0, #1
    lsls r0, r0, #31
    adds r0, #3
    pop {r4, r5, r6, pc}

#ifdef SHARED_CLASSIC
/* After successful body validation and the native SysInfo copy. Only the
 * common ABI receives 2.0.5's compatibility fields; actual SysCfg is untouched.
 */
.global context_bridge
.thumb_func
context_bridge:
    push {r2, r3, r4, lr}
    ldr r3, [sp, #0x4c] /* Original SP + 0x3c: relocated ROM protocol. */
    ldr r3, [r3, #8]    /* Relocated unsigned_header_gate pointer. */
    adds r3, #CONTEXT_OFFSET
    ldr r0, [sp, #0x30] /* Original SP + 0x20: validated header. */
    blx r3
    ldr r1, =0x2203ff18
    ldr r0, [sp, #0x6c]
    pop {r2, r3, r4, pc}
    .ltorg
#endif
