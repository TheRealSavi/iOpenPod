"""Verified replacement retains recovery bytes across failure boundaries."""

import json
from pathlib import Path

import pytest

from storage import (
    AccessMode,
    DevicePath,
    FilePreconditionError,
    FilesystemSession,
    RecoverableWriteError,
    Storage,
)
from storage.testing import VirtualStoragePlatform


def _session(tmp_path: Path) -> tuple[Path, VirtualStoragePlatform, FilesystemSession]:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    )
    return root, platform, session


def test_replacement_retains_original_and_can_restore_it(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("database.bin")
    (root / str(path)).write_bytes(b"original")
    result = session.replace_with_recovery(
        path, b"replacement", expected=session.fingerprint(path)
    )
    assert session.read(path) == b"replacement"
    journal = json.loads(session.read(result.recovery_path))
    assert journal["state"] == "committed"
    restored = session.restore_replacement(
        result.recovery_path, expected=result.write.fingerprint
    )
    assert session.read(path) == b"original"
    assert (
        session.restore_replacement(
            result.recovery_path, expected=restored.fingerprint
        ).fingerprint
        == restored.fingerprint
    )


def test_recovery_refuses_to_overwrite_a_later_edit(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("database.bin")
    (root / str(path)).write_bytes(b"original")
    result = session.replace_with_recovery(
        path, b"replacement", expected=session.fingerprint(path)
    )
    session.atomic_write(path, b"later edit", expected=result.write.fingerprint)
    with pytest.raises(FilePreconditionError, match="unrelated"):
        session.restore_replacement(
            result.recovery_path, expected=session.fingerprint(path)
        )
    assert session.read(path) == b"later edit"


def test_disconnection_before_publication_keeps_source_and_recovery(
    tmp_path: Path,
) -> None:
    root, platform, session = _session(tmp_path)
    path = DevicePath("database.bin")
    (root / str(path)).write_bytes(b"original")
    with pytest.raises(RecoverableWriteError) as caught:
        session.replace_with_recovery(
            path,
            b"replacement",
            expected=session.fingerprint(path),
            before_publish=lambda: platform.disconnect(root),
        )
    assert (root / str(path)).read_bytes() == b"original"
    journal = root / caught.value.recovery_path
    assert json.loads(journal.read_bytes())["state"] == "prepared"
    assert journal.with_name("original.bin").read_bytes() == b"original"


def test_callback_cancellation_does_not_publish(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("database.bin")
    (root / str(path)).write_bytes(b"original")

    def cancelled() -> None:
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        session.replace_with_recovery(
            path,
            b"replacement",
            expected=session.fingerprint(path),
            before_publish=cancelled,
        )
    assert session.read(path) == b"original"


def test_recovery_verifies_backup_before_overwriting(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("database.bin")
    (root / str(path)).write_bytes(b"original")
    result = session.replace_with_recovery(
        path, b"replacement", expected=session.fingerprint(path)
    )
    (root / str(result.recovery_path)).with_name("original.bin").write_bytes(
        b"tampered"
    )
    from storage import StorageOperationError

    with pytest.raises(StorageOperationError, match="recovery copy"):
        session.restore_replacement(
            result.recovery_path, expected=result.write.fingerprint
        )
    assert session.read(path) == b"replacement"


def test_failed_postpublication_verification_retains_original_and_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    root, _, session = _session(tmp_path)
    path = DevicePath("database.bin")
    target = root / str(path)
    target.write_bytes(b"original")
    replace_file = os.replace

    def corrupted_publish(source: Path, destination: Path) -> None:
        replace_file(source, destination)
        if destination == target:
            target.write_bytes(b"corrupted")

    monkeypatch.setattr(os, "replace", corrupted_publish)
    with pytest.raises(RecoverableWriteError) as caught:
        session.replace_with_recovery(
            path, b"replacement", expected=session.fingerprint(path)
        )
    assert caught.value.publication_started
    journal = root / caught.value.recovery_path
    assert json.loads(journal.read_bytes())["state"] == "prepared"
    assert journal.with_name("original.bin").read_bytes() == b"original"
