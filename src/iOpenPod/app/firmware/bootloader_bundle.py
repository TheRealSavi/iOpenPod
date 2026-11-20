"""Qualified loader identity and checked, device-independent installation assets."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from importlib.resources import files
from typing import cast

from .bootloader_targets import bootloader_target

IDENTIFIER = "iOpenPod-Bootloader-v1"
VERSION = "1.0.0"


def sha(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class WriterPlan:
    nonce: bytes
    before_sha: str
    target_sha: str
    after_sha: str
    outside_sha: str
    image: bytes


class BootloaderBundle:
    def __init__(self, family: int = 33) -> None:
        target = self.target = bootloader_target(family)
        root = files("iOpenPod").joinpath(f"assets/bootloader/classic{family}")
        raw_manifest = root.joinpath("manifest.json").read_bytes()
        if sha(raw_manifest) != target.manifest_sha256:
            raise ValueError("Damaged bootloader manifest")
        manifest = json.loads(raw_manifest)
        if (
            manifest["schema"],
            manifest["target_sha256"],
            manifest["family"],
            manifest["gap_start"],
            manifest["seccore_offset"],
        ) != (1, target.target_sha256, family, target.gap_start, target.seccore_offset):
            raise ValueError("Unsupported bootloader bundle")
        self._patch = root.joinpath("stock.delta").read_bytes()
        self._template = root.joinpath("writer.dfu").read_bytes()
        for name, data in (
            ("stock.delta", self._patch),
            ("writer.dfu", self._template),
        ):
            if sha(data) != manifest["files"][name]:
                raise ValueError(f"Damaged bootloader asset: {name}")
        self._slots = cast("dict[str, dict[str, int]]", manifest["slots"])

    def apply(self, stock: bytes) -> bytes:
        if len(stock) != 0x1F800 or sha(stock) != self.target.stock_sha256:
            raise ValueError(
                f"This bootloader is not the qualified family {self.target.family} "
                f"Apple {self.target.apple_version} loader"
            )
        return apply_delta(stock, self._patch, self.target.target_sha256)

    def writer(self, before: bytes, target: bytes, nonce: bytes) -> WriterPlan:
        return prepare_writer(
            before,
            target,
            nonce,
            body_sha256=self.target.target_sha256,
            gap=self.target.gap_start,
            tail=self.target.seccore_offset,
            template=self._template,
            slots=self._slots,
        )


def prepare_writer(
    before: bytes,
    target: bytes,
    nonce: bytes,
    *,
    body_sha256: str,
    gap: int,
    tail: int,
    template: bytes,
    slots: dict[str, dict[str, int]],
) -> WriterPlan:
    if len(before) != 0x100000 or len(target) != 0x20000 or len(nonce) != 16:
        raise ValueError("Invalid writer plan lengths")
    if (
        sha(target[0x800:]) != body_sha256
        or target[:8] != b"87021.0\x02"
        or any(target[80:0x800])
    ):
        raise ValueError("Writer requires the qualified sealed loader")
    body = target[0x800:]
    if body[gap:tail] != b"\xff" * (tail - gap):
        raise ValueError("Loader packing gap is not empty")
    outside = before[:0x8000] + before[0x28000:]
    after = before[:0x8000] + target + before[0x28000:]
    values = {
        "expected_original_full": hashlib.sha256(before).digest(),
        "expected_original_boot": hashlib.sha256(before[0x8000:0x28000]).digest(),
        "expected_syscfg": hashlib.sha256(before[:0x8000]).digest(),
        "expected_outside": hashlib.sha256(outside).digest(),
        "expected_target": hashlib.sha256(target).digest(),
        "expected_after_full": hashlib.sha256(after).digest(),
        "run_nonce": nonce,
        "packed_header": target[:80],
        "packed_body": body[:gap] + body[tail:],
    }
    image = bytearray(template)
    occupied: set[int] = set()
    if values.keys() != slots.keys():
        raise ValueError("Invalid writer template fields")
    for name, data in values.items():
        slot = slots[name]
        offset, size = slot["offset"], slot["size"]
        positions = set(range(offset, offset + size))
        if (
            size != len(data)
            or not 0x30C <= offset < offset + size <= len(image)
            or occupied & positions
            or any(image[offset : offset + size])
        ):
            raise ValueError("Invalid writer template slot")
        occupied.update(positions)
        image[offset : offset + size] = data
    return WriterPlan(
        nonce, sha(before), sha(target), sha(after), sha(outside), bytes(image)
    )


def apply_delta(stock: bytes, compressed: bytes, expected_sha256: str) -> bytes:
    stream = zlib.decompressobj()
    patch = stream.decompress(compressed, 2 * 1024 * 1024)
    if not stream.eof or stream.unused_data or stream.unconsumed_tail:
        raise ValueError("Invalid bootloader delta")
    result = bytearray(stock)
    cursor = end = 0
    while cursor < len(patch):
        offset, size = struct.unpack_from("<II", patch, cursor)
        cursor += 8
        if not end <= offset < offset + size <= len(result) or cursor + size > len(
            patch
        ):
            raise ValueError("Invalid bootloader delta range")
        result[offset : offset + size] = patch[cursor : cursor + size]
        end = offset + size
        cursor += size
    if sha(result) != expected_sha256:
        raise ValueError("Patched bootloader digest mismatch")
    return bytes(result)
