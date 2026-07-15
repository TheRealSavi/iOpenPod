from __future__ import annotations

from iopenpod.sync.album_chapters import (
    _build_ffmpeg_concat_command,
    _build_ffmpeg_split_command,
    build_chapter_lyrics,
    build_chapter_split_segments,
    build_chapter_timeline,
    resolve_album_tracks,
)
from iopenpod.sync.fingerprint_diff_engine import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.pc_library import PCLibrary
from iopenpod.sync.review_selection import build_filtered_sync_plan
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext
from iopenpod.sync.transcoder import TranscodeOptions, TranscodeTarget


def _track(
    title: str,
    *,
    album: str = "Album",
    artist: str = "Artist",
    album_artist: str = "Artist",
    album_id: int = 10,
    disc: int = 1,
    number: int = 1,
    length: int = 60_000,
    db_track_id: int = 1,
    media_type: int = 1,
) -> dict:
    return {
        "Title": title,
        "Album": album,
        "Artist": artist,
        "Album Artist": album_artist,
        "album_id": album_id,
        "disc_number": disc,
        "track_number": number,
        "length": length,
        "db_track_id": db_track_id,
        "media_type": media_type,
    }


def test_resolve_album_tracks_by_album_id_and_sort_order() -> None:
    tracks = [
        _track("Second", disc=1, number=2, db_track_id=2),
        _track("Other", album_id=99, db_track_id=99),
        _track("Disc Two", disc=2, number=1, db_track_id=3),
        _track("First", disc=1, number=1, db_track_id=1),
        _track("Video", db_track_id=4, media_type=0x02),
    ]

    resolved = resolve_album_tracks(
        {"filter_key": "album_id", "filter_value": 10, "category": "Albums"},
        tracks,
    )

    assert [track["Title"] for track in resolved] == ["First", "Second", "Disc Two"]


def test_resolve_album_tracks_falls_back_to_album_and_artist() -> None:
    tracks = [
        _track("Match", album="Shared", artist="One", album_artist="One"),
        _track("Different Artist", album="Shared", artist="Two", album_artist="Two"),
    ]

    resolved = resolve_album_tracks(
        {
            "album": "Shared",
            "artist": "One",
            "category": "Albums",
            "filter_key": "Album",
            "filter_value": "Shared",
        },
        tracks,
    )

    assert [track["Title"] for track in resolved] == ["Match"]


def test_chapter_timeline_and_lyrics_preserve_disc_track_order() -> None:
    tracks = [
        _track("Opening", disc=1, number=1, length=65_000),
        _track("Finale", disc=2, number=1, length=125_000),
    ]

    chapters = build_chapter_timeline(tracks)
    lyrics = build_chapter_lyrics(chapters)

    assert chapters == [
        {"startpos": 0, "endpos": 65_000, "title": "Disc 1, Track 1: Opening"},
        {"startpos": 65_000, "endpos": 190_000, "title": "Disc 2, Track 1: Finale"},
    ]
    assert lyrics.splitlines() == [
        "[00:00] Disc 1, Track 1: Opening",
        "[01:05] Disc 2, Track 1: Finale",
    ]


def test_chaptered_album_ffmpeg_command_can_target_mp3(tmp_path) -> None:
    metadata_path = tmp_path / "chapters.ffmetadata"
    output_path = tmp_path / "Album.mp3"

    cmd = _build_ffmpeg_concat_command(
        ffmpeg="ffmpeg",
        sources=[tmp_path / "one.flac", tmp_path / "two.flac"],
        metadata_path=metadata_path,
        output_path=output_path,
        options=TranscodeOptions(lossy_encoder="libmp3lame"),
        target=TranscodeTarget.MP3,
        encoder="libmp3lame",
    )

    assert cmd[cmd.index("-c:a") + 1] == "libmp3lame"
    assert "-id3v2_version" in cmd
    assert "-map_chapters" in cmd
    assert "-movflags" not in cmd


def test_chapter_split_segments_use_chapter_titles_and_track_length() -> None:
    track = _track("Chaptered Album", length=180_000)
    track["chapter_data"] = {
        "chapters": [
            {"startpos": 60_000, "title": "Middle"},
            {"startpos": 0, "title": "Opening"},
            {"startpos": 120_000, "title": ""},
        ]
    }

    segments = build_chapter_split_segments(track)

    assert [(s.index, s.title, s.start_ms, s.end_ms) for s in segments] == [
        (1, "Opening", 0, 60_000),
        (2, "Middle", 60_000, 120_000),
        (3, "Chapter 3", 120_000, 180_000),
    ]


def test_chapter_split_ffmpeg_command_strips_source_chapters(tmp_path) -> None:
    cmd = _build_ffmpeg_split_command(
        ffmpeg="ffmpeg",
        source=tmp_path / "album.m4a",
        output_path=tmp_path / "chapter.mp3",
        segment=build_chapter_split_segments({
            "length": 120_000,
            "chapter_data": {
                "chapters": [
                    {"startpos": 0, "title": "One"},
                    {"startpos": 60_000, "title": "Two"},
                ]
            },
        })[0],
        options=TranscodeOptions(lossy_encoder="libmp3lame"),
        target=TranscodeTarget.MP3,
        encoder="libmp3lame",
    )

    assert cmd[cmd.index("-ss") + 1] == "0.000"
    assert cmd[cmd.index("-t") + 1] == "60.000"
    assert cmd[cmd.index("-map_chapters") + 1] == "-1"
    assert cmd[cmd.index("-c:a") + 1] == "libmp3lame"


def test_filtered_plan_drops_deferred_removals_when_conversion_add_unchecked() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        conversion_group_id="album-1",
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        conversion_group_id="album-1",
        defer_removal_until_after_add=True,
        ipod_track={"size": 123},
    )
    ordinary_remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"size": 456},
    )
    original = SyncPlan(to_add=[add], to_remove=[remove, ordinary_remove])

    filtered = build_filtered_sync_plan(original, [remove, ordinary_remove])

    assert filtered.to_add == []
    assert filtered.to_remove == [ordinary_remove]
    assert filtered.storage.bytes_to_remove == 456


def test_filtered_plan_keeps_deferred_removals_when_conversion_add_checked() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        conversion_group_id="album-1",
        estimated_size=1000,
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        conversion_group_id="album-1",
        defer_removal_until_after_add=True,
        ipod_track={"size": 123},
    )
    original = SyncPlan(to_add=[add], to_remove=[remove])

    filtered = build_filtered_sync_plan(original, [add, remove])

    assert filtered.to_add == [add]
    assert filtered.to_remove == [remove]
    assert filtered.storage.bytes_to_add == 1000
    assert filtered.storage.bytes_to_remove == 123


def test_filtered_plan_drops_deferred_removal_until_all_split_adds_checked() -> None:
    first = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        conversion_group_id="split-1",
        conversion_group_add_count=2,
        estimated_size=100,
    )
    second = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        conversion_group_id="split-1",
        conversion_group_add_count=2,
        estimated_size=200,
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        conversion_group_id="split-1",
        defer_removal_until_after_add=True,
        ipod_track={"size": 123},
    )
    original = SyncPlan(to_add=[first, second], to_remove=[remove])

    partial = build_filtered_sync_plan(original, [first, remove])
    complete = build_filtered_sync_plan(original, [first, second, remove])

    assert partial.to_remove == []
    assert complete.to_remove == [remove]


def test_executor_defers_replacement_removals_until_add_group_completes(tmp_path) -> None:
    immediate = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=1,
        ipod_track={"Location": ":iPod_Control:Music:F00:ONE.m4a"},
    )
    deferred = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=2,
        ipod_track={"Location": ":iPod_Control:Music:F00:TWO.m4a"},
        conversion_group_id="album-1",
        defer_removal_until_after_add=True,
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_remove=[immediate, deferred]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    executor = SyncExecutor(tmp_path)

    executor._execute_removes(ctx)

    assert ctx.result.tracks_removed == 1

    executor._execute_deferred_replacement_removes(ctx)

    assert ctx.result.tracks_removed == 1

    ctx.completed_conversion_groups.add("album-1")
    executor._execute_deferred_replacement_removes(ctx)

    assert ctx.result.tracks_removed == 2


def test_executor_waits_for_all_split_adds_before_deferred_remove(tmp_path) -> None:
    first = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        conversion_group_id="split-1",
        conversion_group_add_count=2,
    )
    second = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        conversion_group_id="split-1",
        conversion_group_add_count=2,
    )
    deferred = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=2,
        ipod_track={"Location": ":iPod_Control:Music:F00/TWO.m4a"},
        conversion_group_id="split-1",
        defer_removal_until_after_add=True,
    )
    ctx = _SyncContext(
        plan=SyncPlan(to_add=[first, second], to_remove=[deferred]),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    executor = SyncExecutor(tmp_path)
    executor._prepare_conversion_group_counts(ctx)

    executor._record_conversion_group_add_success(ctx, first)
    executor._execute_deferred_replacement_removes(ctx)

    assert ctx.result.tracks_removed == 0

    executor._record_conversion_group_add_success(ctx, second)
    executor._execute_deferred_replacement_removes(ctx)

    assert ctx.result.tracks_removed == 1


def test_pc_library_extracts_chapters_for_music_m4a(monkeypatch, tmp_path) -> None:
    path = tmp_path / "song.m4a"
    path.write_bytes(b"not a real m4a")
    chapters = [{"startpos": 0, "title": "Intro"}]

    monkeypatch.setattr(
        PCLibrary,
        "_extract_metadata",
        lambda self, audio, ext, file_path=None: {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration_ms": 1000,
        },
    )
    monkeypatch.setattr(PCLibrary, "_compute_art_hash", lambda self, file_path: None)
    monkeypatch.setattr(
        "iopenpod.podcasts.downloader.extract_chapters",
        lambda file_path: chapters,
    )

    track = PCLibrary(str(tmp_path))._read_track(path)

    assert track is not None
    assert track.is_podcast is False
    assert track.is_audiobook is False
    assert track.chapters == chapters


def test_pc_library_extracts_chapters_for_supported_non_aac_audio(monkeypatch, tmp_path) -> None:
    path = tmp_path / "song.flac"
    path.write_bytes(b"not a real flac")
    chapters = [{"startpos": 0, "title": "Intro"}]

    monkeypatch.setattr(
        PCLibrary,
        "_extract_metadata",
        lambda self, audio, ext, file_path=None: {
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "duration_ms": 1000,
        },
    )
    monkeypatch.setattr(PCLibrary, "_compute_art_hash", lambda self, file_path: None)
    monkeypatch.setattr(
        "iopenpod.podcasts.downloader.extract_chapters",
        lambda file_path: chapters,
    )

    track = PCLibrary(str(tmp_path))._read_track(path)

    assert track is not None
    assert track.chapters == chapters
