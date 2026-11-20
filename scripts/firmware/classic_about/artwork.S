/* SPDX-License-Identifier: GPL-3.0-only */
.syntax unified
.cpu arm926ej-s
.arm
.text
.balign 4
.global iop_artwork_format
.type iop_artwork_format,%function
iop_artwork_format:
    /* Replaces ldrh r0,[r4,#0xb8] at 0x081001f0. r4 is BitmapView.
     * A dynamic Now Playing image lives in the borrowed context, not the
     * embedded static bitmap. Its stale mask format can make RGB565 artwork
     * render invisibly in mode 0x21. Read the actual source format instead.
     * Preserve all other registers; the next native instruction sets flags.
     * Static sources and other dynamic properties retain their original path.
     */
    push {r1, lr}
    ldr r0, [r4, #0x40]
    ldr r1, =0x44726177
    cmp r0, r1
    bne 1f
    ldr r0, [r4, #0x44]
    ldr r1, =0x7f05
    cmp r0, r1
    bne 1f
    ldr r0, [r4, #0x15c]
    cmp r0, #0
    beq 1f
    ldr r0, [r0, #0x1c]
    cmp r0, #0
    beq 1f
    ldrh r0, [r0, #0x14]
    pop {r1, pc}
1:
    ldrh r0, [r4, #0xb8]
    pop {r1, pc}
.size iop_artwork_format, .-iop_artwork_format
.ltorg
