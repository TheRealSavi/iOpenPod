.syntax unified
.cpu arm926ej-s
.thumb
.section .text.crc32,"ax",%progbits
.global unsigned_crc32
.thumb_func
unsigned_crc32:
    push {r4, lr}
    movs r2, #0
    mvns r2, r2
    adr r4, crc_table
    cmp r1, #0
    beq 2f
1:  ldrb r3, [r0]
    adds r0, #1
    eors r2, r3
    movs r3, r2
    lsls r3, r3, #24
    lsrs r3, r3, #22
    lsrs r2, r2, #8
    ldr r3, [r4, r3]
    eors r2, r3
    subs r1, #1
    bne 1b
2:  mvns r0, r2
    pop {r4, pc}
.balign 4
crc_table:
    .set index, 0
    .rept 256
      .set value, index
      .rept 8
        .if value & 1
          .set value, (value >> 1) ^ 0xedb88320
        .else
          .set value, value >> 1
        .endif
      .endr
      .word value
      .set index, index + 1
    .endr
