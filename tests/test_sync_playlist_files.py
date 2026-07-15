from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from iopenpod.infrastructure.media_folders import MediaFolderEntry
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync._playlist_builder import build_and_evaluate_playlists
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.sync_playlist_files import (
    SYNC_PLAYLIST_SOURCE,
    discover_sync_playlist_files,
    is_managed_sync_playlist_id,
    normalize_sync_playlist_path,
    sync_playlist_file_id,
)
from iopenpod.sync.sync_playlist_planner import build_sync_playlist_changes


def test_discover_sync_playlist_files_imports_outside_references_and_counts_skips(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "Music"
    outside_root = tmp_path / "Elsewhere"
    media_root.mkdir()
    outside_root.mkdir()
    inside = media_root / "inside.mp3"
    outside = outside_root / "outside.mp3"
    missing = media_root / "missing.mp3"
    playlist = media_root / "mix.m3u8"
    inside.write_bytes(b"inside")
    outside.write_bytes(b"outside")
    playlist.write_text(
        f"inside.mp3\n{outside}\n{missing.name}\n",
        encoding="utf-8",
    )

    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(media_root))],
        include_video=True,
    )

    assert len(discovery.playlists) == 1
    parsed = discovery.playlists[0]
    assert parsed.title == "Mix"
    assert parsed.playlist_id == sync_playlist_file_id(playlist)
    assert is_managed_sync_playlist_id(parsed.playlist_id)
    assert parsed.total_entries == 3
    assert parsed.skipped_entries == 1
    assert [item["source_path"] for item in parsed.items] == [
        normalize_sync_playlist_path(inside),
        normalize_sync_playlist_path(outside),
    ]
    assert discovery.media_paths == (
        normalize_sync_playlist_path(inside),
        normalize_sync_playlist_path(outside),
    )


def test_discover_sync_playlist_files_requires_playlist_media_type(tmp_path: Path) -> None:
    track = tmp_path / "song.mp3"
    playlist = tmp_path / "mix.m3u8"
    track.write_bytes(b"audio")
    playlist.write_text("song.mp3\n", encoding="utf-8")

    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path), media_types=("music",))],
        include_video=True,
    )

    assert discovery.playlists == ()
    assert discovery.media_paths == ()


def test_build_sync_playlist_changes_adds_new_managed_playlist(tmp_path: Path) -> None:
    track = tmp_path / "song.mp3"
    playlist = tmp_path / "mix.m3u8"
    track.write_bytes(b"audio")
    playlist.write_text("song.mp3\nmissing.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths={normalize_sync_playlist_path(track)},
        valid_source_paths={normalize_sync_playlist_path(track)},
    )

    assert len(adds) == 1
    assert edits == []
    assert removals == []
    assert adds[0]["Title"] == "Mix"
    assert adds[0]["_source"] == SYNC_PLAYLIST_SOURCE
    assert adds[0]["_sync_playlist_skipped_count"] == 1
    assert adds[0]["items"] == [{"source_path": normalize_sync_playlist_path(track)}]


def test_build_sync_playlist_changes_adds_known_ipod_ids_to_new_playlist(
    tmp_path: Path,
) -> None:
    track = tmp_path / "song.mp3"
    playlist = tmp_path / "mix.m3u8"
    track.write_bytes(b"audio")
    playlist.write_text("song.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[],
        ipod_tracks=[],
        source_path_to_db_track_id={normalize_sync_playlist_path(track): 101},
        pending_add_source_paths=set(),
        valid_source_paths={normalize_sync_playlist_path(track)},
    )

    assert len(adds) == 1
    assert edits == []
    assert removals == []
    assert adds[0]["items"] == [
        {"source_path": normalize_sync_playlist_path(track), "db_track_id": 101}
    ]


def test_build_sync_playlist_changes_skips_unchanged_existing_playlist(
    tmp_path: Path,
) -> None:
    track = tmp_path / "song.mp3"
    playlist = tmp_path / "mix.m3u8"
    track.write_bytes(b"audio")
    playlist.write_text("song.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )
    playlist_id = sync_playlist_file_id(playlist)

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[
            {
                "Title": "Mix",
                "playlist_id": playlist_id,
                "items": [{"db_track_id": 101}],
            }
        ],
        ipod_tracks=[],
        source_path_to_db_track_id={normalize_sync_playlist_path(track): 101},
        pending_add_source_paths=set(),
        valid_source_paths={normalize_sync_playlist_path(track)},
    )

    assert adds == []
    assert edits == []
    assert removals == []


def test_build_sync_playlist_changes_edits_changed_existing_playlist(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    playlist = tmp_path / "mix.m3u8"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    playlist.write_text("first.mp3\nsecond.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )
    playlist_id = sync_playlist_file_id(playlist)

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[
            {
                "Title": "Mix",
                "playlist_id": playlist_id,
                "items": [{"db_track_id": 101}],
            }
        ],
        ipod_tracks=[],
        source_path_to_db_track_id={
            normalize_sync_playlist_path(first): 101,
            normalize_sync_playlist_path(second): 202,
        },
        pending_add_source_paths=set(),
        valid_source_paths={
            normalize_sync_playlist_path(first),
            normalize_sync_playlist_path(second),
        },
    )

    assert adds == []
    assert len(edits) == 1
    assert removals == []
    assert edits[0]["_isNew"] is False
    assert edits[0]["items"] == [
        {"source_path": normalize_sync_playlist_path(first), "db_track_id": 101},
        {"source_path": normalize_sync_playlist_path(second), "db_track_id": 202},
    ]


def test_build_sync_playlist_changes_edits_playlist_when_source_removes_track(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    playlist = tmp_path / "mix.m3u8"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    playlist.write_text("first.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )
    playlist_id = sync_playlist_file_id(playlist)

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[
            {
                "Title": "Mix",
                "playlist_id": playlist_id,
                "items": [{"db_track_id": 101}, {"db_track_id": 202}],
            }
        ],
        ipod_tracks=[],
        source_path_to_db_track_id={
            normalize_sync_playlist_path(first): 101,
            normalize_sync_playlist_path(second): 202,
        },
        pending_add_source_paths=set(),
        valid_source_paths={
            normalize_sync_playlist_path(first),
            normalize_sync_playlist_path(second),
        },
    )

    assert adds == []
    assert len(edits) == 1
    assert removals == []
    assert edits[0]["items"] == [
        {"source_path": normalize_sync_playlist_path(first), "db_track_id": 101}
    ]


def test_build_sync_playlist_changes_aliases_duplicate_sources_to_representative(
    tmp_path: Path,
) -> None:
    representative = tmp_path / "chosen.mp3"
    duplicate = tmp_path / "duplicate.mp3"
    playlist = tmp_path / "mix.m3u8"
    representative.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    playlist.write_text("duplicate.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths={normalize_sync_playlist_path(representative)},
        valid_source_paths={normalize_sync_playlist_path(representative)},
        source_path_aliases={
            normalize_sync_playlist_path(duplicate): normalize_sync_playlist_path(representative)
        },
    )

    assert len(adds) == 1
    assert edits == []
    assert removals == []
    assert adds[0]["items"] == [{"source_path": normalize_sync_playlist_path(representative)}]


def test_build_sync_playlist_changes_aliases_duplicate_source_to_representative_db_id(
    tmp_path: Path,
) -> None:
    representative = tmp_path / "chosen.mp3"
    duplicate = tmp_path / "duplicate.mp3"
    playlist = tmp_path / "mix.m3u8"
    representative.write_bytes(b"same")
    duplicate.write_bytes(b"same")
    playlist.write_text("duplicate.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[],
        ipod_tracks=[],
        source_path_to_db_track_id={normalize_sync_playlist_path(representative): 101},
        pending_add_source_paths=set(),
        valid_source_paths={normalize_sync_playlist_path(representative)},
        source_path_aliases={
            normalize_sync_playlist_path(duplicate): normalize_sync_playlist_path(representative)
        },
    )

    assert len(adds) == 1
    assert edits == []
    assert removals == []
    assert adds[0]["items"] == [
        {"source_path": normalize_sync_playlist_path(representative), "db_track_id": 101}
    ]


def test_build_sync_playlist_changes_skips_unresolved_playlist_tracks(
    tmp_path: Path,
) -> None:
    unresolved = tmp_path / "unresolved.mp3"
    playlist = tmp_path / "mix.m3u8"
    unresolved.write_bytes(b"audio")
    playlist.write_text("unresolved.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths=set(),
        valid_source_paths={normalize_sync_playlist_path(unresolved)},
    )

    assert len(adds) == 1
    assert edits == []
    assert removals == []
    assert adds[0]["items"] == []
    assert adds[0]["_sync_playlist_skipped_count"] == 1


def test_build_sync_playlist_changes_removes_deleted_managed_playlist(
    tmp_path: Path,
) -> None:
    deleted_playlist = tmp_path / "gone.m3u8"
    managed_id = sync_playlist_file_id(deleted_playlist)

    adds, edits, removals = build_sync_playlist_changes(
        discover_sync_playlist_files([MediaFolderEntry(str(tmp_path))], include_video=True),
        existing_playlists=[
            {"Title": "Gone", "playlist_id": managed_id, "items": []},
            {"Title": "Manual", "playlist_id": 123, "items": []},
        ],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths=set(),
        valid_source_paths=set(),
    )

    assert adds == []
    assert edits == []
    assert [playlist["playlist_id"] for playlist in removals] == [managed_id]
    assert removals[0]["_source"] == SYNC_PLAYLIST_SOURCE


def test_build_sync_playlist_changes_filters_selected_playlist_adds_without_removing_existing(
    tmp_path: Path,
) -> None:
    first_track = tmp_path / "first.mp3"
    second_track = tmp_path / "second.mp3"
    first_playlist = tmp_path / "first.m3u8"
    second_playlist = tmp_path / "second.m3u8"
    first_track.write_bytes(b"first")
    second_track.write_bytes(b"second")
    first_playlist.write_text("first.mp3\n", encoding="utf-8")
    second_playlist.write_text("second.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )
    second_id = sync_playlist_file_id(second_playlist)

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[
            {"Title": "Second", "playlist_id": second_id, "items": []},
        ],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths={normalize_sync_playlist_path(first_track)},
        valid_source_paths={normalize_sync_playlist_path(first_track)},
        selected_playlist_source_paths={normalize_sync_playlist_path(first_playlist)},
    )

    assert [playlist["playlist_id"] for playlist in adds] == [
        sync_playlist_file_id(first_playlist)
    ]
    assert edits == []
    assert removals == []


def test_build_sync_playlist_changes_does_not_remove_malformed_source_playlist(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "broken.xspf"
    malformed.write_text("<playlist>", encoding="utf-8")
    managed_id = sync_playlist_file_id(malformed)

    adds, edits, removals = build_sync_playlist_changes(
        discover_sync_playlist_files([MediaFolderEntry(str(tmp_path))], include_video=True),
        existing_playlists=[
            {"Title": "Broken", "playlist_id": managed_id, "items": []},
        ],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths=set(),
        valid_source_paths=set(),
    )

    assert adds == []
    assert edits == []
    assert removals == []


def test_playlist_builder_resolves_synced_playlist_source_paths(tmp_path: Path) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:Song.mp3",
        db_track_id=101,
        source_path=normalize_sync_playlist_path(source),
    )

    _master_name, _master_id, playlists, *_rest = build_and_evaluate_playlists(
        existing_tracks_data=[],
        dataset2_standard_playlists_raw=[
            {
                "Title": "Mix",
                "playlist_id": sync_playlist_file_id(tmp_path / "mix.m3u8"),
                "_source": SYNC_PLAYLIST_SOURCE,
                "items": [{"source_path": normalize_sync_playlist_path(source)}],
            }
        ],
        dataset3_podcast_playlists_raw=[],
        dataset5_smart_playlists_raw=[],
        all_track_infos=[track],
        source_path_to_db_track_id={normalize_sync_playlist_path(source): 101},
    )

    assert len(playlists) == 1
    assert playlists[0].track_ids == [101]


def test_playlist_builder_uses_trackinfo_source_path_for_playlist_items(
    tmp_path: Path,
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:Song.mp3",
        db_track_id=101,
        source_path=normalize_sync_playlist_path(source),
    )

    _master_name, _master_id, playlists, *_rest = build_and_evaluate_playlists(
        existing_tracks_data=[],
        dataset2_standard_playlists_raw=[
            {
                "Title": "Mix",
                "playlist_id": sync_playlist_file_id(tmp_path / "mix.m3u8"),
                "_source": SYNC_PLAYLIST_SOURCE,
                "items": [{"source_path": normalize_sync_playlist_path(source)}],
            }
        ],
        dataset3_podcast_playlists_raw=[],
        dataset5_smart_playlists_raw=[],
        all_track_infos=[track],
    )

    assert len(playlists) == 1
    assert playlists[0].track_ids == [101]


def test_playlist_builder_prefers_sync_playlist_direct_db_track_ids(
    tmp_path: Path,
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:Song.mp3",
        db_track_id=101,
        source_path="/missing/old/library/song.mp3",
    )

    _master_name, _master_id, playlists, *_rest = build_and_evaluate_playlists(
        existing_tracks_data=[],
        dataset2_standard_playlists_raw=[
            {
                "Title": "Mix",
                "playlist_id": sync_playlist_file_id(tmp_path / "mix.m3u8"),
                "_source": SYNC_PLAYLIST_SOURCE,
                "items": [
                    {
                        "source_path": normalize_sync_playlist_path(source),
                        "db_track_id": 101,
                    }
                ],
            }
        ],
        dataset3_podcast_playlists_raw=[],
        dataset5_smart_playlists_raw=[],
        all_track_infos=[track],
        source_path_to_db_track_id={},
    )

    assert len(playlists) == 1
    assert playlists[0].track_ids == [101]


def test_pending_add_playlist_item_resolves_after_commit_assigns_db_track_id(
    tmp_path: Path,
) -> None:
    source = tmp_path / "new.mp3"
    playlist = tmp_path / "mix.m3u8"
    source.write_bytes(b"audio")
    playlist.write_text("new.mp3\n", encoding="utf-8")
    discovery = discover_sync_playlist_files(
        [MediaFolderEntry(str(tmp_path))],
        include_video=True,
    )

    adds, edits, removals = build_sync_playlist_changes(
        discovery,
        existing_playlists=[],
        ipod_tracks=[],
        source_path_to_db_track_id={},
        pending_add_source_paths={normalize_sync_playlist_path(source)},
        valid_source_paths={normalize_sync_playlist_path(source)},
    )
    assert edits == []
    assert removals == []
    assert adds[0]["items"] == [{"source_path": normalize_sync_playlist_path(source)}]

    copied_track = TrackInfo(
        title="New",
        location=":iPod_Control:Music:F00:New.mp3",
        db_track_id=909,
        source_path=normalize_sync_playlist_path(source),
    )
    _master_name, _master_id, playlists, *_rest = build_and_evaluate_playlists(
        existing_tracks_data=[],
        dataset2_standard_playlists_raw=list(adds),
        dataset3_podcast_playlists_raw=[],
        dataset5_smart_playlists_raw=[],
        all_track_infos=[copied_track],
        source_path_to_db_track_id={normalize_sync_playlist_path(source): 909},
    )

    assert len(playlists) == 1
    assert playlists[0].track_ids == [909]


def test_full_sync_playlist_ipod_file_reference_uses_existing_fingerprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_track_path = ipod_root / "iPod_Control" / "Music" / "F00" / "SONG.m4a"
    ipod_track_path.parent.mkdir(parents=True)
    ipod_track_path.write_bytes(b"audio")

    playlist_root = tmp_path / "Music"
    playlist_root.mkdir()
    playlist_path = playlist_root / "mix.m3u8"
    playlist_path.write_text(str(ipod_track_path), encoding="utf-8")

    class PlaylistOnlyLibrary:
        root_path = playlist_root
        root_entries = (
            MediaFolderEntry(
                str(playlist_root),
                recurse=False,
                media_types=("playlists",),
            ),
        )

        def scan(self, **_kwargs):
            return []

        def _read_track(self, file_path: Path, library_root: Path | None = None):
            assert Path(file_path) == ipod_track_path
            stat = ipod_track_path.stat()
            return PCTrack(
                path=str(ipod_track_path),
                relative_path=ipod_track_path.name,
                filename=ipod_track_path.name,
                extension=ipod_track_path.suffix.lower(),
                mtime=stat.st_mtime,
                size=stat.st_size,
                title="Song",
                artist="Artist",
                album="Album",
                album_artist=None,
                genre=None,
                year=None,
                track_number=None,
                track_total=None,
                disc_number=None,
                disc_total=None,
                duration_ms=123_000,
                bitrate=256,
                sample_rate=44_100,
                rating=None,
            )

    class Mapping:
        def all_db_track_ids(self):
            return {888}

        def all_fingerprints(self):
            return {"old-fingerprint"}

        def aggregate_entries(self):
            return []

        def get_entries(self, fingerprint: str):
            if fingerprint == "old-fingerprint":
                return [SimpleNamespace(db_track_id=888)]
            return []

    class MappingManager:
        def exists(self):
            return True

        def load(self):
            return Mapping()

        def save(self, _mapping):
            return True

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.is_fpcalc_available",
        lambda _fpcalc_path="": True,
    )
    monkeypatch.setattr(
        "iopenpod.sync.integrity.check_integrity",
        lambda *_args, **_kwargs: SimpleNamespace(
            is_clean=True,
            stale_mappings=[],
            missing_files=[],
            summary="clean",
        ),
    )

    def fingerprint_playlist_reference(path, *, fpcalc_path="", write_to_file=True):
        assert Path(path) == ipod_track_path
        assert write_to_file is False
        return "matching-fingerprint", "computed"

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.get_or_compute_fingerprint_with_status",
        fingerprint_playlist_reference,
    )

    engine = FingerprintDiffEngine(
        cast(Any, PlaylistOnlyLibrary()),
        ipod_root,
        supports_photo=False,
    )
    cast(Any, engine).mapping_manager = MappingManager()

    plan = engine.compute_diff(
        [
            {
                "db_track_id": 888,
                "Location": ":iPod_Control:Music:F00:SONG.m4a",
                "Title": "Song",
                "Artist": "Artist",
                "Album": "Album",
                "length": 123_000,
                "size": ipod_track_path.stat().st_size,
            }
        ],
        write_fingerprints=True,
        sync_workers=1,
        existing_playlists=[],
    )

    assert plan.to_add == []
    assert plan.to_remove == []
    assert plan.playlists_to_add[0]["items"] == [
        {
            "source_path": normalize_sync_playlist_path(ipod_track_path),
            "db_track_id": 888,
        }
    ]


def test_full_sync_playlist_external_reference_uses_existing_ipod_fingerprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ipod_root = tmp_path / "ipod"
    ipod_track_path = ipod_root / "iPod_Control" / "Music" / "F00" / "SONG.m4a"
    ipod_track_path.parent.mkdir(parents=True)
    ipod_track_path.write_bytes(b"ipod audio")

    playlist_root = tmp_path / "Music"
    source_root = tmp_path / "External"
    playlist_root.mkdir()
    source_root.mkdir()
    source_path = source_root / "Song.m4a"
    source_path.write_bytes(b"source audio")
    playlist_path = playlist_root / "mix.m3u8"
    playlist_path.write_text(str(source_path), encoding="utf-8")

    class PlaylistOnlyLibrary:
        root_path = playlist_root
        root_entries = (
            MediaFolderEntry(
                str(playlist_root),
                recurse=False,
                media_types=("playlists",),
            ),
        )

        def scan(self, **_kwargs):
            return []

        def _read_track(self, file_path: Path, library_root: Path | None = None):
            assert Path(file_path) == source_path
            stat = source_path.stat()
            return PCTrack(
                path=str(source_path),
                relative_path=source_path.name,
                filename=source_path.name,
                extension=source_path.suffix.lower(),
                mtime=stat.st_mtime,
                size=stat.st_size,
                title="Song",
                artist="Artist",
                album="Album",
                album_artist=None,
                genre=None,
                year=None,
                track_number=None,
                track_total=None,
                disc_number=None,
                disc_total=None,
                duration_ms=123_000,
                bitrate=256,
                sample_rate=44_100,
                rating=None,
            )

    class Mapping:
        def all_db_track_ids(self):
            return {888}

        def all_fingerprints(self):
            return {"old-fingerprint"}

        def aggregate_entries(self):
            return []

        def get_entries(self, fingerprint: str):
            if fingerprint == "old-fingerprint":
                return [SimpleNamespace(db_track_id=888)]
            return []

    class MappingManager:
        def exists(self):
            return True

        def load(self):
            return Mapping()

        def save(self, _mapping):
            return True

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.is_fpcalc_available",
        lambda _fpcalc_path="": True,
    )
    monkeypatch.setattr(
        "iopenpod.sync.integrity.check_integrity",
        lambda *_args, **_kwargs: SimpleNamespace(
            is_clean=True,
            stale_mappings=[],
            missing_files=[],
            summary="clean",
        ),
    )

    def fingerprint_playlist_reference(path, *, fpcalc_path="", write_to_file=True):
        assert Path(path) in {source_path, ipod_track_path}
        if Path(path) == ipod_track_path:
            assert write_to_file is False
        return "matching-fingerprint", "computed"

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.get_or_compute_fingerprint_with_status",
        fingerprint_playlist_reference,
    )

    engine = FingerprintDiffEngine(
        cast(Any, PlaylistOnlyLibrary()),
        ipod_root,
        supports_photo=False,
    )
    cast(Any, engine).mapping_manager = MappingManager()

    plan = engine.compute_diff(
        [
            {
                "db_track_id": 888,
                "Location": ":iPod_Control:Music:F00:SONG.m4a",
                "Title": "Song",
                "Artist": "Artist",
                "Album": "Album",
                "length": 123_000,
                "size": ipod_track_path.stat().st_size,
            }
        ],
        write_fingerprints=True,
        sync_workers=1,
        existing_playlists=[],
    )

    assert plan.to_add == []
    assert plan.to_remove == []
    assert plan.playlists_to_add[0]["items"] == [
        {
            "source_path": normalize_sync_playlist_path(source_path),
            "db_track_id": 888,
        }
    ]
