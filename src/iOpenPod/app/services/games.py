"""Prepare game authorization publication without owning a device connection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, cast

from storage import (
    DevicePath,
    FileContent,
    StorageTransaction,
    TransactionWrite,
)

if TYPE_CHECKING:
    from device_registry import DeviceEvidence
    from storage import FilePrecondition, FilesystemSession

AUTHORIZATION_PATH = DevicePath("iPod_Control/iTunes/IC-Info.sidb")
MAX_AUTHORIZATION_BYTES = 0x80000
_TESTED_RELEASES = {
    13: (1, 3, 0),
    20: (1, 3, 0),
    25: (1, 3, 0),
    24: (1, 1, 2),
    33: (2, 0, 1),
    35: (2, 0, 4),
    38: (2, 0, 5),
    26: (1, 1, 3),
    31: (1, 0, 4),
    34: (1, 0, 2),
}


@dataclass(frozen=True, slots=True)
class GamesResult:
    """Publication counts, never account identifiers or key material."""

    added_keys: int
    replaced_keys: int
    unchanged_keys: int
    changed: bool


@dataclass(frozen=True, slots=True)
class PreparedGames:
    transaction: StorageTransaction | None
    result: GamesResult


def destination_family(evidence: DeviceEvidence) -> int:
    """Require unambiguous family and RetailOS evidence for an inspected build."""
    identifiers = evidence.updater_family_ids
    versions = evidence.firmware_versions
    if not identifiers or not versions:
        raise ValueError(
            "Games requires an identified updater family and firmware release."
        )
    authority = max(item.authority for item in identifiers)
    families = {item.value for item in identifiers if item.authority == authority}
    if len(families) != 1 or (family := next(iter(families))) not in _TESTED_RELEASES:
        raise ValueError("This iPod family is not supported for game authorization.")
    version_authority = max(item.authority for item in versions)
    releases: set[tuple[int, int, int] | None] = set()
    for item in versions:
        if item.authority != version_authority:
            continue
        match = re.fullmatch(
            r"([0-9]{1,3})\.([0-9]{1,3})(?:\.([0-9]{1,3}))?", item.value.strip()
        )
        releases.add(
            None
            if match is None
            else (int(match[1]), int(match[2]), int(match[3] or 0))
        )
    if releases != {_TESTED_RELEASES[family]}:
        raise ValueError(
            "Game authorization has not been verified for this iPod firmware release."
        )
    return family


def bundled_source() -> tuple[bytes, bytes]:
    """Load and authenticate the explicitly bundled Classic source resource."""
    root = files("iOpenPod").joinpath("assets", "games")
    decoded: object = json.loads(
        root.joinpath("source.json").read_text(encoding="utf-8")
    )
    if not isinstance(decoded, dict):
        raise ValueError("The bundled game authorization metadata is invalid.")
    metadata = cast("dict[str, object]", decoded)
    guid_hex: object = metadata.get("guid")
    expected_hash: object = metadata.get("sha256")
    if not isinstance(guid_hex, str) or not isinstance(expected_hash, str):
        raise ValueError("The bundled game authorization metadata is incomplete.")
    guid = bytes.fromhex(guid_hex)
    source = root.joinpath("classic65-IC-Info.sidb").read_bytes()
    if len(guid) != 8 or hashlib.sha256(source).hexdigest() != expected_hash:
        raise ValueError("The bundled game authorization source failed verification.")
    return source, guid


def prepare(
    session: FilesystemSession,
    *,
    source: bytes,
    source_guid: bytes,
    destination_guid: bytes,
    family: int,
    dependencies: tuple[FilePrecondition, ...],
) -> PreparedGames:
    """Capture the existing file, convert/merge bytes, and validate one plan."""
    from iPodDB.ic_info import transfer_and_merge

    snapshot = (
        session.read_snapshot(AUTHORIZATION_PATH, max_bytes=MAX_AUTHORIZATION_BYTES)
        if session.exists(AUTHORIZATION_PATH)
        else None
    )
    existing = None if snapshot is None else snapshot.data
    converted = transfer_and_merge(
        source, source_guid, destination_guid, family, existing
    )
    changed = converted.data != existing
    result = GamesResult(
        converted.added_keys, converted.replaced_keys, converted.unchanged_keys, changed
    )
    if not changed:
        if (
            snapshot is None
            or session.fingerprint(AUTHORIZATION_PATH) != snapshot.fingerprint
        ):
            raise ValueError("The game authorization file changed during preparation.")
        return PreparedGames(None, result)
    transaction = StorageTransaction(
        (
            TransactionWrite(
                AUTHORIZATION_PATH,
                converted.data,
                FileContent(
                    len(converted.data), hashlib.sha256(converted.data).hexdigest()
                ),
                expected=None if snapshot is None else snapshot.fingerprint,
            ),
        ),
        dependencies=dependencies,
        host_recovery=True,
    )
    session.validate_transaction(transaction)
    return PreparedGames(transaction, result)
