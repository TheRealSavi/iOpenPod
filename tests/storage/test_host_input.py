"""Untrusted local references cannot turn file approval into arbitrary access."""

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

from storage import (
    ConcurrentModificationError,
    FileSizeLimitError,
    HostPath,
    UnsafeFilesystemPathError,
)
from storage.host_input import LocalHostFile, resolve_local_file_reference


@pytest.mark.parametrize(
    "reference",
    [
        "https://example.org/song.mp3",
        "smb://server/share/song.mp3",
        "file://server/share/song.mp3",
        "//server/share/song.mp3",
        r"\\server\share\song.mp3",
        r"\\?\C:\song.mp3",
        r"\\.\pipe\song.mp3",
        "file:////server/share/song.mp3",
        "file://localhost/%2fserver/share/song.mp3",
        "file:///C:/song.mp3:secret",
        "file:///tmp/song%00.mp3",
        "file:///tmp/song.mp3?command=run",
        "C:relative.mp3",
        "NUL.mp3",
        "aux/song.mp3",
        "nested/track.mp3:stream",
        "bad\x01.mp3",
        "file:relative.mp3",
    ],
)
def test_rejects_unsafe_reference_without_filesystem_access(
    tmp_path: Path, reference: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Reference resolution must not touch the filesystem")

    monkeypatch.setattr(Path, "stat", unexpected)
    monkeypatch.setattr(Path, "lstat", unexpected)
    with pytest.raises(ValueError):
        resolve_local_file_reference(reference, HostPath(tmp_path / "Mix.m3u"))


def test_resolves_local_paths_and_uris_without_expanding_shell_syntax(
    tmp_path: Path,
) -> None:
    source = HostPath(tmp_path / "Mix.m3u")
    target = tmp_path / "Artist Name" / "Song #1.mp3"
    assert resolve_local_file_reference(target.as_uri(), source) == HostPath(target)
    assert resolve_local_file_reference(
        r'"Artist Name\Song #1.mp3"', source
    ) == HostPath(target)
    assert resolve_local_file_reference("literal%20name.mp3", source) == HostPath(
        tmp_path / "literal%20name.mp3"
    )
    assert resolve_local_file_reference("$HOME/song.mp3", source) == HostPath(
        tmp_path / "$HOME/song.mp3"
    )


def test_local_file_reads_are_bounded_and_capture_is_private_and_cleaned(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Song.wav"
    path.write_bytes(b"audio")
    observed = LocalHostFile.observe(HostPath(path))
    with pytest.raises(FileSizeLimitError):
        observed.read_bytes(max_bytes=4, checkpoint=lambda: None)
    assert observed.read_bytes(max_bytes=5, checkpoint=lambda: None) == b"audio"
    with observed.capture(checkpoint=lambda: None) as captured:
        snapshot = Path(captured)
        assert snapshot.name == path.name
        assert snapshot != path
        path.write_bytes(b"changed")
        assert snapshot.read_bytes() == b"audio"
    assert not snapshot.exists()


def test_replaced_reviewed_file_is_rejected_even_when_size_and_mtime_match(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Song.wav"
    path.write_bytes(b"audio")
    observed = LocalHostFile.observe(HostPath(path))
    replacement = tmp_path / "Replacement.wav"
    replacement.write_bytes(b"other")
    os.utime(replacement, ns=(observed.modified_ns, observed.modified_ns))
    replacement.replace(path)
    with pytest.raises(ConcurrentModificationError):
        observed.read_bytes(max_bytes=100, checkpoint=lambda: None)


@pytest.mark.parametrize("parent_link", [False, True])
def test_link_components_are_never_followed(tmp_path: Path, parent_link: bool) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    (target / "Song.wav").write_bytes(b"audio")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(
            target if parent_link else target / "Song.wav",
            target_is_directory=parent_link,
        )
    except OSError as error:
        pytest.skip(f"Host does not permit symlink creation: {error}")
    with pytest.raises(UnsafeFilesystemPathError):
        LocalHostFile.observe(HostPath(alias / "Song.wav" if parent_link else alias))


def test_capture_cancellation_cleans_up_and_preserves_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source = tmp_path / "Song.wav"
    source.write_bytes(b"audio")
    error = InterruptedError("cancelled")

    def cancel() -> None:
        raise error

    with (
        pytest.raises(InterruptedError) as caught,
        LocalHostFile.observe(HostPath(source)).capture(checkpoint=cancel),
    ):
        pytest.fail("Cancelled capture must not be published")
    assert caught.value is error
    assert tuple(tmp_path.iterdir()) == (source,)


def test_directories_and_special_files_are_not_media(tmp_path: Path) -> None:
    with pytest.raises(UnsafeFilesystemPathError):
        LocalHostFile.observe(HostPath(tmp_path))
    if sys.platform != "win32":
        pipe = tmp_path / "pipe.mp3"
        os.mkfifo(pipe)
        with pytest.raises(UnsafeFilesystemPathError):
            LocalHostFile.observe(HostPath(pipe))


def test_link_swap_between_validation_and_open_cannot_redirect_the_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "Selected.mp3"
    secret = tmp_path / "Private.mp3"
    source.write_bytes(b"approved")
    secret.write_bytes(b"private")
    observed = LocalHostFile.observe(HostPath(source))
    validate_original = LocalHostFile.validate

    def validate_then_swap(file: LocalHostFile) -> None:
        validate_original(file)
        source.unlink()
        try:
            source.symlink_to(secret)
        except OSError as error:
            pytest.skip(f"Host does not permit symlink creation: {error}")

    monkeypatch.setattr(LocalHostFile, "validate", validate_then_swap)
    with pytest.raises(
        (UnsafeFilesystemPathError, ConcurrentModificationError, OSError)
    ):
        observed.read_bytes(max_bytes=100, checkpoint=lambda: None)


def test_oversized_input_is_rejected_before_opening_or_allocating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "Oversized.m3u"
    with path.open("wb") as stream:
        stream.seek(8 * 1024 * 1024)
        stream.write(b"x")
    observed = LocalHostFile.observe(HostPath(path))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Oversized document must be rejected before it is opened")

    monkeypatch.setattr(LocalHostFile, "validate", forbidden)
    with pytest.raises(FileSizeLimitError):
        observed.read_bytes(max_bytes=8 * 1024 * 1024, checkpoint=lambda: None)


def test_scoped_stream_is_seekable_read_only_and_closed_on_exit(tmp_path: Path) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"first\nsecond")
    observed = LocalHostFile.observe(HostPath(path))
    with observed.open_read() as stream:
        assert stream.readable() and stream.seekable() and not stream.writable()
        assert stream.read(5) == b"first"
        assert stream.seek(6) == 6
        assert stream.read() == b"second"
        assert stream.seek(0) == 0
        assert stream.readline() == b"first\n"
        assert os.fstat(stream.fileno()).st_size == observed.size_bytes
        with pytest.raises(io.UnsupportedOperation):
            stream.write(b"replacement")
    assert stream.closed
    assert path.read_bytes() == b"first\nsecond"


def test_scoped_stream_cancellation_propagates_and_closes_handles(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"file")
    observed = LocalHostFile.observe(HostPath(path))
    error = InterruptedError("cancelled while reading")
    cancelled = False

    def checkpoint() -> None:
        if cancelled:
            raise error

    with (
        pytest.raises(InterruptedError) as caught,
        observed.open_read(checkpoint=checkpoint) as stream,
    ):
        cancelled = True
        stream.read()
    assert caught.value is error and stream.closed
    path.rename(tmp_path / "released.bin")


def test_scoped_stream_detects_changes_or_prevents_them_on_windows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"first")
    observed = LocalHostFile.observe(HostPath(path))
    if os.name == "nt":
        with observed.open_read() as stream:
            assert stream.read() == b"first"
            with pytest.raises(PermissionError):
                path.write_bytes(b"changed")
    else:
        with pytest.raises(ConcurrentModificationError), observed.open_read() as stream:
            assert stream.read() == b"first"
            path.write_bytes(b"changed")


def test_scoped_stream_limit_precedes_open_and_caller_close_is_safe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"file")
    observed = LocalHostFile.observe(HostPath(path))
    with pytest.raises(FileSizeLimitError), observed.open_read(max_bytes=3):
        pytest.fail("An oversized source must not be opened")
    with observed.open_read(max_bytes=4) as stream:
        stream.close()
    assert path.read_bytes() == b"file"


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing-mode protection")
def test_scoped_stream_pins_parent_directory_against_replacement(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "selected"
    parent.mkdir()
    source = parent / "source.bin"
    source.write_bytes(b"approved")
    observed = LocalHostFile.observe(HostPath(source))
    with observed.open_read() as stream:
        with pytest.raises(PermissionError):
            parent.rename(tmp_path / "renamed")
        assert stream.read() == b"approved"
    parent.rename(tmp_path / "unpinned")
