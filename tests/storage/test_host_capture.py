"""Selected Host inputs are stable snapshots, with bounded reads and cleanup."""

import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from storage import (
    ConcurrentModificationError,
    FileSizeLimitError,
    HostPath,
    UnsafeFilesystemPathError,
    capture_host_file,
)


def test_capture_is_independent_of_later_source_edits_and_is_cleaned(
    tmp_path: Path,
) -> None:
    source = tmp_path / "selected.bin"
    source.write_bytes(b"original")
    with capture_host_file(HostPath(source), checkpoint=lambda: None) as captured:
        snapshot = Path(captured.snapshot)
        source.write_bytes(b"replaced")
        assert snapshot.read_bytes() == b"original"
        assert captured.source == HostPath(source)
        assert captured.fingerprint.sha256 == hashlib.sha256(b"original").hexdigest()
        assert captured.fingerprint.size == 8
    assert not snapshot.parent.exists()


def test_capture_does_not_translate_caller_failure_and_cleans_up(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"data")
    error = OSError("caller failure")
    snapshot: Path | None = None
    with (
        pytest.raises(OSError) as caught,
        capture_host_file(HostPath(source), checkpoint=lambda: None) as captured,
    ):
        snapshot = Path(captured.snapshot)
        raise error
    assert caught.value is error
    assert snapshot is not None
    assert not snapshot.parent.exists()


@pytest.mark.parametrize("change", ["replace", "grow", "rewrite"])
def test_capture_rejects_changes_during_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from storage import host_capture

    monkeypatch.setattr(host_capture, "COPY_CHUNK_SIZE", 4)
    source = tmp_path / "input"
    source.write_bytes(b"original content")
    before = source.stat()
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            if change == "replace":
                other = tmp_path / "new"
                other.write_bytes(b"original content")
                other.replace(source)
            elif change == "grow":
                with source.open("ab") as output:
                    output.write(b"more")
            else:
                source.write_bytes(b"different bytes!")
                os.utime(
                    source, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000)
                )

    # Windows can prohibit replacing the open source before our recheck is needed.
    expected = (
        (ConcurrentModificationError, PermissionError)
        if change == "replace"
        else (ConcurrentModificationError,)
    )
    with (
        pytest.raises(expected),
        capture_host_file(HostPath(source), checkpoint=checkpoint),
    ):
        pytest.fail("A changed source must not produce a snapshot")


def test_capture_checks_limit_and_file_kind(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"data")
    with (
        pytest.raises(FileSizeLimitError),
        capture_host_file(HostPath(source), checkpoint=lambda: None, max_bytes=3),
    ):
        pytest.fail("Oversized source accepted")
    with (
        pytest.raises(UnsafeFilesystemPathError),
        capture_host_file(HostPath(tmp_path), checkpoint=lambda: None),
    ):
        pytest.fail("Directory accepted")


def test_capture_cancellation_during_copy_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source = tmp_path / "input"
    source.write_bytes(b"data")
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise InterruptedError("cancelled")

    # Cancellation exceptions, even OSError subclasses, must retain their identity.
    with (
        pytest.raises(InterruptedError),
        capture_host_file(HostPath(source), checkpoint=checkpoint),
    ):
        pytest.fail("Cancelled capture accepted")
    assert list(tmp_path.iterdir()) == [source]
