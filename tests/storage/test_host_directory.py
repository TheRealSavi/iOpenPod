"""Host enumeration pins directories and reuses one observed identity per entry."""

import os
import sys
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from storage import (
    ConcurrentModificationError,
    HostPath,
    StorageError,
    UnsafeFilesystemPathError,
)
from storage.host_directory import HostEntryKind, LocalHostDirectory
from storage.host_input import LocalHostFile


def test_listing_returns_typed_entries_with_reusable_identity_observations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    first = root / "first.bin"
    first.write_bytes(b"first")
    nested = root / "nested"
    nested.mkdir()
    (nested / "second.bin").write_bytes(b"second")
    observed = LocalHostDirectory.observe(HostPath(root))
    entries = observed.list_entries(checkpoint=lambda: None)
    assert tuple(entry.path.path.name for entry in entries) == ("first.bin", "nested")
    file_entry, directory_entry = entries
    assert file_entry.kind is HostEntryKind.FILE
    assert file_entry.file == LocalHostFile.observe(HostPath(first))
    assert file_entry.size_bytes == 5
    assert file_entry.modified_ns == first.stat().st_mtime_ns
    assert file_entry.directory is None
    assert directory_entry.kind is HostEntryKind.DIRECTORY
    assert directory_entry.directory is not None
    assert directory_entry.directory == LocalHostDirectory.observe(HostPath(nested))
    assert directory_entry.file is None
    children = directory_entry.directory.list_entries(checkpoint=lambda: None)
    assert len(children) == 1 and children[0].file is not None
    with children[0].file.open_read() as stream:
        assert stream.read() == b"second"


@pytest.mark.parametrize("include_directories", [False, True])
def test_filtered_listing_skips_unneeded_file_metadata_and_preserves_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, include_directories: bool
) -> None:
    (tmp_path / "track.wav").write_bytes(b"track")
    (tmp_path / "cover.png").write_bytes(b"cover")
    (tmp_path / "notes.txt").write_text("unneeded", encoding="utf-8")
    (tmp_path / "album.txt").mkdir()
    observed = LocalHostDirectory.observe(HostPath(tmp_path))
    native_scandir = os.scandir
    native_lstat = Path.lstat
    statted: list[str] = []

    class Entry:
        def __init__(self, original: os.DirEntry[str]) -> None:
            self.original = original
            self.name = original.name

        def is_dir(self, *, follow_symlinks: bool) -> bool:
            return self.original.is_dir(follow_symlinks=follow_symlinks)

        def stat(self, *, follow_symlinks: bool) -> os.stat_result:
            statted.append(self.name)
            return self.original.stat(follow_symlinks=follow_symlinks)

    @contextmanager
    def scandir(path: Path | int) -> Generator[Iterator[Entry]]:
        with native_scandir(path) as iterator:
            yield (Entry(entry) for entry in iterator)

    def lstat(path: Path) -> os.stat_result:
        if path.parent == tmp_path:
            statted.append(path.name)
        return native_lstat(path)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(Path, "lstat", lstat)
    discovered: list[HostPath] = []
    entries = observed.list_entries(
        checkpoint=lambda: None,
        include_file=lambda name: name in {"track.wav", "cover.png"},
        include_directories=include_directories,
        on_entry=lambda entry: discovered.append(entry.path),
    )
    expected = {"track.wav", "cover.png"}
    if include_directories:
        expected.add("album.txt")
    assert set(statted) == expected
    assert {entry.path.path.name for entry in entries} == expected
    assert set(discovered) == {entry.path for entry in entries}
    assert all(
        entry.file is not None for entry in entries if entry.kind is HostEntryKind.FILE
    )


def test_filtered_listing_still_rejects_directory_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    observed = LocalHostDirectory.observe(HostPath(root))
    root.rename(tmp_path / "old-root")
    root.mkdir()
    with pytest.raises(ConcurrentModificationError):
        observed.list_entries(
            checkpoint=lambda: None,
            include_file=lambda name: False,
            include_directories=False,
            on_issue=lambda path, error: None,
        )


@pytest.mark.parametrize("parent_link", [False, True])
def test_selected_directory_and_parent_links_are_rejected(
    tmp_path: Path, parent_link: bool
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "nested").mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host does not permit symlink creation: {error}")
    selected = alias / "nested" if parent_link else alias
    with pytest.raises(UnsafeFilesystemPathError):
        LocalHostDirectory.observe(HostPath(selected))


def test_child_links_are_reported_without_following_or_granting_read_observations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"private")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host does not permit symlink creation: {error}")
    entries = LocalHostDirectory.observe(HostPath(root)).list_entries(
        checkpoint=lambda: None
    )
    assert len(entries) == 1
    assert entries[0].kind is HostEntryKind.LINK_OR_REPARSE_POINT
    assert entries[0].file is None and entries[0].directory is None


def test_replaced_directory_is_rejected_even_with_same_timestamp(
    tmp_path: Path,
) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    observed = LocalHostDirectory.observe(HostPath(root))
    root.rename(tmp_path / "previous")
    root.mkdir()
    os.utime(root, ns=(observed.modified_ns, observed.modified_ns))
    with pytest.raises(ConcurrentModificationError):
        observed.list_entries(checkpoint=lambda: None)


def test_directory_change_during_listing_rejects_partial_results(
    tmp_path: Path,
) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    (root / "first.bin").write_bytes(b"first")
    observed = LocalHostDirectory.observe(HostPath(root))
    calls = 0

    def change() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            (root / "late.bin").write_bytes(b"late")
            changed = observed.modified_ns + 2_000_000_000
            os.utime(root, ns=(changed, changed))

    with pytest.raises(ConcurrentModificationError):
        observed.list_entries(checkpoint=change)


def test_best_effort_listing_reports_churn_without_losing_readable_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "first.bin").write_bytes(b"first")
    observed = LocalHostDirectory.observe(HostPath(tmp_path))
    (tmp_path / "late.bin").write_bytes(b"late")
    changed = observed.modified_ns + 2_000_000_000
    os.utime(tmp_path, ns=(changed, changed))
    issues: list[OSError | StorageError] = []
    entries = observed.list_entries(
        checkpoint=lambda: None, on_issue=lambda path, error: issues.append(error)
    )
    assert {entry.path.path.name for entry in entries} == {"first.bin", "late.bin"}
    assert issues


def test_best_effort_listing_still_rejects_a_replaced_directory(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    observed = LocalHostDirectory.observe(HostPath(root))
    root.rename(tmp_path / "original")
    root.mkdir()
    with pytest.raises(ConcurrentModificationError):
        observed.list_entries(
            checkpoint=lambda: None, on_issue=lambda path, error: None
        )


def test_listing_cannot_follow_directory_swap_after_pinning(tmp_path: Path) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    (root / "approved.bin").write_bytes(b"approved")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.bin").write_bytes(b"private")
    observed = LocalHostDirectory.observe(HostPath(root))
    attempted = False

    def swap() -> None:
        nonlocal attempted
        if attempted:
            return
        # The first checkpoint precedes pinning; a child checkpoint runs after it.
        if not seen:
            seen.append(True)
            return
        attempted = True
        if os.name == "nt":
            with pytest.raises(PermissionError):
                root.rename(tmp_path / "renamed")
        else:
            root.rename(tmp_path / "renamed")
            root.symlink_to(outside, target_is_directory=True)

    seen: list[bool] = []
    if os.name == "nt":
        entries = observed.list_entries(checkpoint=swap)
        assert tuple(entry.path.path.name for entry in entries) == ("approved.bin",)
    else:
        with pytest.raises(UnsafeFilesystemPathError):
            observed.list_entries(checkpoint=swap)
    assert attempted


def test_enumeration_does_not_revalidate_ancestors_for_every_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number in range(50):
        (tmp_path / f"file-{number}.bin").write_bytes(b"file")
    observed = LocalHostDirectory.observe(HostPath(tmp_path))
    native = Path.lstat
    calls: list[Path] = []

    def counted(path: Path) -> os.stat_result:
        calls.append(path)
        return native(path)

    monkeypatch.setattr(Path, "lstat", counted)
    entries = observed.list_entries(checkpoint=lambda: None)
    assert len(entries) == 50
    assert all(entry.file is not None for entry in entries)
    leaf_calls = [path for path in calls if path.name.startswith("file-")]
    assert len(leaf_calls) == (50 if os.name == "nt" else 0)
    assert len(calls) - len(leaf_calls) <= 3 * (len(tmp_path.parents) + 1)


def test_listing_cancellation_preserves_exception_and_releases_pins(
    tmp_path: Path,
) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    (root / "first.bin").write_bytes(b"first")
    observed = LocalHostDirectory.observe(HostPath(root))
    error = InterruptedError("cancelled while enumerating")
    calls = 0

    def cancel() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error

    with pytest.raises(InterruptedError) as caught:
        observed.list_entries(checkpoint=cancel)
    assert caught.value is error
    root.rename(tmp_path / "unpinned")


def test_special_file_never_receives_read_observation(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("Windows has no POSIX FIFO")
    os.mkfifo(tmp_path / "pipe")
    (entry,) = LocalHostDirectory.observe(HostPath(tmp_path)).list_entries(
        checkpoint=lambda: None
    )
    assert entry.kind is HostEntryKind.OTHER
    assert entry.file is None and entry.directory is None
