"""Read-only Original Backup Archive import into the v4 repository."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import iOpenPod.app.backups.original_archive as original_archive_module
import iOpenPod.app.backups.repository as repository_module
from iOpenPod.app.backups import (
    ArchiveKey,
    BackupDeviceIdentity,
    BackupIdentityClaim,
    BackupIdentityClaimKind,
    BackupRepository,
    LegacyIdentityClaim,
    LegacyImportIdentityAssignment,
    SnapshotIdentityState,
)
from iOpenPod.app.backups.archive import catalog_digest

if TYPE_CHECKING:
    import pytest


def _digest(document: dict[str, object]) -> str:
    payload = {
        key: value for key, value in document.items() if key != "manifest_sha256"
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_original(
    root: Path,
    *,
    version: int,
    identity_marker: bool | None,
    shared_object: bool,
    with_mtime: bool,
    reason: str = "manual",
) -> tuple[str, str, bytes]:
    device_id = "LEGACY_SERIAL"
    snapshot_id = f"legacy-v{version}"
    content = b"legacy database"
    digest = hashlib.sha256(content).hexdigest()
    object_root = root if shared_object else root / device_id
    blob = object_root / "blobs" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(content)
    file_info: dict[str, object] = {"hash": digest, "size": len(content)}
    if with_mtime:
        file_info["mtime_ns"] = 1_700_000_000_000_000_000
    document: dict[str, object] = {
        "version": version,
        "id": snapshot_id,
        "timestamp": "2026-02-28T15:14:00+00:00",
        "device_id": device_id,
        "device_name": "LegacyPod",
        "device_meta": {"model_family": "iPod Classic"},
        "reason": reason,
        "note": "Original archive",
        "file_count": 1,
        "total_size": len(content),
        # Splitting only on '/' must retain this literal POSIX backslash.
        "files": {"iPod_Control/Music/name\\literal.mp3": file_info},
    }
    if identity_marker is not None:
        document["identity_is_stable"] = identity_marker
    if version == 3:
        document["manifest_sha256"] = _digest(document)
    manifest = root / device_id / "snapshots" / f"{snapshot_id}.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return device_id, snapshot_id, content


def _source_files(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _identity_assignment(device_id: str) -> LegacyImportIdentityAssignment:
    identity = BackupDeviceIdentity(
        (
            BackupIdentityClaim.from_hardware(
                BackupIdentityClaimKind.PRODUCT_SERIAL,
                device_id,
            ),
        )
    )
    return LegacyImportIdentityAssignment(
        legacy_identity_claim=LegacyIdentityClaim.from_original_key(device_id),
        archive_key=ArchiveKey.for_identity(identity),
        identity=identity,
    )


def test_import_original_v2_preserves_unknown_identity_missing_mtime_and_backslash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, _, content = _write_original(
        source,
        version=2,
        identity_marker=None,
        shared_object=False,
        with_mtime=False,
    )
    before = _source_files(source)
    repository = BackupRepository(tmp_path / "native")

    result = repository.import_original(source)

    assert not result.failures
    assert len(result.imported) == 1
    imported = result.imported[0]
    assert imported.identity_state is SnapshotIdentityState.LEGACY_UNKNOWN
    assert imported.requires_restore_confirmation
    expected_identity = LegacyIdentityClaim.from_original_key(device_id)
    assert imported.legacy_identity_claim == expected_identity
    with repository.open_verified_snapshot(imported.device_id, imported.id) as snapshot:
        assert snapshot.legacy_identity_claim == expected_identity
        assert snapshot.files[0].path_parts == (
            "iPod_Control",
            "Music",
            "name\\literal.mp3",
        )
        assert snapshot.files[0].modified_ns is None
        imported_object = Path(str(snapshot.files[0].source))
        assert imported_object.read_bytes() == content
    assert _source_files(source) == before
    imported_object.write_bytes(b"corrupt")

    repeated = repository.import_original(source)

    assert not repeated.imported
    assert len(repeated.already_imported) == 1
    assert imported_object.read_bytes() == content
    assert _source_files(source) == before


def test_matching_connected_serial_assigns_an_original_v2_snapshot_native_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, _, _ = _write_original(
        source,
        version=2,
        identity_marker=None,
        shared_object=False,
        with_mtime=False,
    )
    assignment = _identity_assignment(device_id)
    repository = BackupRepository(tmp_path / "native")

    result = repository.import_original(
        source,
        identity_assignments=(assignment,),
    )

    assert not result.failures
    assert len(result.imported) == 1
    imported = result.imported[0]
    assert imported.device_id == assignment.archive_key.value
    assert imported.identity_state is SnapshotIdentityState.NATIVE
    assert imported.legacy_identity_claim == assignment.legacy_identity_claim
    with repository.open_verified_snapshot(imported.device_id, imported.id) as snapshot:
        assert snapshot.identity.matches(assignment.identity)
        assert snapshot.legacy_identity_claim == assignment.legacy_identity_claim


def test_explicitly_unstable_original_snapshot_ignores_native_identity_assignment(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, _, _ = _write_original(
        source,
        version=3,
        identity_marker=False,
        shared_object=True,
        with_mtime=True,
    )
    assignment = _identity_assignment(device_id)
    repository = BackupRepository(tmp_path / "native")

    result = repository.import_original(
        source,
        identity_assignments=(assignment,),
    )

    assert not result.failures
    assert len(result.imported) == 1
    imported = result.imported[0]
    assert imported.device_id == ArchiveKey.for_legacy(device_id).value
    assert imported.identity_state is SnapshotIdentityState.UNSTABLE


def test_import_original_v3_verifies_checksum_and_preserves_asserted_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, _, _ = _write_original(
        source,
        version=3,
        identity_marker=True,
        shared_object=True,
        with_mtime=True,
    )
    repository = BackupRepository(tmp_path / "native")

    result = repository.import_original(source)

    assert not result.failures
    assert result.imported[0].identity_state is SnapshotIdentityState.LEGACY_ASSERTED
    manifest_path = next((tmp_path / "native" / "v4" / "archives").rglob("*.json"))
    document = cast(
        "dict[str, object]", json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    assert document["format"] == "iopenpod.backup.snapshot"
    legacy_source = cast("dict[str, object]", document["legacy_source"])
    assert legacy_source["version"] == 3
    assert "device_id" not in legacy_source
    assert "legacy_device_id" not in document
    assert "source_volume_identity_key" not in document
    assert device_id not in manifest_path.as_posix()
    assert device_id not in manifest_path.read_text(encoding="utf-8")


def test_import_classifies_original_snapshot_as_import_regardless_of_source_reason(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    _write_original(
        source,
        version=3,
        identity_marker=True,
        shared_object=True,
        with_mtime=True,
        reason="pre_sync",
    )

    result = BackupRepository(tmp_path / "native").import_original(source)

    assert not result.failures
    assert result.imported[0].reason.value == "import"


def test_existing_import_with_manual_reason_projects_as_import(tmp_path: Path) -> None:
    source = tmp_path / "original"
    source.mkdir()
    _write_original(
        source,
        version=3,
        identity_marker=True,
        shared_object=True,
        with_mtime=True,
    )
    native = tmp_path / "native"
    repository = BackupRepository(native)
    imported = repository.import_original(source).imported[0]
    manifest_path = next((native / "v4" / "archives").rglob("*.json"))
    document = cast(
        "dict[str, object]",
        json.loads(manifest_path.read_text(encoding="utf-8")),
    )
    document["reason"] = "manual"
    document["catalog_sha256"] = catalog_digest(document)
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    snapshot = repository.list_snapshots(imported.device_id)[0]

    assert snapshot.reason.value == "import"


def test_import_does_not_use_a_legacy_device_key_as_a_missing_display_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, snapshot_id, _ = _write_original(
        source,
        version=3,
        identity_marker=True,
        shared_object=True,
        with_mtime=True,
    )
    source_manifest = source / device_id / "snapshots" / f"{snapshot_id}.json"
    source_document = cast(
        "dict[str, object]", json.loads(source_manifest.read_text(encoding="utf-8"))
    )
    source_document.pop("device_name")
    source_document["manifest_sha256"] = _digest(source_document)
    source_manifest.write_text(json.dumps(source_document), encoding="utf-8")
    native = tmp_path / "native"

    result = BackupRepository(native).import_original(source)

    assert not result.failures
    assert result.imported[0].device_name == "iPod"
    native_manifest = next((native / "v4" / "archives").rglob("*.json"))
    assert device_id not in native_manifest.as_posix()
    assert device_id not in native_manifest.read_text(encoding="utf-8")


def test_import_original_rejects_corrupt_v3_without_publishing_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, snapshot_id, _ = _write_original(
        source,
        version=3,
        identity_marker=False,
        shared_object=True,
        with_mtime=True,
    )
    manifest = source / device_id / "snapshots" / f"{snapshot_id}.json"
    document = cast("dict[str, object]", json.loads(manifest.read_text()))
    document["note"] = "tampered"
    manifest.write_text(json.dumps(document))
    repository = BackupRepository(tmp_path / "native")

    result = repository.import_original(source)

    assert not result.imported
    assert len(result.failures) == 1
    assert "checksum" in result.failures[0].detail.casefold()
    assert repository.list_devices() == ()


def test_original_catalog_reads_are_bounded_before_json_decoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    _write_original(
        source,
        version=3,
        identity_marker=True,
        shared_object=True,
        with_mtime=True,
    )
    repository = BackupRepository(tmp_path / "native")
    monkeypatch.setattr(repository_module, "_MAX_CATALOG_BYTES", 32)

    result = repository.import_original(source)

    assert result.imported == ()
    assert result.already_imported == ()
    assert len(result.failures) == 1
    assert "exceeds its supported size" in result.failures[0].detail
    assert repository.list_devices() == ()


def test_original_catalog_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    source = tmp_path / "original"
    source.mkdir()
    device_id, snapshot_id, _ = _write_original(
        source,
        version=3,
        identity_marker=True,
        shared_object=True,
        with_mtime=True,
    )
    manifest = source / device_id / "snapshots" / f"{snapshot_id}.json"
    encoded = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        encoded.replace('"version": 3', '"version": 2, "version": 3', 1),
        encoding="utf-8",
    )

    result = BackupRepository(tmp_path / "native").import_original(source)

    assert result.imported == ()
    assert len(result.failures) == 1
    assert "Duplicate JSON field" in result.failures[0].detail


def test_original_catalog_reports_canonicalization_recursion_as_format_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "original"
    source.mkdir()
    _write_original(
        source,
        version=2,
        identity_marker=True,
        shared_object=False,
        with_mtime=True,
    )

    def fail_digest(_document: dict[str, object]) -> str:
        raise RecursionError("catalog nesting")

    monkeypatch.setattr(
        original_archive_module,
        "original_catalog_digest",
        fail_digest,
    )

    result = BackupRepository(tmp_path / "native").import_original(source)

    assert result.imported == ()
    assert len(result.failures) == 1
    assert "too deeply nested" in result.failures[0].detail
