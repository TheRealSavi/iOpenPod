"""Journalled first stock Classic upload, without automatic reboot or retries."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.firmware.classic_update import BLOCK_BYTES, CLASSIC_33
from storage import AtomicHostFile, HostPath, ScsiCommand, ScsiIdentity

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.firmware.classic_update import ClassicUpdatePlan
    from storage import MountedVolume, ScsiSession, Storage


@dataclass(frozen=True)
class VerifiedFirmwareRange:
    offset: int
    size: int
    sha256: str


@dataclass(frozen=True)
class ClassicRecovery:
    """Retained material and independent device observations for this experiment.

    Ranges are obtained from the acquisition helper's two-read comparison and
    device-side hashes. The entire proposed write span must match the retained
    preimage. Merely possessing an Apple package is not this evidence.
    """

    serial: str
    preimage: bytes
    ranges: tuple[VerifiedFirmwareRange, ...]
    nor: bytes
    raw_mbr: bytes
    visible_mbr: bytes
    visible_boot_sector: bytes
    visible_last_lba: int

    def validate(self, plan: ClassicUpdatePlan) -> None:
        padded = (len(plan.payload) + BLOCK_BYTES - 1) // BLOCK_BYTES * BLOCK_BYTES
        if not self.serial or len(self.preimage) != padded or len(self.nor) != 1024**2:
            raise ValueError("Incomplete Classic recovery material")
        offset = 0
        for item in self.ranges:
            if (
                item.offset != offset
                or not 0 < item.size <= len(self.preimage) - offset
            ):
                raise ValueError(
                    "Recovery verification has a gap, overlap or invalid bound"
                )
            if _sha(self.preimage[offset : offset + item.size]) != item.sha256:
                raise ValueError(
                    "Recovery preimage differs from the device-verified digest"
                )
            offset += item.size
        if offset != padded:
            raise ValueError(
                "Recovery evidence does not cover the entire padded write span"
            )
        if (
            len(self.raw_mbr) != BLOCK_BYTES
            or self.raw_mbr[510:512] != b"\x55\xaa"
            or self.raw_mbr[466] != 0x3F
            or struct.unpack_from("<II", self.raw_mbr, 470) != (63, 49152)
            or plan.firmware_partition_bytes != 49152 * BLOCK_BYTES
            or len(self.visible_mbr) != BLOCK_BYTES
            or len(self.visible_boot_sector) != BLOCK_BYTES
            or self.visible_last_lba <= 63
        ):
            raise ValueError("Recovery layout does not match the qualified Classic")


@dataclass(frozen=True)
class ClassicUploadReceipt:
    serial: str
    payload_sha256: str
    acknowledged_bytes: int
    acknowledged_commands: int
    state: str = "awaiting-independent-verification"


def upload_classic_stock(
    storage: Storage,
    mounted: MountedVolume,
    plan: ClassicUpdatePlan,
    recovery: ClassicRecovery,
    journal: AtomicHostFile,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> ClassicUploadReceipt:
    """Send the qualified stream once; a receipt is not proof of installation.

    A durable intent precedes every command. Failure, including journal failure,
    closes access without sending further commands, a finalizer, or an eject.
    An existing journal cannot be reused or resumed. The caller separately owns
    reboot, independent firmware verification, and media/library postconditions.
    """

    if (
        plan.release != CLASSIC_33
        or len(plan.payload) != CLASSIC_33.payload_bytes
        or _sha(plan.payload) != CLASSIC_33.payload_sha256
        or not BLOCK_BYTES <= plan.chunk_bytes <= 8 * BLOCK_BYTES
        or plan.chunk_bytes % BLOCK_BYTES
    ):
        raise ValueError(
            "Only the pinned original Classic firmware stream is permitted"
        )
    recovery.validate(plan)
    storage.require_host_path_off_physical_device(HostPath(journal.path), mounted)
    if journal.exists():
        raise ValueError("An existing upload journal cannot be replayed or resumed")
    identity = ScsiIdentity("Apple", "iPod", recovery.serial)
    state: dict[str, object] = {
        "schema": 1,
        "serial": recovery.serial,
        "volume_id": mounted.volume.id.value,
        "connection_generation": mounted.connection_generation.value,
        "package_sha256": CLASSIC_33.package_sha256,
        "payload_sha256": CLASSIC_33.payload_sha256,
        "recovery_sha256": _sha(recovery.preimage),
        "nor_sha256": _sha(recovery.nor),
        "state": "prepared",
        "acknowledged_bytes": 0,
        "acknowledged_commands": 0,
        "pending_command": None,
    }
    acknowledged_bytes = 0
    acknowledged_commands = 0
    with storage.open_scsi_session(mounted, expected_identity=identity) as session:
        _check_visible_disk(session, recovery)
        journal.create_bytes(_encode(state))
        try:
            for index, transfer in enumerate(plan.transfers()):
                state.update(
                    state="command-in-flight",
                    pending_command={
                        "index": index,
                        "cdb": transfer.cdb.hex(),
                        "bytes": len(transfer.data),
                    },
                )
                journal.replace_bytes(_encode(state))
                session.execute(
                    ScsiCommand(
                        transfer.cdb, data_out=transfer.data, timeout_seconds=30
                    )
                )
                acknowledged_bytes += len(transfer.data)
                acknowledged_commands += 1
                state.update(
                    state="command-acknowledged",
                    acknowledged_bytes=acknowledged_bytes,
                    acknowledged_commands=acknowledged_commands,
                    pending_command=None,
                )
                journal.replace_bytes(_encode(state))
                if progress is not None:
                    progress(acknowledged_bytes, len(plan.payload))
            receipt = ClassicUploadReceipt(
                recovery.serial,
                CLASSIC_33.payload_sha256,
                acknowledged_bytes,
                acknowledged_commands,
            )
            state.update(state=receipt.state, receipt=asdict(receipt))
            journal.replace_bytes(_encode(state))
            return receipt
        except BaseException as error:
            # Leave an in-flight command uncertain. Do not infer that a failed
            # host call means no data reached the device's implicit write cursor.
            state.update(state="interrupted-do-not-retry-or-eject", error=str(error))
            try:
                journal.replace_bytes(_encode(state))
            except Exception as journal_error:
                error.add_note(f"Recording interruption also failed: {journal_error}")
            raise


def _check_visible_disk(session: ScsiSession, recovery: ClassicRecovery) -> None:
    capacity = session.execute(
        ScsiCommand(bytes.fromhex("25000000000000000000"), data_in_length=8)
    ).data
    if struct.unpack(">II", capacity) != (recovery.visible_last_lba, BLOCK_BYTES):
        raise ValueError("The visible disk capacity changed after recovery capture")
    for lba, expected in (
        (0, recovery.visible_mbr),
        (63, recovery.visible_boot_sector),
    ):
        cdb = b"\x28\0" + lba.to_bytes(4, "big") + b"\0\0\x01\0"
        actual = session.execute(ScsiCommand(cdb, data_in_length=BLOCK_BYTES)).data
        if actual != expected:
            raise ValueError("The visible disk layout changed after recovery capture")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode(state: dict[str, object]) -> bytes:
    return (json.dumps(state, indent=2) + "\n").encode("utf-8")
