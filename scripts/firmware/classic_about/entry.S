.syntax unified
.cpu arm926ej-s
.arm
.section .text.copy_entry,"ax",%progbits
.global iop_copy_entry
.type iop_copy_entry,%function
iop_copy_entry:
    /* Invoked in the original loader buffer after native region relocation.
     * ADR and literal accesses remain valid before this block relocates itself.
     * The native copy routine's r4-r6/LR frame remains on the stack.
     */
    adr r0, iop_copy_entry
    ldr r1, =__payload_start
    ldr r2, =__payload_copy_bytes
    /* Large appended payloads can overlap their final RAM location. The code
     * being executed stays below the destination for the backward-copy case.
     */
    cmp r0, r1
    bhs 1f
    add r0, r0, r2
    add r1, r1, r2
2:
    ldr r3, [r0, #-4]!
    str r3, [r1, #-4]!
    subs r2, r2, #4
    bne 2b
    b 3f
1:
    ldr r3, [r0], #4
    str r3, [r1], #4
    subs r2, r2, #4
    bne 1b
3:
    /* Initialize our zero-filled storage independently of Apple's BSS. */
    ldr r0, =__payload_zero_start
    ldr r1, =__payload_zero_end
    mov r2, #0
4:
    cmp r0, r1
    strlo r2, [r0], #4
    blo 4b
#ifdef IOP_BOOT_REPORT
    /* The final mod image is now resident and its BSS is zeroed. Measure NOR
     * before entering Apple's OS, before tasks or hardware owners exist.
     */
    ldr r3, =iop_boot_report_capture
    blx r3
#endif
    ldr r0, =0x22000000
    pop {r4, r5, r6, lr}
    bx r0
    .ltorg
.size iop_copy_entry, .-iop_copy_entry
