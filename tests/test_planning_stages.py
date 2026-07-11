from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from iopenpod.infrastructure.media_folders import MediaFolderEntry
from iopenpod.sync.path_identity import stable_path_key
from iopenpod.sync.planning_stages import scan_source_libraries


def _track(path, *, is_podcast: bool = False) -> Any:
    return SimpleNamespace(path=str(path), is_podcast=is_podcast)


def test_scan_source_libraries_expands_selected_playlist_tracks(tmp_path) -> None:
    main = tmp_path / "main.mp3"
    extra = tmp_path / "extra.mp3"
    playlist = tmp_path / "mix.m3u8"
    main.write_bytes(b"main")
    extra.write_bytes(b"extra")
    playlist.write_text("extra.mp3\n", encoding="utf-8")

    class FakePCLibrary:
        root_entries: list[MediaFolderEntry] = [MediaFolderEntry(str(tmp_path))]

        def scan(
            self,
            progress_callback: Callable[[int, int, str], None] | None = None,
            include_video: bool = True,
            max_workers: int | None = None,
            is_cancelled: Callable[[], bool] | None = None,
        ) -> Iterator[Any]:
            return iter([_track(main)])

        def _read_track(
            self,
            file_path: Path,
            library_root: Path | None = None,
        ) -> Any | None:
            if stable_path_key(file_path) == stable_path_key(extra):
                return _track(extra)
            return None

    result = scan_source_libraries(
        FakePCLibrary(),
        supports_video=True,
        supports_podcast=True,
        sync_workers=0,
        allowed_paths=frozenset({str(main)}),
        selected_playlist_paths=frozenset({str(playlist)}),
    )

    assert not result.cancelled
    assert result.selected_playlist_source_keys == frozenset({stable_path_key(playlist)})
    assert {stable_path_key(track.path) for track in result.pc_tracks} == {
        stable_path_key(main),
        stable_path_key(extra),
    }


def test_scan_source_libraries_filters_podcasts_when_unsupported(tmp_path) -> None:
    music = tmp_path / "song.mp3"
    podcast = tmp_path / "episode.mp3"

    class FakePCLibrary:
        root_entries: list[MediaFolderEntry] = []

        def scan(
            self,
            progress_callback: Callable[[int, int, str], None] | None = None,
            include_video: bool = True,
            max_workers: int | None = None,
            is_cancelled: Callable[[], bool] | None = None,
        ) -> Iterator[Any]:
            return iter([_track(music), _track(podcast, is_podcast=True)])

        def _read_track(
            self,
            file_path: Path,
            library_root: Path | None = None,
        ) -> Any | None:
            return None

    result = scan_source_libraries(
        FakePCLibrary(),
        supports_video=True,
        supports_podcast=False,
        sync_workers=0,
        allowed_paths=None,
        selected_playlist_paths=None,
    )

    assert [track.path for track in result.pc_tracks] == [str(music)]
