"""Checksummed persistence codec for unresolved restore recovery records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from typing import cast

from iOpenPod.app.backups._json import StrictJsonError, loads_strict
from iOpenPod.app.backups.archive import BACKUP_FORMAT_VERSION
from iOpenPod.app.backups.models import (
    ArchiveKey,
    BackupDeviceIdentity,
    RestoreRecoveryOutcome,
    RestoreRecoveryPhase,
    RestoreRecoveryRecord,
)
from storage import DevicePath

RECOVERY_FORMAT = "iopenpod.backup.restore-recovery"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECOVERY_FIELDS = frozenset(
    {
        "format",
        "version",
        "id",
        "target_archive_key",
        "safety_archive_key",
        "current_identity",
        "target_snapshot_id",
        "safety_snapshot_id",
        "operation_journal",
        "recovery_material_identity",
        "phase",
        "outcome",
        "created_at",
        "updated_at",
        "record_sha256",
    }
)


class RestoreRecoveryFormatError(ValueError):
    """A restore recovery record cannot safely authorize recovery."""


def encode_recovery(record: RestoreRecoveryRecord) -> bytes:
    document: dict[str, object] = {
        "format": RECOVERY_FORMAT,
        "version": BACKUP_FORMAT_VERSION,
        "id": record.id,
        "target_archive_key": record.target_archive_key.value,
        "safety_archive_key": record.safety_archive_key.value,
        "current_identity": record.current_identity.to_manifest(),
        "target_snapshot_id": record.target_snapshot_id,
        "safety_snapshot_id": record.safety_snapshot_id,
        "operation_journal": list(record.operation_journal.parts),
        "recovery_material_identity": record.recovery_material_identity,
        "phase": record.phase.value,
        "outcome": record.outcome.value,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    document["record_sha256"] = recovery_digest(document)
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def decode_recovery(data: bytes, *, expected_id: str) -> RestoreRecoveryRecord:
    try:
        value = loads_strict(data)
    except StrictJsonError as error:
        raise RestoreRecoveryFormatError(
            f"The restore recovery record is unreadable: {error}"
        ) from error
    if not isinstance(value, dict):
        raise RestoreRecoveryFormatError("The restore recovery record is not an object")
    document = {
        key: item
        for key, item in cast("dict[object, object]", value).items()
        if isinstance(key, str)
    }
    if set(document) != set(_RECOVERY_FIELDS):
        raise RestoreRecoveryFormatError(
            "The restore recovery fields do not match Backup format version 4"
        )
    if (
        document.get("format") != RECOVERY_FORMAT
        or document.get("version") != BACKUP_FORMAT_VERSION
    ):
        raise RestoreRecoveryFormatError(
            "The restore recovery record format or version is unsupported"
        )
    if document.get("id") != expected_id:
        raise RestoreRecoveryFormatError(
            "The restore recovery identity does not match its filename"
        )
    checksum = document.get("record_sha256")
    try:
        computed_digest = recovery_digest(document)
    except RecursionError as error:
        raise RestoreRecoveryFormatError(
            "The restore recovery record is too deeply nested to checksum"
        ) from error
    except UnicodeError as error:
        raise RestoreRecoveryFormatError(
            "The restore recovery record contains invalid Unicode text"
        ) from error
    if not isinstance(checksum, str) or checksum != computed_digest:
        raise RestoreRecoveryFormatError("The restore recovery checksum is invalid")
    raw_journal = document.get("operation_journal")
    if not isinstance(raw_journal, list) or not all(
        isinstance(part, str) for part in cast("list[object]", raw_journal)
    ):
        raise RestoreRecoveryFormatError("The Operation Journal path is invalid")
    try:
        identity = BackupDeviceIdentity.from_manifest(document.get("current_identity"))
        if not identity.is_stable:
            raise ValueError("Current Backup Identifier is unavailable")
        record = RestoreRecoveryRecord(
            id=expected_id,
            target_archive_key=ArchiveKey(_text(document, "target_archive_key")),
            safety_archive_key=ArchiveKey(_text(document, "safety_archive_key")),
            current_identity=identity,
            target_snapshot_id=_text(document, "target_snapshot_id"),
            safety_snapshot_id=_text(document, "safety_snapshot_id"),
            operation_journal=DevicePath.from_parts(
                tuple(cast("list[str]", raw_journal))
            ),
            recovery_material_identity=_text(document, "recovery_material_identity"),
            phase=RestoreRecoveryPhase(_text(document, "phase")),
            outcome=RestoreRecoveryOutcome(_text(document, "outcome")),
            created_at=_text(document, "created_at"),
            updated_at=_text(document, "updated_at"),
        )
    except ValueError as error:
        raise RestoreRecoveryFormatError(
            f"The restore recovery record is invalid: {error}"
        ) from error
    if _SHA256.fullmatch(record.recovery_material_identity) is None:
        raise RestoreRecoveryFormatError(
            "The restore recovery material identity is invalid"
        )
    return record


def update_recovery_phase(
    record: RestoreRecoveryRecord,
    phase: RestoreRecoveryPhase,
    *,
    updated_at: str,
) -> RestoreRecoveryRecord:
    return replace(record, phase=phase, updated_at=updated_at)


def recovery_digest(document: dict[str, object]) -> str:
    payload = {key: value for key, value in document.items() if key != "record_sha256"}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise RestoreRecoveryFormatError(
            f"The restore recovery field {key!r} is invalid"
        )
    return value


__all__ = [
    "RestoreRecoveryFormatError",
    "decode_recovery",
    "encode_recovery",
    "recovery_digest",
    "update_recovery_phase",
]
