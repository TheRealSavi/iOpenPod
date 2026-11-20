"""Durable normal-USB installation records, independent of worker/UI progress.

Saved strings and JSON fields are stable across releases. This codec performs
no I/O; upload acknowledgements determine completion across app restarts.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from .bootloader_install import UnlockIdentity, identity_from_record
from .shared_release import IMAGE_SHA256, MOD_VERSION, RELEASE_BYTES, RELEASE_HASHES


class InstallRecordState(StrEnum):
    PREPARED = "prepared"
    COMMAND_IN_FLIGHT = "command-in-flight"
    INTERRUPTED = "interrupted"
    REBOOT_IN_FLIGHT = "reboot-in-flight"
    AWAITING_BOOT = "awaiting-boot"
    BOOT_VERIFIED = "boot-verified"
    COMPLETE = "complete"


REBOOT_COMMAND_HEX = "1b0000000200"


@dataclass(frozen=True)
class VisibleLayout:
    capacity: str
    mbr_sha256: str
    boot_lba: int
    boot_sha256: str


@dataclass(frozen=True)
class InstallRecord:
    identity: UnlockIdentity
    volume_id: str
    layout: VisibleLayout
    library: dict[str, str]
    state: InstallRecordState = InstallRecordState.PREPARED
    image_sha256: str = IMAGE_SHA256
    mod_version: str = MOD_VERSION
    acknowledged_bytes: int = 0
    acknowledged_commands: int = 0
    command_count: int = 0
    pending_command: str = ""
    verified_library: dict[str, str] | None = None
    reported_mod_version: str = ""

    @property
    def library_changed(self) -> bool:
        return (
            self.verified_library is not None and self.verified_library != self.library
        )


LIBRARY_PATHS = (
    "iPod_Control/iTunes/iTunesDB",
    "iPod_Control/iTunes/iTunesCDB",
    "iPod_Control/iTunes/iTunesSD",
    "iPod_Control/Artwork/ArtworkDB",
    "Photos/Photo Database",
)
PENDING_STATES = frozenset(
    {
        InstallRecordState.COMMAND_IN_FLIGHT,
        InstallRecordState.INTERRUPTED,
        InstallRecordState.REBOOT_IN_FLIGHT,
        InstallRecordState.AWAITING_BOOT,
        InstallRecordState.BOOT_VERIFIED,
    }
)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid firmware installation record")
    mapping = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError("Invalid firmware installation record")
    return cast("dict[str, object]", value)


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Invalid firmware record field: {key}")
    return value


def _number(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid firmware record field: {key}")
    return value


def decode_record(raw: bytes) -> InstallRecord:
    data = _object(json.loads(raw))
    layout = _object(data.get("layout"))
    library = _object(data.get("library"))
    verified = data.get("verified_library")
    verified_library = _object(verified) if verified is not None else None
    record = InstallRecord(
        identity_from_record(_object(data.get("identity"))),
        _text(data, "volume_id"),
        VisibleLayout(
            _text(layout, "capacity"),
            _text(layout, "mbr_sha256"),
            _number(layout, "boot_lba"),
            _text(layout, "boot_sha256"),
        ),
        {key: _text(library, key) for key in library},
        InstallRecordState(_text(data, "state")),
        _text(data, "image_sha256"),
        _text(data, "mod_version"),
        _number(data, "acknowledged_bytes"),
        _number(data, "acknowledged_commands"),
        _number(data, "command_count"),
        _text(data, "pending_command"),
        {key: _text(verified_library, key) for key in verified_library}
        if verified_library is not None
        else None,
        _text(data, "reported_mod_version") if "reported_mod_version" in data else "",
    )
    if (
        RELEASE_HASHES.get(record.mod_version) != record.image_sha256
        or not record.volume_id
        or not record.library
        or any(key not in LIBRARY_PATHS for key in record.library)
        or any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in record.library.values()
        )
        or record.acknowledged_bytes > RELEASE_BYTES.get(record.mod_version, 0)
        or record.acknowledged_commands > record.command_count
        or record.reported_mod_version not in ("", record.mod_version)
        or (
            record.verified_library is not None
            and (
                not record.verified_library
                or any(key not in LIBRARY_PATHS for key in record.verified_library)
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", value) is None
                    for value in record.verified_library.values()
                )
            )
        )
    ):
        raise ValueError("Unrecognized or damaged firmware installation record")
    return record


def finish_uploaded(record: InstallRecord | None) -> InstallRecord | None:
    """Finish legacy post-upload receipts using their saved acknowledgements."""
    if (
        record is None
        or record.acknowledged_bytes != RELEASE_BYTES[record.mod_version]
        or record.acknowledged_commands != record.command_count
        or record.command_count < 3
        or record.state
        not in (
            InstallRecordState.AWAITING_BOOT,
            InstallRecordState.REBOOT_IN_FLIGHT,
            InstallRecordState.BOOT_VERIFIED,
        )
    ):
        return record
    if record.pending_command not in ("", REBOOT_COMMAND_HEX):
        return record
    return replace(record, state=InstallRecordState.COMPLETE)
