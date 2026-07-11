from pathlib import Path

from iopenpod.application.dropped_files import (
    build_dropped_playlist_imports,
    collect_import_file_paths,
    collect_media_file_paths,
    is_media_drop_candidate,
)


def test_collect_media_file_paths_expands_supported_files(tmp_path: Path) -> None:
    media_dir = tmp_path / "album"
    media_dir.mkdir()
    track = media_dir / "song.mp3"
    audiobook = media_dir / "book.aax"
    nested = media_dir / "nested"
    nested.mkdir()
    video = nested / "clip.m4v"
    ignored = media_dir / "notes.txt"
    standalone = tmp_path / "single.flac"
    for path in (track, audiobook, video, ignored, standalone):
        path.write_text("x", encoding="utf-8")

    assert is_media_drop_candidate(media_dir) is True
    assert is_media_drop_candidate(standalone) is True
    assert is_media_drop_candidate(ignored) is False

    assert collect_media_file_paths([media_dir, standalone, ignored]) == [
        audiobook,
        track,
        video,
        standalone,
    ]


def test_collect_media_file_paths_can_exclude_videos(tmp_path: Path) -> None:
    media_dir = tmp_path / "album"
    media_dir.mkdir()
    track = media_dir / "song.mp3"
    video = media_dir / "clip.m4v"
    for path in (track, video):
        path.write_text("x", encoding="utf-8")

    assert is_media_drop_candidate(video, include_video=False) is False
    assert collect_media_file_paths([media_dir], include_video=False) == [track]


def test_drop_candidate_accepts_supported_extension_before_file_exists(
    tmp_path: Path,
) -> None:
    pending_audio = tmp_path / "song.m4a"
    pending_playlist = tmp_path / "mix.m3u8"
    pending_note = tmp_path / "notes.txt"

    assert is_media_drop_candidate(pending_audio) is True
    assert is_media_drop_candidate(pending_playlist) is True
    assert is_media_drop_candidate(pending_note) is False


def test_collect_import_file_paths_groups_supported_imports(tmp_path: Path) -> None:
    media_dir = tmp_path / "drop"
    nested = media_dir / "album"
    nested.mkdir(parents=True)
    track = media_dir / "song.mp3"
    photo = nested / "cover.jpg"
    playlist = media_dir / "mix.m3u8"
    ignored = media_dir / "notes.txt"
    for path in (track, photo, playlist, ignored):
        path.write_text("x", encoding="utf-8")

    assert is_media_drop_candidate(photo) is True
    assert is_media_drop_candidate(playlist) is True
    assert is_media_drop_candidate(ignored) is False

    grouped = collect_import_file_paths([media_dir])

    assert grouped.track_paths == (track,)
    assert grouped.photo_imports == ((str(photo), "album"),)
    assert grouped.playlist_paths == (playlist,)


def test_collect_import_file_paths_respects_photo_flag(tmp_path: Path) -> None:
    media_dir = tmp_path / "drop"
    media_dir.mkdir()
    track = media_dir / "song.mp3"
    photo = media_dir / "cover.jpg"
    for path in (track, photo):
        path.write_text("x", encoding="utf-8")

    grouped = collect_import_file_paths([media_dir], include_photo=False)

    assert grouped.track_paths == (track,)
    assert grouped.photo_imports == ()


def test_build_dropped_playlist_imports_uses_supported_media_paths(
    tmp_path: Path,
) -> None:
    track = tmp_path / "song.mp3"
    photo = tmp_path / "cover.jpg"
    playlist = tmp_path / "mix.m3u8"
    track.write_text("audio", encoding="utf-8")
    photo.write_text("image", encoding="utf-8")
    playlist.write_text("song.mp3\ncover.jpg\nmissing.mp3\n", encoding="utf-8")

    media_paths, playlists = build_dropped_playlist_imports([playlist])

    assert media_paths == [track]
    assert len(playlists) == 1
    assert playlists[0]["Title"] == "Mix"
    assert playlists[0]["_isNew"] is True
    assert playlists[0]["_source"] == "regular"
    assert playlists[0]["items"] == [{"source_path": str(track)}]
