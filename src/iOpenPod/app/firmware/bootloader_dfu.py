"""Qualified S5L8702 DFU protocol over Storage-owned retained USB sessions.

All probes are volatile. Only the separately qualified RAM writer can mutate NOR.
"""

from __future__ import annotations

import hashlib
import struct
import time
import zlib
from typing import TYPE_CHECKING

from storage import UsbControlError, UsbControlRequest

from . import bootloader_probes as probes
from .bootloader_bundle import WriterPlan, sha
from .bootloader_targets import BOOTROM_SHA

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from storage.usb_control import UsbControlChannel

WINDOWS = ((0x400, 0x80), (0x4800, 0x100), (0xA500, 0x200), (0xA8C0, 0x200))
WINDOW_SHA = "275b874cadb2ab1476e1851b1850438771faf95f7210b11fa2cce4ab2e167fcf"


class ClassicBootDfu:
    def __init__(self, session: UsbControlChannel, cancel: Event) -> None:
        self.session = session
        self.cancel = cancel

    def read(
        self, kind: int, request: int, count: int, value: int = 0, index: int = 0
    ) -> bytes:
        return self.session.execute(
            UsbControlRequest(kind, request, value, index, data_in_length=count)
        ).data

    def write(self, request: int, data: bytes = b"", value: int = 0) -> None:
        self.session.execute(UsbControlRequest(0x21, request, value, data_out=data))

    def clean(self) -> None:
        self.write(4)
        if self.read(0xA1, 5, 1) != b"\x02":
            raise ValueError("Enter fresh DFU mode and try again")

    def probe(
        self, code: bytes, size: int, prefix: bytes = bytes(probes.PREFIX_SIZE)
    ) -> bytes:
        if self.cancel.is_set():
            raise InterruptedError("Bootloader preparation canceled")
        if len(prefix) != probes.PREFIX_SIZE or len(prefix + code) > 1024:
            raise ValueError("Invalid probe wire size")
        self.clean()
        self.write(1, prefix + code)
        self.clean()
        self.read(0xA1, 2, 64)
        return self.read(0xA0, 0xFE, size, 0xEAFF, 6)

    def fingerprint(self) -> None:
        data = b"".join(
            self.probe(probes.memory(0x20000000 + offset, fast=False), 64)
            for start, size in WINDOWS
            for offset in range(start, start + size, 64)
        )
        if sha(data) != WINDOW_SHA:
            raise ValueError("This iPod's BootROM is not supported")

    def qualify(self) -> None:
        self.fingerprint()
        rom = b"".join(
            self.probe(probes.memory(0x20000000 + offset, 512), 512)
            for offset in range(0, 65536, 512)
        )
        if sha(rom) != BOOTROM_SHA:
            raise ValueError("This iPod's BootROM is not qualified")
        if self.probe(probes.nor_init(), 64) != rom[:64]:
            raise ValueError("NOR initialization failed")

    def nor(
        self, offset: int, size: int, progress: Callable[[int, int], None]
    ) -> bytes:
        data = bytearray()
        for at in range(offset, offset + size, 512):
            count = min(512, offset + size - at)
            reply = self.probe(probes.nor_read(at, count), count + 16)
            if struct.unpack_from("<I", reply)[0]:
                raise ValueError("The iPod could not read its boot flash")
            data.extend(reply[16:])
            progress(len(data), size)
        return bytes(data)

    def crypt(
        self, data: bytes, *, encrypt: bool = False, iv: bytes = bytes(16)
    ) -> bytes:
        if len(iv) != 16:
            raise ValueError("Invalid CBC IV")
        code = probes.aes(len(data), encrypt=encrypt)
        prefix = bytearray(probes.PREFIX_SIZE)
        prefix[:4] = b"\xff" * 4
        prefix[16 : 16 + len(data)] = data
        prefix[16 + len(data) : 32 + len(data)] = iv
        reply = self.probe(code, len(data) + 16, bytes(prefix))
        if struct.unpack_from("<I", reply)[0]:
            raise ValueError("The iPod's bootloader authentication operation failed")
        result = reply[16:]
        if encrypt and self.crypt(result) != data:
            raise ValueError("Bootloader authentication round-trip failed")
        return result

    def plaintext(self, image: bytes) -> bytes:
        if (
            len(image) != 0x20000
            or image[:7] != b"87021.0"
            or image[7] not in (1, 2)
            or struct.unpack_from("<II", image, 8) != (0, 0x1F800)
        ):
            raise ValueError("Unsupported installed bootloader framing")
        if self.crypt(image[0x40:0x50]) != hashlib.sha1(image[:0x40]).digest()[:16]:
            raise ValueError("Installed bootloader header authentication failed")
        body = image[0x800:]
        if image[7] == 1:
            plain = bytearray()
            iv = bytes(16)
            for offset in range(0, len(body), 512):
                block = body[offset : offset + 512]
                plain.extend(self.crypt(block, iv=iv))
                iv = block[-16:]
            body = bytes(plain)
        if self.crypt(image[0x10:0x20]) != hashlib.sha1(body).digest()[:16]:
            raise ValueError("Installed bootloader body authentication failed")
        return body

    def seal(self, body: bytes) -> bytes:
        if len(body) != 0x1F800:
            raise ValueError("Invalid loader body size")
        header = bytearray(0x800)
        header[:8] = b"87021.0\x02"
        struct.pack_into("<I", header, 12, len(body))
        header[0x10:0x20] = self.crypt(hashlib.sha1(body).digest()[:16], encrypt=True)
        header[0x40:0x50] = self.crypt(
            hashlib.sha1(header[:0x40]).digest()[:16], encrypt=True
        )
        return bytes(header) + body

    def download(self, image: bytes, handoff: Callable[[], None]) -> None:
        if not 0x800 <= len(image) <= 0x20000 or image[:8] != b"87021.0\x03":
            raise ValueError("Invalid RAM writer envelope")
        self.clean()
        data = image + struct.pack("<I", zlib.crc32(image) ^ 0xFFFFFFFF)
        for index, offset in enumerate(range(0, len(data), 1024)):
            if self.cancel.is_set():
                raise InterruptedError(
                    "Bootloader transfer canceled before installation"
                )
            self.write(1, data[offset : offset + 1024], index)
            self.wait_status(manifest=False)
        # Persist intent BEFORE the zero-length command. Its completion can be
        # uncertain; never automatically resend it, even on transfer failure.
        handoff()
        try:
            self.write(1, value=(len(data) + 1023) // 1024)
            self.wait_status(manifest=True)
        except (UsbControlError, OSError, TimeoutError, ValueError):
            pass  # A fresh session and nonce-bearing report decide the outcome.

    def wait_status(self, *, manifest: bool) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.read(0xA1, 3, 6)
            if status[0]:
                raise ValueError(f"DFU transfer error {status[0]}")
            if status[4] == (7 if manifest else 5):
                return
            if status[4] not in ((4, 6) if manifest else (3, 4)):
                raise ValueError(f"Unexpected DFU state {status[4]}")
            time.sleep(min(100, max(1, int.from_bytes(status[1:4], "little"))) / 1000)
        raise TimeoutError("DFU transfer timed out")

    def report(self, plan: WriterPlan) -> bytes:
        data = self.probe(probes.memory(0x2201F000, 256), 256)
        if data[:64] != self.probe(probes.memory(0x2201F000, fast=False), 64):
            raise ValueError("Bootloader report reads disagree")
        verify_report(data, plan)
        return data


def verify_report(data: bytes, plan: WriterPlan) -> None:
    if len(data) < 212:
        raise ValueError("Incomplete bootloader report")
    words = struct.unpack_from("<21I", data)
    if (
        words[:6] != (0x314E5249, 1, 6, 0, 4096, 0x20000)
        or data[32:48] != plan.nonce
        or words[16:19] != (0xBF258E, 1, 32)
    ):
        raise ValueError(
            "Installation is unverified: missing, stale, or failed writer report"
        )
    for offset, expected in (
        (84, plan.before_sha),
        (116, plan.target_sha),
        (148, plan.after_sha),
        (180, plan.outside_sha),
    ):
        if data[offset : offset + 32].hex() != expected:
            raise ValueError("Installation is unverified: boot flash readback mismatch")
