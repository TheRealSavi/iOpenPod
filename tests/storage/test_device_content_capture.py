"""Device captures reuse the copy's digest while retaining source-change guards."""

import hashlib
import os
from pathlib import Path
from typing import BinaryIO

import pytest

import storage._filesystem as filesystem_module
import storage.session as session_module
from storage import (
    ConcurrentModificationError,
    DevicePath,
    FilesystemSession,
    HostPath,
    SessionInvalidatedError,
    Storage,
)
from storage.content_workspace import StagedContent, content_workspace
from storage.testing import VirtualStoragePlatform


def _session(
    tmp_path: Path,
) -> tuple[Path, VirtualStoragePlatform, FilesystemSession]:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    return root, platform, storage.open_session(storage.discover().volumes[0])


@pytest.mark.parametrize("memory_budget", (0, 1024))
def test_capture_returns_source_fingerprint_without_a_second_device_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, memory_budget: int
) -> None:
    root, _, session = _session(tmp_path)
    source = root / "source.bin"
    source.write_bytes(b"retained device content")
    expected = session.fingerprint(DevicePath("source.bin"))
    device_opens: list[Path] = []
    open_original = filesystem_module.open_read_no_follow

    def open_counted(path: Path) -> BinaryIO:
        if path == source:
            device_opens.append(path)
        return open_original(path)

    monkeypatch.setattr(session_module, "open_read_no_follow", open_counted)
    monkeypatch.setattr(filesystem_module, "open_read_no_follow", open_counted)
    with content_workspace(
        memory_budget=memory_budget, checkpoint=lambda: None
    ) as workspace:
        data, fingerprint = workspace.capture_device_snapshot(
            session, DevicePath("source.bin")
        )
        actual = data.read_at(0, len(data)) if isinstance(data, StagedContent) else data
        assert actual == b"retained device content"
        assert fingerprint == expected
        assert device_opens == [source]


def test_transformed_export_reports_original_source_fingerprint(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    source = root / "source.bin"
    source.write_bytes(b"original")
    expected = session.fingerprint(DevicePath("source.bin"))
    destination = tmp_path / "tagged.bin"

    def tag(path: HostPath) -> None:
        Path(path).write_bytes(b"modified host file")

    result = session.copy_to_host(
        DevicePath("source.bin"), HostPath(destination), prepare_staged=tag
    )

    assert result.source_fingerprint == expected
    assert result.sha256 == hashlib.sha256(b"modified host file").hexdigest()
    assert result.bytes_copied == len(b"modified host file")


def test_capture_rejects_source_path_replacement_before_host_publication(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    source = root / "source.bin"
    source.write_bytes(b"original")
    original = source.stat()
    destination = tmp_path / "copied.bin"

    def replace_source(_path: HostPath) -> None:
        replacement = root / "replacement.bin"
        replacement.write_bytes(b"replaced")
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(source)

    with pytest.raises(ConcurrentModificationError, match="changed"):
        session.copy_to_host(
            DevicePath("source.bin"),
            HostPath(destination),
            prepare_staged=replace_source,
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".iop-*"))


def test_capture_rejects_disconnect_and_removes_partial_host_copy(
    tmp_path: Path,
) -> None:
    root, platform, session = _session(tmp_path)
    (root / "source.bin").write_bytes(b"original")
    destination = tmp_path / "copied.bin"

    with pytest.raises(SessionInvalidatedError):
        session.copy_to_host(
            DevicePath("source.bin"),
            HostPath(destination),
            progress=lambda _copied: platform.disconnect(root),
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".iop-*"))
