from types import SimpleNamespace

from app_core.jobs import (
    SyncExecuteWorker,
    SyncToolAvailability,
    build_dropped_playlist_imports,
    check_sync_tool_availability,
    collect_import_file_paths,
    collect_media_file_paths,
    is_media_drop_candidate,
)
from infrastructure.settings_schema import AppSettings


def test_sync_tool_availability_summarizes_missing_tools() -> None:
    availability = SyncToolAvailability(
        missing_ffmpeg=True,
        missing_fpcalc=True,
        can_download=False,
    )

    assert availability.has_missing is True
    assert availability.can_continue_without_download is False
    assert availability.tool_names == ("fpcalc (Chromaprint)", "FFmpeg/ffprobe")
    assert availability.tool_list == "fpcalc (Chromaprint) and FFmpeg/ffprobe"
    assert "ffprobe" in availability.install_help_text
    assert "Settings -> External Tools" in availability.install_help_text


def test_sync_tool_availability_blocks_missing_ffmpeg_only() -> None:
    availability = SyncToolAvailability(
        missing_ffmpeg=True,
        missing_fpcalc=False,
        can_download=True,
    )

    assert availability.has_missing is True
    assert availability.can_continue_without_download is False
    assert availability.tool_names == ("FFmpeg/ffprobe",)


def test_check_sync_tool_availability_uses_configured_paths(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_ffmpeg_available(path: str) -> bool:
        seen["ffmpeg"] = path
        return path == "ffmpeg-ok"

    def fake_fpcalc_available(path: str) -> bool:
        seen["fpcalc"] = path
        return path == "fpcalc-ok"

    monkeypatch.setattr(
        "SyncEngine.transcoder.is_ffmpeg_available",
        fake_ffmpeg_available,
    )
    monkeypatch.setattr(
        "SyncEngine.audio_fingerprint.is_fpcalc_available",
        fake_fpcalc_available,
    )
    monkeypatch.setattr(
        "SyncEngine.dependency_manager.is_platform_supported",
        lambda: False,
    )

    settings = AppSettings()
    settings.ffmpeg_path = "missing-ffmpeg"
    settings.fpcalc_path = "fpcalc-ok"

    availability = check_sync_tool_availability(settings)

    assert availability.missing_ffmpeg is True
    assert availability.missing_fpcalc is False
    assert availability.can_download is False
    assert seen == {"ffmpeg": "missing-ffmpeg", "fpcalc": "fpcalc-ok"}


def test_sync_execute_worker_blocks_missing_required_tools(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "app_core.jobs.check_sync_tool_availability",
        lambda _settings: SyncToolAvailability(
            missing_ffmpeg=True,
            missing_fpcalc=False,
            can_download=False,
        ),
    )

    worker = SyncExecuteWorker(
        str(tmp_path),
        SimpleNamespace(),
        settings=AppSettings(),
    )
    errors: list[str] = []
    worker.error.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "FFmpeg/ffprobe required before sync" in errors[0]


def test_collect_media_file_paths_expands_supported_files(tmp_path) -> None:
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


def test_collect_media_file_paths_can_exclude_videos(tmp_path) -> None:
    media_dir = tmp_path / "album"
    media_dir.mkdir()
    track = media_dir / "song.mp3"
    video = media_dir / "clip.m4v"
    for path in (track, video):
        path.write_text("x", encoding="utf-8")

    assert is_media_drop_candidate(video, include_video=False) is False
    assert collect_media_file_paths([media_dir], include_video=False) == [track]


def test_drop_candidate_accepts_supported_extension_before_file_exists(tmp_path) -> None:
    pending_audio = tmp_path / "song.m4a"
    pending_playlist = tmp_path / "mix.m3u8"
    pending_note = tmp_path / "notes.txt"

    assert is_media_drop_candidate(pending_audio) is True
    assert is_media_drop_candidate(pending_playlist) is True
    assert is_media_drop_candidate(pending_note) is False


def test_collect_import_file_paths_groups_supported_imports(tmp_path) -> None:
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


def test_collect_import_file_paths_respects_photo_flag(tmp_path) -> None:
    media_dir = tmp_path / "drop"
    media_dir.mkdir()
    track = media_dir / "song.mp3"
    photo = media_dir / "cover.jpg"
    for path in (track, photo):
        path.write_text("x", encoding="utf-8")

    grouped = collect_import_file_paths([media_dir], include_photo=False)

    assert grouped.track_paths == (track,)
    assert grouped.photo_imports == ()


def test_build_dropped_playlist_imports_uses_supported_media_paths(tmp_path) -> None:
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
    assert playlists[0]["items"] == [{"source_path": str(track)}]
