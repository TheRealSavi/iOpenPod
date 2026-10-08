"""Resolving an explicit selection never relaxes the normal no-link readers."""

import os
from pathlib import Path

import pytest

from storage import HostPath, UnsafeFilesystemPathError
from storage.host_directory import LocalHostDirectory, resolve_host_entry
from storage.host_input import (
    HostSelectionResolver,
    LocalHostFile,
    resolve_host_selection,
)


def _link(alias: Path, target: Path, *, directory: bool = False) -> None:
    try:
        alias.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"Host cannot create symbolic links: {error}")


def test_selection_resolves_relative_parent_links_then_uses_strict_readers(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "real"
    directory.mkdir()
    source = directory / "song.wav"
    source.write_bytes(b"song")
    alias = tmp_path / "alias"
    _link(alias, Path("real"), directory=True)
    _link(tmp_path / "selected.wav", Path("alias/song.wav"))
    assert resolve_host_selection(HostPath(alias)) == HostPath(directory)
    entry = resolve_host_entry(HostPath(tmp_path / "selected.wav"))
    assert entry.path == HostPath(source) and entry.file is not None
    assert entry.file.read_bytes(max_bytes=4, checkpoint=lambda: None) == b"song"
    with pytest.raises(UnsafeFilesystemPathError):
        LocalHostFile.observe(HostPath(alias / "song.wav"))
    with pytest.raises(UnsafeFilesystemPathError):
        LocalHostDirectory.observe(HostPath(alias))


def test_selection_rejects_broken_and_cyclic_links(tmp_path: Path) -> None:
    _link(tmp_path / "broken", tmp_path / "missing")
    _link(tmp_path / "first", tmp_path / "second")
    _link(tmp_path / "second", tmp_path / "first")
    with pytest.raises(FileNotFoundError):
        resolve_host_selection(HostPath(tmp_path / "broken"))
    with pytest.raises(UnsafeFilesystemPathError, match="cycle"):
        resolve_host_selection(HostPath(tmp_path / "first"))


@pytest.mark.skipif(os.name == "nt", reason="Windows has no POSIX FIFO")
def test_selection_rejects_special_targets(tmp_path: Path) -> None:
    mkfifo = getattr(os, "mkfifo", None)
    assert mkfifo is not None
    mkfifo(tmp_path / "fifo")
    _link(tmp_path / "linked.wav", tmp_path / "fifo")
    with pytest.raises(UnsafeFilesystemPathError):
        resolve_host_selection(HostPath(tmp_path / "linked.wav"))


def test_replacing_a_resolved_target_with_a_link_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"song")
    other = tmp_path / "other.wav"
    other.write_bytes(b"other")
    _link(tmp_path / "selected.wav", source)
    entry = resolve_host_entry(HostPath(tmp_path / "selected.wav"))
    assert entry.file is not None
    source.unlink()
    _link(source, other)
    with pytest.raises(UnsafeFilesystemPathError):
        entry.file.read_bytes(max_bytes=100, checkpoint=lambda: None)


def test_resolution_reuses_ancestor_probes_without_granting_read_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for name in ("one.wav", "two.wav"):
        (root / name).write_bytes(b"song")
    native = Path.lstat
    probes: list[Path] = []

    def lstat(path: Path) -> os.stat_result:
        probes.append(path)
        return native(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    resolver = HostSelectionResolver()
    resolver.resolve(HostPath(root / "one.wav"))
    probes.clear()
    assert resolver.resolve(HostPath(root / "two.wav")) == HostPath(root / "two.wav")
    assert probes == [root / "two.wav"]
    # A cached ordinary ancestor must never bypass the read-time link check.
    moved = tmp_path / "moved"
    root.rename(moved)
    _link(root, moved, directory=True)
    path = resolver.resolve(HostPath(root / "two.wav"))
    with pytest.raises(UnsafeFilesystemPathError):
        LocalHostFile.observe(path)
