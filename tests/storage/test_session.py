"""Safety and data-integrity tests for the Filesystem Session portal."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import storage._filesystem as storage_filesystem
from storage import (
    AccessMode,
    DeviceEntryKind,
    DevicePath,
    DevicePathNotFoundError,
    FilePreconditionError,
    FileSizeLimitError,
    FilesystemSession,
    HostPath,
    InvalidDevicePathError,
    ReadOnlyFilesystemError,
    SessionClosedError,
    SessionInvalidatedError,
    Storage,
    StorageCapacityError,
    StorageOperationError,
    UnsafeFilesystemPathError,
)
from storage.testing import VirtualStoragePlatform


def _session(
    tmp_path: Path,
    *,
    writable: bool = True,
    max_file_size_bytes: int | None = None,
    filesystem_type: str = "virtual",
) -> tuple[Path, VirtualStoragePlatform, FilesystemSession]:
    root = tmp_path / "volume"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        writable=writable,
        max_file_size_bytes=max_file_size_bytes,
        filesystem_type=filesystem_type,
    )
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    access = AccessMode.READ_WRITE if writable else AccessMode.READ_ONLY
    session = storage.open_session(storage.discover().volumes[0], access=access)
    return root, platform, session


def test_reads_stats_and_lists_only_root_bound_device_paths(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    music = root / "Music"
    music.mkdir()
    (music / "B.mp3").write_bytes(b"second")
    (music / "a.mp3").write_bytes(b"first")

    entries = session.list_directory(DevicePath("Music"))
    snapshot = session.read_snapshot(DevicePath("Music/a.mp3"))

    assert [entry.path.name for entry in entries] == ["a.mp3", "B.mp3"]
    assert all(entry.kind is DeviceEntryKind.FILE for entry in entries)
    assert snapshot.data == b"first"
    assert snapshot.fingerprint.size == 5
    assert session.stat(DevicePath("Music")).kind is DeviceEntryKind.DIRECTORY
    assert session.fingerprint(DevicePath("Music/a.mp3")) == snapshot.fingerprint
    assert session.free_space() > 0


@pytest.mark.parametrize(
    "component",
    ("CON", "aux.txt", "trailing.", "trailing ", "wild?.mp3", "control\x01"),
)
def test_windows_device_operations_reject_unrepresentable_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
) -> None:
    _, _, session = _session(tmp_path)
    monkeypatch.setattr(storage_filesystem, "_WINDOWS_PATH_SEMANTICS", True)

    with pytest.raises(InvalidDevicePathError, match="not representable"):
        session.exists(DevicePath.from_parts((component,)))


def test_root_listing_stays_path_typed_without_exposing_mount_point(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    (root / "iPod_Control").mkdir()
    (root / "note.txt").write_bytes(b"note")

    entries = session.list_root()

    assert [str(entry.path) for entry in entries] == ["iPod_Control", "note.txt"]
    assert entries[0].kind is DeviceEntryKind.DIRECTORY
    assert entries[1].kind is DeviceEntryKind.FILE


def test_missing_and_oversized_reads_have_typed_failures(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    (root / "large.bin").write_bytes(b"1234")

    with pytest.raises(DevicePathNotFoundError):
        session.read(DevicePath("missing.bin"))
    with pytest.raises(StorageOperationError, match="allowed read size"):
        session.read(DevicePath("large.bin"), max_bytes=3)
    with pytest.raises(ValueError, match="non-negative"):
        session.read(DevicePath("large.bin"), max_bytes=-1)


def test_range_reads_are_bounded_without_loading_the_whole_device_file(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    (root / "shared.ithmb").write_bytes(b"prefixARTWORKsuffix")

    assert (
        session.read_range(
            DevicePath("shared.ithmb"),
            offset=6,
            length=7,
        )
        == b"ARTWORK"
    )

    with pytest.raises(ValueError, match="non-negative"):
        session.read_range(DevicePath("shared.ithmb"), offset=-1, length=1)
    with pytest.raises(StorageOperationError, match="outside"):
        session.read_range(DevicePath("shared.ithmb"), offset=6, length=100)


def test_range_snapshots_expose_a_lightweight_identity_for_safe_caching(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    source = root / "shared.ithmb"
    source.write_bytes(b"prefixARTWORKsuffix")

    snapshot = session.read_range_snapshot(
        DevicePath("shared.ithmb"),
        offset=6,
        length=7,
    )

    assert snapshot.data == b"ARTWORK"
    assert snapshot.identity.size == len(b"prefixARTWORKsuffix")
    assert snapshot.identity == session.file_identity(DevicePath("shared.ithmb"))
    source.write_bytes(b"prefixCHANGEDsuffix")
    assert session.file_identity(DevicePath("shared.ithmb")) != snapshot.identity


def test_atomic_write_is_create_only_unless_given_an_exact_fingerprint(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("iPod_Control/iTunes/iTunesDB")

    created = session.atomic_write(path, b"one", create_parents=True)
    assert not created.replaced_existing
    assert (root / Path(str(path))).read_bytes() == b"one"

    with pytest.raises(FilePreconditionError):
        session.atomic_write(path, b"unconditional replacement")

    replaced = session.atomic_write(path, b"two", expected=created.fingerprint)
    assert replaced.replaced_existing
    assert (root / Path(str(path))).read_bytes() == b"two"
    assert not tuple((root / "iPod_Control" / "iTunes").glob(".iop-*.tmp"))


def test_modified_time_update_requires_exact_file_content(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("track.mp3")
    created = session.atomic_write(path, b"audio")
    requested = 946_684_800_000_000_000

    entry = session.set_modified_time(path, requested, expected=created.fingerprint)

    assert entry.modified_ns == requested
    stale = session.fingerprint(path)
    (root / "track.mp3").write_bytes(b"changed")
    with pytest.raises(FilePreconditionError):
        session.set_modified_time(path, requested + 1, expected=stale)


def test_stale_fingerprint_never_overwrites_a_newer_file(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("database.bin")
    initial = session.atomic_write(path, b"initial")
    (root / "database.bin").write_bytes(b"external change")

    with pytest.raises(FilePreconditionError, match="changed since"):
        session.atomic_write(path, b"stale replacement", expected=initial.fingerprint)

    assert (root / "database.bin").read_bytes() == b"external change"
    assert not tuple(root.glob(".iop-*.tmp"))


def test_write_checks_filesystem_limit_capacity_and_reserve(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path, max_file_size_bytes=3)

    with pytest.raises(FileSizeLimitError):
        session.atomic_write(DevicePath("too-large.bin"), b"1234")
    with pytest.raises(StorageCapacityError):
        session.atomic_write(
            DevicePath("no-space.bin"),
            b"1",
            reserve_bytes=10**30,
        )
    with pytest.raises(ValueError, match="non-negative"):
        session.atomic_write(
            DevicePath("bad-reserve.bin"),
            b"1",
            reserve_bytes=-1,
        )

    assert tuple(root.iterdir()) == ()


def test_host_copies_are_streamed_and_never_replace_existing_destinations(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    host_source = tmp_path / "source.mp3"
    host_source.write_bytes(b"host audio")

    imported = session.copy_from_host(
        HostPath(host_source),
        DevicePath("Music/F00/track.mp3"),
        create_parents=True,
    )
    host_destination = tmp_path / "export.mp3"
    copied_bytes: list[int] = []
    exported = session.copy_to_host(
        DevicePath("Music/F00/track.mp3"),
        HostPath(host_destination),
        progress=copied_bytes.append,
    )

    assert imported.fingerprint.sha256 == exported.sha256
    assert exported.bytes_copied == len(b"host audio")
    assert copied_bytes == [len(b"host audio")]
    assert host_destination.read_bytes() == b"host audio"
    assert (root / "Music" / "F00" / "track.mp3").read_bytes() == b"host audio"

    with pytest.raises(FilePreconditionError):
        session.copy_to_host(
            DevicePath("Music/F00/track.mp3"),
            HostPath(host_destination),
        )


def test_host_export_prepares_the_staged_copy_before_atomic_publication(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    (root / "track.mp3").write_bytes(b"audio")
    destination = tmp_path / "prepared.mp3"
    staged_suffixes: list[str] = []

    def prepare(path: HostPath) -> None:
        staged = Path(os.fspath(path))
        staged_suffixes.append(staged.suffix)
        staged.write_bytes(b"tagged audio")

    result = session.copy_to_host(
        DevicePath("track.mp3"),
        HostPath(destination),
        prepare_staged=prepare,
    )

    assert destination.read_bytes() == b"tagged audio"
    assert result.bytes_copied == len(b"tagged audio")
    assert staged_suffixes == [".mp3"]


def test_failed_host_export_preparation_never_publishes_a_partial_file(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    (root / "track.mp3").write_bytes(b"audio")
    destination = tmp_path / "failed.mp3"

    def fail(path: HostPath) -> None:
        Path(os.fspath(path)).write_bytes(b"partial tags")
        raise RuntimeError("tag injection failed")

    with pytest.raises(RuntimeError, match="tag injection failed"):
        session.copy_to_host(
            DevicePath("track.mp3"),
            HostPath(destination),
            prepare_staged=fail,
        )

    assert not destination.exists()
    assert not tuple(tmp_path.glob(".iop-*"))


def test_move_trash_and_restore_require_verified_source_content(tmp_path: Path) -> None:
    root, _, session = _session(tmp_path)
    source = DevicePath("Music/F00/source.mp3")
    created = session.atomic_write(source, b"audio", create_parents=True)

    moved = session.move(
        source,
        DevicePath("Music/F01/moved.mp3"),
        expected_source=created.fingerprint,
        create_parents=True,
    )
    assert moved.fingerprint.sha256 == created.fingerprint.sha256
    assert not (root / "Music" / "F00" / "source.mp3").exists()

    entry = session.trash(DevicePath("Music/F01/moved.mp3"))
    assert not (root / "Music" / "F01" / "moved.mp3").exists()
    assert (root / Path(str(entry.trash_path))).read_bytes() == b"audio"

    session.restore_trash(entry)
    assert (root / "Music" / "F01" / "moved.mp3").read_bytes() == b"audio"
    assert not (root / Path(str(entry.trash_path))).exists()


def test_trash_requires_unchanged_file_and_can_remove_empty_parents(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath("Music/F00/track.mp3")
    session.atomic_write(path, b"first", create_parents=True)
    expected = session.fingerprint(path)
    (root / str(path)).write_bytes(b"later")

    with pytest.raises(FilePreconditionError):
        session.trash(path, expected=expected, remove_empty_parents=True)

    current = session.fingerprint(path)
    session.trash(path, expected=current, remove_empty_parents=True)

    assert not (root / "Music").exists()


def test_read_only_and_revoked_write_authority_fail_closed(tmp_path: Path) -> None:
    root, platform, read_only = _session(tmp_path, writable=False)
    with pytest.raises(ReadOnlyFilesystemError):
        read_only.atomic_write(DevicePath("file.bin"), b"data")

    other_tmp = tmp_path / "writable"
    other_tmp.mkdir()
    other_root, other_platform, writable = _session(other_tmp)
    other_platform.set_writable(other_root, False)

    with pytest.raises(ReadOnlyFilesystemError):
        writable.atomic_write(DevicePath("file.bin"), b"data")
    with pytest.raises(SessionInvalidatedError):
        writable.exists(DevicePath("file.bin"))

    assert not (root / "file.bin").exists()
    assert not platform.flush_count(root)


def test_device_symlink_cannot_redirect_access_outside_the_volume(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.bin").write_bytes(b"secret")
    try:
        (root / "redirect").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host does not permit symlink creation: {error}")

    with pytest.raises(UnsafeFilesystemPathError):
        session.read(DevicePath("redirect/secret.bin"))


def test_windows_unrepresentable_device_component_fails_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, session = _session(tmp_path)
    path = DevicePath.from_parts(("literal\\name",))
    monkeypatch.setattr(storage_filesystem, "_WINDOWS_PATH_SEMANTICS", True)

    with pytest.raises(InvalidDevicePathError, match="Windows"):
        session.atomic_write(path, b"data", create_parents=True)

    assert not (root / "literal" / "name").exists()


def test_flush_and_close_have_explicit_lifecycle_results(tmp_path: Path) -> None:
    root, platform, session = _session(tmp_path)

    result = session.flush()
    assert result.complete
    assert platform.flush_count(root) == 1

    session.close()
    with pytest.raises(SessionClosedError):
        session.exists(DevicePath("anything"))


def test_modified_time_comparison_uses_the_bound_filesystem_precision(
    tmp_path: Path,
) -> None:
    _, _, session = _session(tmp_path, filesystem_type="fat32")

    assert session.modified_time_matches(10_000_000_000, 12_000_000_000)
    assert not session.modified_time_matches(10_000_000_000, 12_000_000_001)


def test_time_comparison_uses_session_facts_without_reinspecting_the_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, platform, session = _session(tmp_path, filesystem_type="fat32")

    def unexpected_reinspection(*_args: object) -> None:
        pytest.fail("Comparing already observed times must not inspect the Volume")

    monkeypatch.setattr(platform, "reinspect", unexpected_reinspection)
    assert session.modified_time_matches(10_000_000_000, 11_000_000_000)
    session.invalidate("disconnected")
    with pytest.raises(SessionInvalidatedError):
        session.modified_time_matches(10_000_000_000, 11_000_000_000)


def test_time_comparison_rejects_closed_session(tmp_path: Path) -> None:
    _, _, session = _session(tmp_path)
    session.close()
    with pytest.raises(SessionClosedError):
        session.modified_time_matches(0, 0)


def test_host_source_symlink_is_rejected_when_the_host_supports_symlinks(
    tmp_path: Path,
) -> None:
    _, _, session = _session(tmp_path)
    source = tmp_path / "actual.mp3"
    alias = tmp_path / "alias.mp3"
    source.write_bytes(b"audio")
    try:
        alias.symlink_to(source)
    except OSError as error:
        pytest.skip(f"Host does not permit symlink creation: {error}")

    with pytest.raises(UnsafeFilesystemPathError):
        session.copy_from_host(HostPath(alias), DevicePath("track.mp3"))


def test_all_device_facing_mutations_are_local_to_storage() -> None:
    storage_root = Path(__file__).parents[2] / "src" / "storage"
    forbidden = ("device_registry", "iPodDB", "iOpenPod")

    for source in storage_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert all(f"import {name}" not in text for name in forbidden), source
        assert all(f"from {name}" not in text for name in forbidden), source


def test_virtual_device_fixture_does_not_require_a_physical_volume(
    tmp_path: Path,
) -> None:
    root, _, session = _session(tmp_path)
    result = session.atomic_write(DevicePath("proof.bin"), memoryview(b"safe"))

    assert os.fspath(root) in os.fspath(root / "proof.bin")
    assert result.fingerprint.size == 4
