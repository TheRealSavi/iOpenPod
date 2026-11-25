/* SPDX-License-Identifier: GPL-3.0-only */
.syntax unified
.cpu arm926ej-s
.arm
.text
.balign 4
.global iop_mono_mix_finish
.type iop_mono_mix_finish,%function
iop_mono_mix_finish:
    /* Final mixer epilogue. r8 is the returned PCM buffer and r7 the
     * effective frame count. Both output drivers share this callback. */
    ldr r1, =iop_mono_enabled
    ldr r1, [r1]
    cmp r1, #0
    beq .Lfinish
    cmp r7, #0
    beq .Lfinish
    cmp r7, #1024              /* Each native refill buffer is 4096 bytes. */
    bhi .Lfinish
.Lframe:
    ldrsh r1, [r8]
    ldrsh r2, [r8, #2]
    add r1, r1, r2
    add r1, r1, r1, lsr #31    /* Signed average rounded towards zero. */
    asr r1, r1, #1
    strh r1, [r8], #2
    strh r1, [r8], #2
    subs r7, r7, #1
    bne .Lframe
.Lfinish:
    strb r6, [r4, #0x54]
    pop {r1-r9, pc}
.size iop_mono_mix_finish, . - iop_mono_mix_finish
