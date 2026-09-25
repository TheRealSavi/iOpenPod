"""Pure Backup Archive v4 manifest encoding and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

from iOpenPod.app.backups._json import StrictJsonError, loads_strict
from iOpenPod.app.backups.models import (
    ArchiveKey,
    BackupDeviceIdentity,
    BackupDeviceMetadata,
    BackupReason,
    ContentIdentity,
    LegacyIdentityClaim,
    SnapshotIdentityState,
)

BACKUP_REPOSITORY_DIRECTORY = "v4"
BACKUP_REPOSITORY_FORMAT = "iopenpod.backup.repository"
BACKUP_SNAPSHOT_FORMAT = "iopenpod.backup.snapshot"
BACKUP_FORMAT_VERSION = 4
FULL_SOURCE_VERIFICATION = "full_sha256"
INCREMENTAL_SOURCE_VERIFICATION = "streamed_sha256_with_metadata_reuse"
_SUPPORTED_SOURCE_VERIFICATION = frozenset(
    {FULL_SOURCE_VERIFICATION, INCREMENTAL_SOURCE_VERIFICATION}
)
MAX_MTIME_NS = (1 << 63) - 1
_NATIVE_REQUIRED_FIELDS = frozenset(
    {
        "format",
        "version",
        "id",
        "timestamp",
        "sequence",
        "archive_key",
        "device_name",
        "device_metadata",
        "identity_state",
        "identity",
        "reason",
        "note",
        "source_verification",
        "file_count",
        "total_size",
        "files",
        "catalog_sha256",
    }
)
_NATIVE_OPTIONAL_FIELDS = frozenset({"legacy_identity", "legacy_source"})
_NATIVE_FILE_FIELDS = frozenset({"path", "content", "modified_ns"})
_NATIVE_CONTENT_FIELDS = frozenset({"algorithm", "sha256", "size"})
_NATIVE_METADATA_FIELDS = frozenset(
    {"family", "generation", "color", "display_name", "product_image"}
)
_LEGACY_SOURCE_FIELDS = frozenset(
    {"format", "version", "device_identity", "snapshot_id", "catalog_sha256"}
)


class NativeArchiveFormatError(ValueError):
    """Repository bytes do not satisfy the Backup Archive v4 contract."""


@dataclass(frozen=True, slots=True)
class NativeManifestFile:
    path_parts: tuple[str, ...]
    content: ContentIdentity
    modified_ns: int | None

    def to_document(self) -> dict[str, object]:
        return {
            "path": list(self.path_parts),
            "content": {
                "algorithm": "sha256",
                "sha256": self.content.sha256,
                "size": self.content.size,
            },
            "modified_ns": self.modified_ns,
        }


@dataclass(frozen=True, slots=True)
class LegacySource:
    version: int
    device_identity: LegacyIdentityClaim
    snapshot_id: str
    catalog_sha256: str

    def to_document(self) -> dict[str, object]:
        return {
            "format": "original-iopenpod",
            "version": self.version,
            "device_identity": self.device_identity.to_manifest(),
            "snapshot_id": self.snapshot_id,
            "catalog_sha256": self.catalog_sha256,
        }


@dataclass(frozen=True, slots=True)
class NativeManifest:
    raw: dict[str, object]
    snapshot_id: str
    timestamp: str
    sequence: int
    archive_key: ArchiveKey
    device_name: str
    metadata: BackupDeviceMetadata
    identity_state: SnapshotIdentityState
    identity: BackupDeviceIdentity
    legacy_identity_claim: LegacyIdentityClaim | None
    reason: BackupReason
    note: str
    files: tuple[NativeManifestFile, ...]
    total_size: int
    catalog_sha256: str
    legacy_source: LegacySource | None = None


def encode_manifest(
    *,
    snapshot_id: str,
    timestamp: str,
    sequence: int,
    archive_key: ArchiveKey,
    device_name: str,
    metadata: BackupDeviceMetadata,
    identity_state: SnapshotIdentityState,
    identity: BackupDeviceIdentity,
    legacy_identity_claim: LegacyIdentityClaim | None,
    reason: BackupReason,
    note: str,
    files: tuple[NativeManifestFile, ...],
    legacy_source: LegacySource | None = None,
    source_verification: str = FULL_SOURCE_VERIFICATION,
) -> bytes:
    if source_verification not in _SUPPORTED_SOURCE_VERIFICATION:
        raise ValueError("Unsupported native Backup source verification")
    ordered_files = tuple(sorted(files, key=lambda item: item.path_parts))
    document: dict[str, object] = {
        "format": BACKUP_SNAPSHOT_FORMAT,
        "version": BACKUP_FORMAT_VERSION,
        "id": snapshot_id,
        "timestamp": timestamp,
        "sequence": sequence,
        "archive_key": archive_key.value,
        "device_name": device_name or "iPod",
        "device_metadata": metadata.to_manifest(),
        "identity_state": identity_state.value,
        "identity": identity.to_manifest(),
        "reason": reason.value,
        "note": note,
        "source_verification": source_verification,
        "file_count": len(ordered_files),
        "total_size": sum(item.content.size for item in ordered_files),
        "files": [item.to_document() for item in ordered_files],
    }
    if legacy_identity_claim is not None:
        document["legacy_identity"] = legacy_identity_claim.to_manifest()
    if legacy_source is not None:
        document["legacy_source"] = legacy_source.to_document()
    document["catalog_sha256"] = catalog_digest(document)
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def decode_manifest(
    data: bytes,
    *,
    expected_snapshot_id: str,
    expected_archive_key: ArchiveKey,
) -> NativeManifest:
    try:
        value = loads_strict(data)
    except StrictJsonError as error:
        raise NativeArchiveFormatError(
            f"The v4 catalog is unreadable: {error}"
        ) from error
    if not isinstance(value, dict):
        raise NativeArchiveFormatError("The v4 catalog is not a JSON object")
    raw = {
        key: item
        for key, item in cast("dict[object, object]", value).items()
        if isinstance(key, str)
    }
    fields = set(raw)
    if not _NATIVE_REQUIRED_FIELDS.issubset(fields) or not fields.issubset(
        _NATIVE_REQUIRED_FIELDS | _NATIVE_OPTIONAL_FIELDS
    ):
        raise NativeArchiveFormatError(
            "The Backup catalog fields do not match format version 4"
        )
    if (
        raw.get("format") != BACKUP_SNAPSHOT_FORMAT
        or raw.get("version") != BACKUP_FORMAT_VERSION
    ):
        raise NativeArchiveFormatError(
            "The v4 catalog format or version is unsupported"
        )
    if raw.get("id") != expected_snapshot_id:
        raise NativeArchiveFormatError(
            "The v4 catalog identity does not match its filename"
        )
    if raw.get("archive_key") != expected_archive_key.value:
        raise NativeArchiveFormatError(
            "The v4 catalog belongs to another Backup Archive"
        )
    if raw.get("source_verification") not in _SUPPORTED_SOURCE_VERIFICATION:
        raise NativeArchiveFormatError(
            "The v4 catalog source verification is unsupported"
        )
    recorded_digest = raw.get("catalog_sha256")
    try:
        computed_digest = catalog_digest(raw)
    except RecursionError as error:
        raise NativeArchiveFormatError(
            "The v4 catalog is too deeply nested to checksum"
        ) from error
    except UnicodeError as error:
        raise NativeArchiveFormatError(
            "The v4 catalog contains invalid Unicode text"
        ) from error
    if not isinstance(recorded_digest, str) or recorded_digest != computed_digest:
        raise NativeArchiveFormatError("The v4 catalog checksum is invalid")

    timestamp = _text(raw, "timestamp")
    device_name = _text(raw, "device_name") or "iPod"
    note = _text(raw, "note")
    sequence = _non_negative_integer(raw.get("sequence"), "sequence")
    file_count = _non_negative_integer(raw.get("file_count"), "file count")
    total_size = _non_negative_integer(raw.get("total_size"), "total size")
    try:
        reason = BackupReason(_text(raw, "reason"))
        identity_state = SnapshotIdentityState(_text(raw, "identity_state"))
        identity = BackupDeviceIdentity.from_manifest(raw.get("identity"))
        legacy_identity_claim = _decode_legacy_identity(raw.get("legacy_identity"))
    except ValueError as error:
        raise NativeArchiveFormatError(
            f"The v4 catalog metadata is invalid: {error}"
        ) from error
    if identity_state is SnapshotIdentityState.NATIVE and not identity.is_stable:
        raise NativeArchiveFormatError(
            "A native snapshot has no Backup Identifier claims"
        )
    if identity_state is not SnapshotIdentityState.NATIVE and identity.is_stable:
        raise NativeArchiveFormatError(
            "Only natively identified snapshots may contain Backup Identifier claims"
        )

    raw_files = raw.get("files")
    if not isinstance(raw_files, list):
        raise NativeArchiveFormatError("The v4 catalog files must be an array")
    files = tuple(_decode_file(item) for item in cast("list[object]", raw_files))
    paths = tuple(item.path_parts for item in files)
    if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
        raise NativeArchiveFormatError(
            "Native catalog paths are duplicate or noncanonical"
        )
    path_set = set(paths)
    if any(
        parts[:depth] in path_set for parts in paths for depth in range(1, len(parts))
    ):
        raise NativeArchiveFormatError("A v4 catalog nests a file beneath another file")
    computed_size = sum(item.content.size for item in files)
    if file_count != len(files) or total_size != computed_size:
        raise NativeArchiveFormatError("The v4 catalog totals do not match its files")

    metadata = _decode_metadata(raw.get("device_metadata"))
    legacy_source = _decode_legacy_source(raw.get("legacy_source"))
    if (legacy_source is None) is not (legacy_identity_claim is None):
        raise NativeArchiveFormatError(
            "Imported source metadata and its legacy identity must appear together"
        )
    if (
        legacy_source is not None
        and legacy_source.device_identity != legacy_identity_claim
    ):
        raise NativeArchiveFormatError(
            "Imported source metadata has a conflicting legacy identity"
        )
    if (
        identity_state
        in {
            SnapshotIdentityState.LEGACY_ASSERTED,
            SnapshotIdentityState.LEGACY_UNKNOWN,
        }
        and legacy_source is None
    ):
        raise NativeArchiveFormatError(
            "An imported Original snapshot has no legacy identity metadata"
        )
    if legacy_source is not None:
        reason = BackupReason.IMPORT
    return NativeManifest(
        raw=raw,
        snapshot_id=expected_snapshot_id,
        timestamp=timestamp,
        sequence=sequence,
        archive_key=expected_archive_key,
        device_name=device_name,
        metadata=metadata,
        identity_state=identity_state,
        identity=identity,
        legacy_identity_claim=legacy_identity_claim,
        reason=reason,
        note=note,
        files=files,
        total_size=total_size,
        catalog_sha256=recorded_digest,
        legacy_source=legacy_source,
    )


def repository_marker_bytes() -> bytes:
    value: dict[str, object] = {
        "format": BACKUP_REPOSITORY_FORMAT,
        "version": BACKUP_FORMAT_VERSION,
    }
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def validate_repository_marker(data: bytes) -> None:
    try:
        value = loads_strict(data)
    except StrictJsonError as error:
        raise NativeArchiveFormatError(
            f"The v4 repository marker is unreadable: {error}"
        ) from error
    if value != {
        "format": BACKUP_REPOSITORY_FORMAT,
        "version": BACKUP_FORMAT_VERSION,
    }:
        raise NativeArchiveFormatError("The v4 repository marker is unsupported")


def catalog_digest(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "catalog_sha256"}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replace_note(manifest: NativeManifest, note: str) -> bytes:
    updated = dict(manifest.raw)
    updated["note"] = note
    if manifest.legacy_source is not None:
        updated["reason"] = BackupReason.IMPORT.value
    updated["catalog_sha256"] = catalog_digest(updated)
    return (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _decode_file(value: object) -> NativeManifestFile:
    if not isinstance(value, dict):
        raise NativeArchiveFormatError("A native file entry is not an object")
    fields = cast("dict[str, object]", value)
    if set(fields) != set(_NATIVE_FILE_FIELDS):
        raise NativeArchiveFormatError("A native file entry has invalid fields")
    raw_path = fields.get("path")
    raw_content = fields.get("content")
    if not isinstance(raw_path, list) or not isinstance(raw_content, dict):
        raise NativeArchiveFormatError("A native file entry is incomplete")
    parts = tuple(_path_component(part) for part in cast("list[object]", raw_path))
    if not parts:
        raise NativeArchiveFormatError("A native Device Path must not be empty")
    content = cast("dict[str, object]", raw_content)
    if set(content) != set(_NATIVE_CONTENT_FIELDS):
        raise NativeArchiveFormatError("A native content identity has invalid fields")
    if content.get("algorithm") != "sha256":
        raise NativeArchiveFormatError("A native content algorithm is unsupported")
    digest = content.get("sha256")
    if not isinstance(digest, str):
        raise NativeArchiveFormatError("A native content digest is missing")
    try:
        identity = ContentIdentity(
            digest,
            _non_negative_integer(content.get("size"), "content size"),
        )
    except ValueError as error:
        raise NativeArchiveFormatError(str(error)) from error
    raw_modified_ns = fields.get("modified_ns")
    modified_ns = (
        None
        if raw_modified_ns is None
        else _non_negative_integer(raw_modified_ns, "modification time")
    )
    if modified_ns is not None and modified_ns > MAX_MTIME_NS:
        raise NativeArchiveFormatError("A native modification time is out of range")
    return NativeManifestFile(parts, identity, modified_ns)


def _path_component(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "\x00" in value
        or "/" in value
        or ":" in value
    ):
        raise NativeArchiveFormatError(
            f"Unsafe native Device Path component: {value!r}"
        )
    return value


def _decode_legacy_source(value: object) -> LegacySource | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NativeArchiveFormatError("The Legacy Backup Import metadata is invalid")
    fields = cast("dict[str, object]", value)
    if set(fields) != set(_LEGACY_SOURCE_FIELDS):
        raise NativeArchiveFormatError(
            "The Legacy Backup Import metadata has invalid fields"
        )
    if fields.get("format") != "original-iopenpod":
        raise NativeArchiveFormatError("The imported source format is invalid")
    version = _non_negative_integer(fields.get("version"), "legacy version")
    if version not in {2, 3}:
        raise NativeArchiveFormatError("The imported source version is unsupported")
    catalog_sha256 = _text(fields, "catalog_sha256")
    if len(catalog_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in catalog_sha256
    ):
        raise NativeArchiveFormatError("The imported source checksum is invalid")
    return LegacySource(
        version,
        _decode_required_legacy_identity(fields.get("device_identity")),
        _text(fields, "snapshot_id"),
        catalog_sha256,
    )


def _decode_metadata(value: object) -> BackupDeviceMetadata:
    if not isinstance(value, dict):
        raise NativeArchiveFormatError("The native device metadata is invalid")
    fields = cast("dict[str, object]", value)
    if set(fields) != set(_NATIVE_METADATA_FIELDS) or not all(
        isinstance(fields[field], str) for field in _NATIVE_METADATA_FIELDS
    ):
        raise NativeArchiveFormatError("The native device metadata is invalid")
    return BackupDeviceMetadata(
        family=cast("str", fields["family"]),
        generation=cast("str", fields["generation"]),
        color=cast("str", fields["color"]),
        display_name=cast("str", fields["display_name"]),
        product_image=cast("str", fields["product_image"]),
    )


def _decode_legacy_identity(value: object) -> LegacyIdentityClaim | None:
    if value is None:
        return None
    return _decode_required_legacy_identity(value)


def _decode_required_legacy_identity(value: object) -> LegacyIdentityClaim:
    try:
        return LegacyIdentityClaim.from_manifest(value)
    except ValueError as error:
        raise NativeArchiveFormatError(
            f"The imported source identity is invalid: {error}"
        ) from error


def _text(fields: dict[object, object] | dict[str, object], key: str) -> str:
    value = fields.get(key)
    if not isinstance(value, str):
        raise NativeArchiveFormatError(f"The v4 catalog {key!r} must be text")
    return value


def _non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NativeArchiveFormatError(f"The v4 catalog {label} is invalid")
    return value


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "BACKUP_REPOSITORY_DIRECTORY",
    "FULL_SOURCE_VERIFICATION",
    "INCREMENTAL_SOURCE_VERIFICATION",
    "MAX_MTIME_NS",
    "LegacySource",
    "NativeArchiveFormatError",
    "NativeManifest",
    "NativeManifestFile",
    "catalog_digest",
    "decode_manifest",
    "encode_manifest",
    "replace_note",
    "repository_marker_bytes",
    "validate_repository_marker",
]
