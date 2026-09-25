"""Strict, read-only decoder for Original iOpenPod v2/v3 catalogs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast

from iOpenPod.app.backups._json import StrictJsonError, loads_strict
from iOpenPod.app.backups.models import (
    BackupDeviceMetadata,
    BackupReason,
    ContentIdentity,
    SnapshotIdentityState,
)

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_MTIME_NS = (1 << 63) - 1
_ORIGINAL_REASON_ALIASES = {"pre_sync": BackupReason.PRE_SYNC}


class OriginalArchiveFormatError(ValueError):
    """An Original v2/v3 catalog cannot be imported safely."""


@dataclass(frozen=True, slots=True)
class OriginalManifestFile:
    path_parts: tuple[str, ...]
    content: ContentIdentity
    modified_ns: int | None


@dataclass(frozen=True, slots=True)
class OriginalManifest:
    version: int
    snapshot_id: str
    timestamp: str
    device_id: str
    device_name: str
    metadata: BackupDeviceMetadata
    identity_state: SnapshotIdentityState
    reason: BackupReason
    note: str
    files: tuple[OriginalManifestFile, ...]
    catalog_sha256: str


def decode_original_manifest(
    data: bytes,
    *,
    expected_snapshot_id: str,
    expected_device_id: str,
) -> OriginalManifest:
    try:
        value = loads_strict(data)
    except StrictJsonError as error:
        raise OriginalArchiveFormatError(
            f"The Original catalog is unreadable: {error}"
        ) from error
    if not isinstance(value, dict):
        raise OriginalArchiveFormatError("The Original catalog is not a JSON object")
    raw = {
        key: item
        for key, item in cast("dict[object, object]", value).items()
        if isinstance(key, str)
    }
    version = raw.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in {2, 3}
    ):
        raise OriginalArchiveFormatError(
            f"The Original catalog version {version!r} is unsupported"
        )
    if raw.get("id") != expected_snapshot_id:
        raise OriginalArchiveFormatError(
            "The Original catalog identity does not match its filename"
        )
    if raw.get("device_id") != expected_device_id:
        raise OriginalArchiveFormatError(
            "The Original catalog belongs to another legacy archive"
        )
    try:
        computed_digest = original_catalog_digest(raw)
    except RecursionError as error:
        raise OriginalArchiveFormatError(
            "The Original catalog is too deeply nested to checksum"
        ) from error
    except UnicodeError as error:
        raise OriginalArchiveFormatError(
            "The Original catalog contains invalid Unicode text"
        ) from error
    if version == 3:
        recorded = raw.get("manifest_sha256")
        if (
            not isinstance(recorded, str)
            or _SHA256.fullmatch(recorded) is None
            or recorded.casefold() != computed_digest
        ):
            raise OriginalArchiveFormatError(
                "The Original v3 catalog checksum is invalid"
            )

    marker = raw.get("identity_is_stable")
    if marker is None:
        identity_state = SnapshotIdentityState.LEGACY_UNKNOWN
    elif marker is True:
        identity_state = SnapshotIdentityState.LEGACY_ASSERTED
    elif marker is False:
        identity_state = SnapshotIdentityState.UNSTABLE
    else:
        raise OriginalArchiveFormatError(
            "The Original catalog hardware-identity marker is invalid"
        )

    raw_files = raw.get("files")
    if not isinstance(raw_files, dict):
        raise OriginalArchiveFormatError("The Original catalog files are invalid")
    files: list[OriginalManifestFile] = []
    for raw_path, raw_file in cast("dict[object, object]", raw_files).items():
        if not isinstance(raw_path, str) or not isinstance(raw_file, dict):
            raise OriginalArchiveFormatError(
                "The Original catalog contains an invalid file entry"
            )
        parts = tuple(_path_component(part) for part in raw_path.split("/"))
        fields = cast("dict[object, object]", raw_file)
        digest = fields.get("hash")
        size = fields.get("size")
        raw_modified_ns = fields.get("mtime_ns")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise OriginalArchiveFormatError(
                f"The Original entry for {raw_path!r} has an invalid SHA-256"
            )
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise OriginalArchiveFormatError(
                f"The Original entry for {raw_path!r} has an invalid size"
            )
        modified_ns: int | None
        if raw_modified_ns is None:
            modified_ns = None
        elif (
            isinstance(raw_modified_ns, bool)
            or not isinstance(raw_modified_ns, int)
            or not 0 <= raw_modified_ns <= _MAX_MTIME_NS
        ):
            raise OriginalArchiveFormatError(
                f"The Original entry for {raw_path!r} has an invalid modification time"
            )
        else:
            modified_ns = raw_modified_ns
        files.append(
            OriginalManifestFile(
                path_parts=parts,
                content=ContentIdentity(digest.casefold(), size),
                modified_ns=modified_ns,
            )
        )

    ordered = tuple(sorted(files, key=lambda item: item.path_parts))
    paths = tuple(item.path_parts for item in ordered)
    if len(set(paths)) != len(paths):
        raise OriginalArchiveFormatError("The Original catalog has duplicate paths")
    path_set = set(paths)
    for path in paths:
        if any(path[:depth] in path_set for depth in range(1, len(path))):
            raise OriginalArchiveFormatError(
                "The Original catalog nests a file beneath another file"
            )
    file_count = _non_negative_integer(raw.get("file_count"), "file count")
    total_size = _non_negative_integer(raw.get("total_size"), "total size")
    if file_count != len(ordered) or total_size != sum(
        item.content.size for item in ordered
    ):
        raise OriginalArchiveFormatError(
            "The Original catalog totals do not match its files"
        )

    reason_value = raw.get("reason", BackupReason.MANUAL.value)
    if not isinstance(reason_value, str):
        raise OriginalArchiveFormatError("The Original catalog reason is invalid")
    try:
        reason = _ORIGINAL_REASON_ALIASES.get(reason_value)
        if reason is None:
            reason = BackupReason(reason_value)
    except ValueError as error:
        raise OriginalArchiveFormatError(
            f"The Original catalog reason is unsupported: {reason_value!r}"
        ) from error
    return OriginalManifest(
        version=version,
        snapshot_id=expected_snapshot_id,
        timestamp=_optional_text(raw, "timestamp", expected_snapshot_id),
        device_id=expected_device_id,
        device_name=_optional_text(raw, "device_name", "iPod"),
        metadata=BackupDeviceMetadata.from_manifest(raw.get("device_meta")),
        identity_state=identity_state,
        reason=reason,
        note=_optional_text(raw, "note", ""),
        files=ordered,
        catalog_sha256=computed_digest,
    )


def original_catalog_digest(document: dict[str, object]) -> str:
    payload = {
        key: value for key, value in document.items() if key != "manifest_sha256"
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_component(value: str) -> str:
    # A backslash is deliberately legal: Original paths used '/' as their one
    # separator and a POSIX source could therefore contain a literal backslash.
    if not value or value in {".", ".."} or "\x00" in value or ":" in value:
        raise OriginalArchiveFormatError(
            f"The Original catalog has an unsafe path component: {value!r}"
        )
    return value


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OriginalArchiveFormatError(f"The Original catalog {label} is invalid")
    return value


def _optional_text(document: dict[str, object], key: str, default: str) -> str:
    value = document.get(key, default)
    if not isinstance(value, str):
        raise OriginalArchiveFormatError(f"The Original catalog {key!r} is invalid")
    return value or default


__all__ = [
    "OriginalArchiveFormatError",
    "OriginalManifest",
    "OriginalManifestFile",
    "decode_original_manifest",
    "original_catalog_digest",
]
