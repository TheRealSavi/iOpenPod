"""Offline preparation for the first stock Classic update experiment.

No transport or device access lives here. Preparation does not qualify execution.
The initial qualification target is the 120 GB Classic, family 33 / 2.0.1.
Protocol evidence: docs/research/classic-stock-update-source-path-2026-11-17.md.
"""

from __future__ import annotations

import hashlib
import io
import plistlib
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

if TYPE_CHECKING:
    from collections.abc import Iterator

BLOCK_BYTES = 4096
MAX_PACKAGE_BYTES = 128 * 1024 * 1024
MAX_FIRMWARE_PARTITION_KIB = 256 * 1024


@dataclass(frozen=True, slots=True)
class ClassicStockRelease:
    updater_family_id: int
    version: str
    build_id: int
    visible_build_id: int
    member_name: str
    package_sha256: str
    payload_sha256: str
    payload_bytes: int


CLASSIC_33 = ClassicStockRelease(
    33,
    "2.0.1",
    0x09018000,
    0x02018000,
    "Firmware-33.9.0.1",
    "17b16ceb4e906cf5636e7389292c40149c503a6fe3df749b3c8447290aa181d5",
    "42d6a0c18e7e3fc7cc181a15973ee12757769e25354d3320f0bff5c5d8ae17eb",
    93_515_776,
)


@dataclass(frozen=True, slots=True)
class ClassicUpdateObservation:
    """Values from one fresh live VPD capture, not inferred from the model name."""

    updater_family_id: int
    firmware_version: str
    update_method: int
    firmware_partition_kib: int
    max_firmware_blocks: int
    logical_block_bytes: int
    forced_disk_mode: bool
    corrupt_data_partition: bool


@dataclass(frozen=True, slots=True)
class FirmwareTransfer:
    cdb: bytes
    data: bytes = b""


@dataclass(frozen=True, slots=True)
class ClassicUpdatePlan:
    release: ClassicStockRelease
    payload: bytes
    firmware_partition_bytes: int
    chunk_bytes: int

    @property
    def transfer_count(self) -> int:
        return (len(self.payload) + self.chunk_bytes - 1) // self.chunk_bytes

    def transfers(self) -> Iterator[FirmwareTransfer]:
        """Describe the stream; never send it. No repartition or finalizer opcode.

        The start layout matches wInd3x's firmware-kind=0 request; this RetailOS
        handler ignores its kind/length fields. The Host must enforce the bound.
        Native C6/92 restores the preserved hash-image sector. Its success status
        does not prove that write succeeded. Chunks and end are not retry-safe:
        chunks advance an implicit cursor and end frees its retained buffer.
        Eject/reboot and independent verification are outside this byte stream.
        """
        yield FirmwareTransfer(
            b"\xc6\x90\x00" + struct.pack(">I", len(self.payload)) + bytes(9)
        )
        for offset in range(0, len(self.payload), self.chunk_bytes):
            chunk = self.payload[offset : offset + self.chunk_bytes]
            chunk += bytes(-len(chunk) % BLOCK_BYTES)
            yield FirmwareTransfer(
                b"\xc6\x91" + struct.pack(">H", len(chunk) // BLOCK_BYTES) + bytes(6),
                chunk,
            )
        yield FirmwareTransfer(b"\xc6\x92" + bytes(14))


def prepare_classic_update(
    package: bytes,
    observation: ClassicUpdateObservation,
) -> ClassicUpdatePlan:
    """Qualify the exact stock package and bounded transfer for family 33 only."""
    release = CLASSIC_33
    if observation.updater_family_id != release.updater_family_id:
        raise ValueError("Only Classic updater family 33 is qualified for preparation")
    if observation.firmware_version != release.version:
        raise ValueError(
            "The initial experiment requires running Classic firmware 2.0.1"
        )
    if (
        observation.update_method != 3
        or observation.logical_block_bytes != BLOCK_BYTES
        or observation.forced_disk_mode
        or observation.corrupt_data_partition
    ):
        raise ValueError(
            "Expected a healthy Classic in normal USB mode with UpdateMethod 3"
        )
    if (
        type(observation.max_firmware_blocks) is not int
        or not 1 <= observation.max_firmware_blocks <= 16
    ):
        raise ValueError("Invalid or unsupported MaxFWBlocks observation")
    # RetailOS publishes FWPartSize as 4096-byte sectors multiplied by four:
    # KiB, not 512-byte sectors (0812d670 -> 0812ddc8 in family 33 / 2.0.1).
    partition_kib = observation.firmware_partition_kib
    if (
        type(partition_kib) is not int
        or not 0 < partition_kib <= MAX_FIRMWARE_PARTITION_KIB
    ):
        raise ValueError("Invalid firmware partition capacity")
    payload = read_stock_package(package, release)
    padded_bytes = (len(payload) + BLOCK_BYTES - 1) // BLOCK_BYTES * BLOCK_BYTES
    partition_bytes = partition_kib * 1024
    if padded_bytes > partition_bytes:
        raise ValueError(
            "Firmware payload would exceed the observed firmware partition"
        )
    # Eight blocks agrees with the upstream transfer size and stays below the
    # connected Classic's advertised sixteen-block maximum.
    chunk_bytes = min(8, observation.max_firmware_blocks) * BLOCK_BYTES
    return ClassicUpdatePlan(release, payload, partition_bytes, chunk_bytes)


def read_stock_package(package: bytes, release: ClassicStockRelease) -> bytes:
    """Read a pinned Apple member after checking the whole package and manifest."""
    if (
        not 0 < len(package) <= MAX_PACKAGE_BYTES
        or hashlib.sha256(package).hexdigest() != release.package_sha256
    ):
        raise ValueError("Package does not match the pinned original Apple IPSW")
    with ZipFile(io.BytesIO(package)) as archive:
        names = [member.filename for member in archive.infolist()]
        if sorted(names) != sorted(["manifest.plist", release.member_name]):
            raise ValueError("Unexpected or duplicate IPSW members")
        metadata: object = plistlib.loads(_member(archive, "manifest.plist", 64 * 1024))
        if not isinstance(metadata, dict):
            raise ValueError("IPSW manifest must be a dictionary")
        manifest = cast("dict[str, object]", metadata)
        raw_payload = manifest.get("FirmwarePayload")
        if not isinstance(raw_payload, dict):
            raise ValueError("Missing FirmwarePayload metadata")
        payload_metadata = cast("dict[str, object]", raw_payload)
        expected: dict[str, str | int] = {
            "FamilyID": 11,
            "UpdaterFamilyID": release.updater_family_id,
            "FirmwareName": release.member_name,
            "BuildID": release.build_id,
            "VisibleBuildID": release.visible_build_id,
        }
        for key, value in expected.items():
            actual = payload_metadata.get(key)
            if type(actual) is not type(value) or actual != value:
                raise ValueError(f"IPSW identity mismatch: {key}")
        payload = _member(archive, release.member_name, MAX_PACKAGE_BYTES)
    if (
        len(payload) != release.payload_bytes
        or hashlib.sha256(payload).hexdigest() != release.payload_sha256
    ):
        raise ValueError(
            "Firmware member does not match the pinned original Apple bytes"
        )
    return payload


def _member(archive: ZipFile, name: str, limit: int) -> bytes:
    info = archive.getinfo(name)
    if (
        info.is_dir()
        or info.flag_bits & 1
        or info.file_size > limit
        or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
    ):
        raise ValueError("Unsupported or oversized IPSW member")
    with archive.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) != info.file_size or len(data) > limit:
        raise ValueError("Incomplete IPSW member")
    return data
