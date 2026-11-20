.syntax unified
.cpu arm926ej-s
.thumb
.section .native_header,"ax",%progbits
.global native_header
.thumb_func
native_header:
    bx lr
.section .native_failure,"ax",%progbits
.global native_failure
.thumb_func
native_failure:
    bx lr
.section .native_success,"ax",%progbits
.global native_success
.thumb_func
native_success:
    bx lr
.section .text.body_dispatch,"ax",%progbits
.global body_dispatch
.thumb_func
body_dispatch:
    push {r4, lr}
    movs r4, r0
    bl unsigned_body_gate
    ldrb r1, [r4, #7]
    cmp r1, #0x7f
    bne 1f
    cmp r0, #0
    beq 2f
    pop {r3, r4} /* Saved original R4 then return address, in register order. */
    movs r4, r3
    bl native_success
2:  pop {r3, r4}
    movs r4, r3
    bl native_failure
1:  pop {r4, pc}
