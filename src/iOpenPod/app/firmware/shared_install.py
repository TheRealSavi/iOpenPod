"""Selected-Classic normal USB installation, with durable no-replay receipts."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import struct
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from storage import (
    AccessMode,
    AtomicHostFile,
    DevicePath,
    HostPath,
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiVpdPagePlan,
)
from storage.host_files import lock_host_file
from storage.scsi_vpd import collect_scsi_vpd

from .bootloader_install import decode_bootloader_receipt
from .bootloader_report import (
    BootloaderReport,
    read_bootloader_report,
    require_reported_bootloader,
)
from .bootloader_targets import bootloader_target
from .classic_shared import FIRMWARE_BYTES, require_firmware_capacity
from .classic_update import ClassicUpdatePlan
from .paths import firmware_directory
from .shared_bootloader import BODY_SHA256, IDENTIFIER, VERSION
from .shared_records import (
    LIBRARY_PATHS,
    PENDING_STATES,
    REBOOT_COMMAND_HEX,
    InstallRecord,
    InstallRecordState,
    VisibleLayout,
    decode_record,
    finish_uploaded,
)
from .shared_release import (
    STOCK,
    SharedFirmwareRelease,
    validate_release,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from threading import Event

    from storage import MountedVolume, ScsiSession, Storage

    from .bootloader_install import UnlockIdentity


class InstallStage(StrEnum):
    READY = "ready"
    PREPARING = "preparing"
    CHECKING = "checking"
    INSTALLING = "installing"
    COMPLETE = "complete"
    CANCELED = "canceled"
    ERROR = "error"


@dataclass(frozen=True)
class InstallProgress:
    stage: InstallStage = InstallStage.READY
    percent: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class LiveFirmware:
    family: int
    version: str
    partition_bytes: int
    chunk_bytes: int
    bootloader_report: BootloaderReport | None = None


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scalar(payload: bytes, key: str, tag: str) -> str:
    prefix = rb"<key>" + re.escape(key.encode()) + rb"</key>\s*"
    if len(payload) > 1024 * 1024 or len(re.findall(prefix, payload)) != 1:
        raise ValueError(f"Missing or duplicate live firmware field: {key}")
    pattern = (
        prefix + rb"<(true|false)\s*/>"
        if tag == "bool"
        else prefix + b"<" + tag.encode() + rb">([^<>]{1,128})</" + tag.encode() + b">"
    )
    matches = re.findall(pattern, payload)
    if len(matches) != 1:
        raise ValueError(f"Malformed live firmware field: {key}")
    matched: bytes = matches[0]
    return matched.decode("ascii")


def read_live(
    session: ScsiSession,
    identity: UnlockIdentity,
    *,
    image_bytes: int = FIRMWARE_BYTES,
) -> LiveFirmware:
    def inquiry(*, evpd: bool, page: int, alloc_len: int) -> bytes:
        return session.execute(
            ScsiCommand(
                bytes((0x12, int(evpd), page, 0, alloc_len, 0)),
                data_in_length=alloc_len,
                allow_short_read=True,
            )
        ).data

    live = collect_scsi_vpd(
        inquiry,
        source="firmware-install",
        page_plan=ScsiVpdPagePlan(0xC0, 0xC2, 0xFF, True),
    )
    payload = live.vendor_payload
    if (
        (live.vendor, live.product, live.unit_serial)
        != ("Apple", "iPod", identity.serial)
        or _scalar(payload, "SerialNumber", "string") != identity.serial
        or _scalar(payload, "FamilyID", "integer") != "11"
        or _scalar(payload, "UpdateMethod", "integer") != "3"
        or _scalar(payload, "ForcedDiskMode", "bool") != "false"
        or _scalar(payload, "CorruptDataPartition", "bool") != "false"
        or _scalar(payload, "AutoRebootAfterFirmwareUpdate", "bool") != "true"
    ):
        raise ValueError("Connect the selected Classic in normal USB mode")
    family = int(_scalar(payload, "UpdaterFamilyID", "integer"))
    version = _scalar(payload, "VisibleBuildID", "string")
    if identity.reported_family is not None and identity.reported_version:
        expected = (identity.reported_family, identity.reported_version)
    else:
        raise ValueError("Refresh the iPod's current firmware before installing")
    if (family, version) != expected:
        raise ValueError(
            "The live firmware version does not match the selected installation stage"
        )
    capacity = int(_scalar(payload, "FWPartSize", "integer")) * 1024
    require_firmware_capacity(capacity, image_bytes=image_bytes)
    blocks = int(_scalar(payload, "MaxFWBlocks", "integer"))
    if not 1 <= blocks <= 16:
        raise ValueError("Unsupported firmware transfer size")
    return LiveFirmware(
        family,
        version,
        capacity,
        min(8, blocks) * 4096,
        read_bootloader_report(payload, serial=identity.serial, model=identity.model),
    )


def visible_layout(session: ScsiSession) -> VisibleLayout:
    capacity = session.execute(
        ScsiCommand(bytes.fromhex("25000000000000000000"), data_in_length=8)
    ).data
    last_lba, block = struct.unpack(">II", capacity)
    if block not in (512, 1024, 2048, 4096) or last_lba < 64:
        raise ValueError("Unsupported visible disk geometry")

    def sector(lba: int) -> bytes:
        return session.execute(
            ScsiCommand(
                b"\x28\0" + lba.to_bytes(4, "big") + b"\0\0\x01\0", data_in_length=block
            )
        ).data

    mbr = sector(0)
    partitions = [
        struct.unpack_from("<II", mbr, offset + 8)
        for offset in range(446, 510, 16)
        if mbr[offset + 4] in (6, 0x0B, 0x0C, 0x0E)
    ]
    if mbr[510:512] != b"\x55\xaa" or len(partitions) != 1:
        raise ValueError("Expected one FAT music partition")
    start, count = partitions[0]
    if not 0 < start <= last_lba or not 0 < count <= last_lba + 1 - start:
        raise ValueError("Invalid music partition bounds")
    return VisibleLayout(capacity.hex(), _digest(mbr), start, _digest(sector(start)))


class SharedFirmwareInstaller:
    def __init__(
        self,
        storage: Storage,
        directory: Path | None = None,
        *,
        release: SharedFirmwareRelease | None = None,
    ) -> None:
        self.storage = storage
        self.directory = directory if directory is not None else firmware_directory()
        self.release = release or SharedFirmwareRelease(self.directory)

    @property
    def platform(self) -> str:
        return self.storage.platform_name

    @property
    def upload_supported(self) -> bool:
        return self.storage.supports_scsi_sessions

    def _journal(self, identity: UnlockIdentity) -> AtomicHostFile:
        return AtomicHostFile(
            self.directory / "installations" / identity.serial / "operation.json"
        )

    def record(self, identity: UnlockIdentity) -> InstallRecord | None:
        raw = self._journal(identity).read_bytes(max_bytes=16384)
        record = decode_record(raw) if raw is not None else None
        if record is not None and (record.identity.serial, record.identity.model) != (
            identity.serial,
            identity.model,
        ):
            raise ValueError("Firmware record belongs to another iPod")
        return record

    def pending_identity(self) -> UnlockIdentity | None:
        pending: list[UnlockIdentity] = []
        for path in (self.directory / "installations").glob("*/operation.json"):
            journal = AtomicHostFile(path)
            with lock_host_file(path):
                raw = journal.read_bytes(max_bytes=16384)
                if raw is None:
                    continue
                record = decode_record(raw)
                if path.parent.name != record.identity.serial:
                    raise ValueError("Invalid firmware record location")
                completed = finish_uploaded(record)
                if completed is not None and completed != record:
                    self._save(journal, completed)
                    record = completed
                if record.state in PENDING_STATES:
                    pending.append(record.identity)
        return pending[0] if len(pending) == 1 else None

    def require_bootloader(self, identity: UnlockIdentity) -> int:
        """Return last DFU-verified hardware, not a current NOR observation."""
        raw = AtomicHostFile(
            self.directory / "bootloader" / identity.serial / "operation.json"
        ).read_bytes(max_bytes=16384)
        data = decode_bootloader_receipt(raw) if raw is not None else {}
        hardware = data.get("hardware_family")
        if (
            data.get("state") != "verified"
            or data.get("identifier") != IDENTIFIER
            or data.get("serial") != identity.serial
            or data.get("model") != identity.model
            or data.get("version") != VERSION
            or data.get("body_sha256") != BODY_SHA256
            or type(hardware) is not int
            or identity.model not in bootloader_target(hardware).models
            or (
                identity.family is not None
                and not identity.shared_os
                and hardware != identity.family
            )
        ):
            raise ValueError(
                f"Unlock or verify Bootloader {VERSION} on this iPod first; "
                "the expanded firmware needs its larger OS limit"
            )
        return hardware

    @staticmethod
    def _save(journal: AtomicHostFile, record: InstallRecord) -> None:
        journal.replace_bytes((json.dumps(asdict(record), indent=2) + "\n").encode())

    def _library(self, mounted: MountedVolume) -> dict[str, str]:
        result: dict[str, str] = {}
        with self.storage.open_session(mounted, access=AccessMode.READ_ONLY) as session:
            for relative in LIBRARY_PATHS:
                path = DevicePath(relative)
                if session.exists(path):
                    result[relative] = _digest(
                        session.read(path, max_bytes=256 * 1024 * 1024)
                    )
        if not any(path in result for path in LIBRARY_PATHS[:2]):
            raise ValueError("The selected iPod's music library cannot be read")
        return result

    def install(
        self,
        identity: UnlockIdentity,
        mounted: MountedVolume,
        cancel: Event,
        publish: Callable[[InstallProgress], None],
    ) -> None:
        if not self.upload_supported:
            raise ValueError(
                "This installation lacks exclusive SCSI access for firmware updates"
            )
        if not mounted.physical_device.removable:
            raise ValueError("Expected a removable iPod")
        self.storage.require_host_path_off_physical_device(
            HostPath(self.directory), mounted
        )
        journal = self._journal(identity)
        with lock_host_file(journal.path):
            previous = self.record(identity)
            completed = finish_uploaded(previous)
            if completed is not None and completed != previous:
                self._save(journal, completed)
                previous = completed
            if previous is not None and previous.state in PENDING_STATES:
                raise ValueError(
                    "The previous upload was interrupted and cannot be replayed; "
                    "DFU recovery is required"
                )
            publish(InstallProgress(InstallStage.PREPARING))
            image = self.release.prepare(
                cancel,
                lambda percent: publish(
                    InstallProgress(InstallStage.PREPARING, percent)
                ),
            )
            validate_release(image)
            if cancel.is_set():
                raise InterruptedError("Firmware installation canceled before writing")
            publish(InstallProgress(InstallStage.CHECKING))
            library = self._library(mounted)
            with self.storage.open_scsi_session(
                mounted,
                expected_identity=ScsiIdentity("Apple", "iPod", identity.serial),
            ) as session:
                live = read_live(session, identity)
                # Recheck the current connection before issuing any write. An
                # explicit failed/unknown report must never fall back to a receipt.
                if live.bootloader_report is not None:
                    require_reported_bootloader(
                        live.bootloader_report,
                        serial=identity.serial,
                        model=identity.model,
                    )
                else:
                    self.require_bootloader(identity)
                layout = visible_layout(session)
                plan = ClassicUpdatePlan(
                    STOCK, image, live.partition_bytes, live.chunk_bytes
                )
                record = InstallRecord(
                    identity,
                    mounted.volume.id.value,
                    layout,
                    library,
                    command_count=plan.transfer_count + 2,
                )
                self._save(journal, record)
                if cancel.is_set():
                    raise InterruptedError(
                        "Firmware installation canceled before writing"
                    )
                # After this boundary cancellation cannot interrupt the update.
                publish(InstallProgress(InstallStage.INSTALLING, 0))
                try:
                    last_percent = -1
                    for transfer in plan.transfers():
                        record = replace(
                            record,
                            state=InstallRecordState.COMMAND_IN_FLIGHT,
                            pending_command=transfer.cdb.hex(),
                        )
                        self._save(journal, record)
                        session.execute(
                            ScsiCommand(
                                transfer.cdb, data_out=transfer.data, timeout_seconds=30
                            )
                        )
                        record = replace(
                            record,
                            acknowledged_bytes=record.acknowledged_bytes
                            + len(transfer.data),
                            acknowledged_commands=record.acknowledged_commands + 1,
                            pending_command="",
                        )
                        self._save(journal, record)
                        percent = record.acknowledged_bytes * 100 // len(image)
                        if percent != last_percent:
                            publish(InstallProgress(InstallStage.INSTALLING, percent))
                            last_percent = percent
                    record = replace(
                        record,
                        state=InstallRecordState.REBOOT_IN_FLIGHT,
                        pending_command=REBOOT_COMMAND_HEX,
                    )
                    self._save(journal, record)
                    session.execute(
                        ScsiCommand(
                            bytes.fromhex(record.pending_command), timeout_seconds=30
                        )
                    )
                    record = replace(
                        record,
                        state=InstallRecordState.COMPLETE,
                        pending_command="",
                    )
                    self._save(journal, record)
                except BaseException as error:
                    if (
                        record.state is InstallRecordState.REBOOT_IN_FLIGHT
                        and isinstance(error, ScsiCommandError)
                        and error.response is None
                    ):
                        # A restart can remove USB before the command replies.
                        # Completion follows the acknowledged upload. Preserve
                        # the missing restart acknowledgement in the receipt.
                        logging.getLogger(__name__).info(
                            "Firmware upload completed; restart reply unavailable",
                            exc_info=True,
                        )
                        self._save(
                            journal, replace(record, state=InstallRecordState.COMPLETE)
                        )
                        return
                    # Keep the last durable intent if recording failure also fails.
                    self._save(
                        journal, replace(record, state=InstallRecordState.INTERRUPTED)
                    )
                    raise
