"""S5L8702 read/crypto probes; no NOR write instructions.

SPDX-License-Identifier: GPL-3.0-only
Ported from osos-lab d2c8e357/reprise-device payload.rs and its checked UKEY
encryption extension. Based on wInd3x (GPL-2.0-or-later), copyright 2022
Serge 'q3k' Bazanski. See scripts/bootloader/README.md.
"""

import struct

PREFIX_SIZE = 648


class Arm:
    def __init__(self) -> None:
        self.code: list[int] = []
        self.literals: list[tuple[int, int]] = []

    def literal(self, register: int, value: int) -> None:
        self.literals.append((len(self.code), value))
        self.code.append(0xE59F0000 | register << 12)

    def value(self, register: int, value: int) -> None:
        if value < 256:
            self.code.append(0xE3A00000 | register << 12 | value)
        else:
            self.literal(register, value)

    def call(self, address: int, *arguments: int, literal: bool = False) -> None:
        if len(arguments) > 5:
            raise ValueError("Too many ARM arguments")
        if len(arguments) == 5:
            self.code.append(0xE24DD008)
            self.literal(0, arguments[4])
            self.code.append(0xE58D0000)
        for register, value in enumerate(arguments[:4]):
            (self.literal if literal else self.value)(register, value)
        self.literal(14, address)
        self.code.append(0xE12FFF3E)
        if len(arguments) == 5:
            self.code.append(0xE28DD008)

    def branch(self, instruction: int, target: int) -> None:
        self.code[instruction] |= (target - instruction - 2) & 0xFFFFFF

    def footer(self, address: int, size: int = 64, *, fast: bool = True) -> None:
        if fast:
            self.call(0x20000468, literal=True)
            self.call(0x2000A514, literal=True)
            self.call(0x2000AA40, address, size, literal=True)
            self.code.extend((0xE59D4000, 0xE59DE004, 0xE28DD008, 0xE12FFF1E))
        else:
            self.literal(0, address)
            self.value(1, 64)
            self.literal(2, 0x2000AA40)
            self.code.append(0xE12FFF32)
            self.literal(14, 0x200048D4)
            self.code.append(0xE12FFF1E)

    def finish(self) -> bytes:
        code = list(self.code)
        pool: list[int] = []
        for instruction, value in self.literals:
            if value not in pool:
                pool.append(value)
            offset = (len(code) + pool.index(value)) * 4 - (instruction * 4 + 8)
            if not 0 <= offset < 4096:
                raise ValueError("Invalid ARM literal displacement")
            code[instruction] |= offset
        data = struct.pack(f"<{len(code) + len(pool)}I", *code, *pool)
        if len(data) + PREFIX_SIZE > 1024:
            raise ValueError("Probe exceeds the DFU buffer")
        return data


def memory(address: int, size: int = 64, *, fast: bool = True) -> bytes:
    if not 1 <= size <= 512 or not 0 <= address <= 0xFFFFFFFF - size + 1:
        raise ValueError("Invalid memory range")
    arm = Arm()
    arm.call(0x20000418)
    arm.footer(address, size, fast=fast)
    return arm.finish()


def nor_init() -> bytes:
    arm = Arm()
    arm.call(0x20000418)
    arm.call(0x20001924, 0)
    arm.call(0x2000147C, 0x22)
    arm.footer(0x20000000, fast=False)
    return arm.finish()


def nor_read(offset: int, size: int) -> bytes:
    if not 1 <= size <= 512 or not 0 <= offset <= 0x100000 - size:
        raise ValueError("Invalid NOR range")
    arm = Arm()
    arm.call(0x20008F90, 0, 200)
    arm.call(0x20004C7C, 0)
    arm.code.append(0xE3500000)
    branch = len(arm.code)
    arm.code.append(0x1A000000)
    arm.call(0x20008F90, 0, size + 4)
    arm.call(0x20004E5C, 0, offset, size, 0x22020010)
    arm.branch(branch, len(arm.code))
    arm.literal(1, 0x22020000)
    arm.code.append(0xE5810000)
    arm.footer(0x22020000, size + 16)
    return arm.finish()


def aes(size: int, *, encrypt: bool = False) -> bytes:
    if not 16 <= size <= 512 or size % 16 or (encrypt and size != 16):
        raise ValueError("Invalid UKEY operation size")
    buffer = 0x22028220
    arm = Arm()
    arm.call(0x20000418)
    arm.call(0x2000147C, 10, literal=True)
    arm.call(0x20000474, literal=True)
    arm.call(
        0x20001F64 if encrypt else 0x20001F04,
        buffer + 16,
        size,
        2,
        0,
        buffer + 16 + size,
        literal=True,
    )
    arm.literal(1, 0x38C0000C)
    arm.literal(2, 100000)
    poll = len(arm.code)
    arm.code.extend((0xE5910000, 0xE200000F, 0xE3500000))
    complete = len(arm.code)
    arm.code.extend((0x1A000000, 0xE2422001, 0xE3520000, 0x1A000000))
    arm.branch(len(arm.code) - 1, poll)
    arm.call(0x20001AFC, literal=True)
    arm.code.append(0xE3A02001)
    done = len(arm.code)
    arm.code.append(0xEA000000)
    arm.branch(complete, len(arm.code))
    arm.call(0x20001D48, literal=True)
    arm.code.append(0xE3A02000)
    arm.branch(done, len(arm.code))
    arm.call(0x20000454, literal=True)
    arm.literal(1, buffer)
    arm.code.append(0xE5812000)
    arm.footer(buffer, size + 16)
    return arm.finish()
