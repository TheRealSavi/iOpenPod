"""Folder usage counts all safe regular files independently of Library metadata."""

from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_game_installation import volume

from iOpenPod.app.services import device_storage
from iOpenPod.app.services.device_storage import (
    ALBUM_ARTWORK_STORAGE_ROOTS,
    GAME_STORAGE_ROOTS,
    capture_folder_storage_bytes,
)
from storage import (
    DeviceEntry,
    DeviceEntryKind,
    DevicePath,
    FilesystemSession,
    StorageOperationError,
)


def test_counts_all_three_trees_without_requiring_manifests_or_reading_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with volume(tmp_path) as (session, root):
        for path in GAME_STORAGE_ROOTS:
            directory = root / str(path)
            (directory / "unknown/nested/empty").mkdir(parents=True)
            (directory / "shared.bin").write_bytes(b"shared")
            (directory / "unknown/nested/file.bin").write_bytes(b"content")
            (directory / "empty.bin").touch()
        (root / "iPod_Control/GameStats_WO_extra").mkdir()
        (root / "iPod_Control/GameStats_WO_extra/ignored.bin").write_bytes(b"other")

        def no_file_reads(*_args: object, **_kwargs: object) -> None:
            pytest.fail("Measuring game usage must not open file contents")

        monkeypatch.setattr(FilesystemSession, "read_snapshot", no_file_reads)

        assert (
            capture_folder_storage_bytes(session, GAME_STORAGE_ROOTS, lambda: None)
            == 39
        )


@pytest.mark.parametrize("roots", [GAME_STORAGE_ROOTS, ALBUM_ARTWORK_STORAGE_ROOTS])
def test_missing_folders_are_zero(
    tmp_path: Path, roots: tuple[DevicePath, ...]
) -> None:
    with volume(tmp_path) as (session, _root):
        assert capture_folder_storage_bytes(session, roots, lambda: None) == 0


def test_links_are_never_followed_or_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with volume(tmp_path) as (session, root):
        directory = root / str(GAME_STORAGE_ROOTS[0])
        directory.mkdir(parents=True)
        (directory / "regular.bin").write_bytes(b"regular")
        original = FilesystemSession.list_directory

        def with_link(
            current: FilesystemSession, path: DevicePath
        ) -> tuple[DeviceEntry, ...]:
            assert path == GAME_STORAGE_ROOTS[0]
            return (
                *original(current, path),
                DeviceEntry(
                    path.joinpath("link"), DeviceEntryKind.LINK_OR_REPARSE_POINT, 999, 0
                ),
            )

        monkeypatch.setattr(FilesystemSession, "list_directory", with_link)

        assert (
            capture_folder_storage_bytes(session, GAME_STORAGE_ROOTS, lambda: None) == 7
        )


def test_enumeration_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with volume(tmp_path) as (session, root):
        directory = root / str(GAME_STORAGE_ROOTS[0])
        directory.mkdir(parents=True)
        (directory / "one.bin").touch()
        (directory / "two.bin").touch()
        monkeypatch.setattr(device_storage, "_MAX_ENTRIES", 1)

        with pytest.raises(StorageOperationError, match="entry limit"):
            capture_folder_storage_bytes(session, GAME_STORAGE_ROOTS, lambda: None)


def test_cancellation_stops_nested_enumeration(tmp_path: Path) -> None:
    with volume(tmp_path) as (session, root):
        directory = root / str(GAME_STORAGE_ROOTS[0])
        (directory / "nested").mkdir(parents=True)
        calls = 0

        def cancel() -> None:
            nonlocal calls
            calls += 1
            if calls == 6:
                raise InterruptedError("cancelled")

        with pytest.raises(InterruptedError, match="cancelled"):
            capture_folder_storage_bytes(session, GAME_STORAGE_ROOTS, cancel)


def test_artwork_counts_database_shards_and_unrecognized_files(tmp_path: Path) -> None:
    with volume(tmp_path) as (session, root):
        directory = root / "iPod_Control/Artwork"
        (directory / "nested/empty").mkdir(parents=True)
        (directory / "ArtworkDB").write_bytes(b"database")
        (directory / "F1061_1.ithmb").write_bytes(b"thumbnails")
        (directory / "nested/unknown.bin").write_bytes(b"unknown")
        (root / "iPod_Control/Artwork_extra").mkdir()
        (root / "iPod_Control/Artwork_extra/excluded.bin").write_bytes(b"excluded")

        assert (
            capture_folder_storage_bytes(
                session, ALBUM_ARTWORK_STORAGE_ROOTS, lambda: None
            )
            == 25
        )
