from types import SimpleNamespace

from app_core.jobs import (
    SyncToolAvailability,
    check_sync_tool_availability,
    collect_media_file_paths,
    is_media_drop_candidate,
)


def test_sync_tool_availability_summarizes_missing_tools() -> None:
    availability = SyncToolAvailability(
        missing_ffmpeg=True,
        missing_fpcalc=True,
        can_download=False,
    )

    assert availability.has_missing is True
    assert availability.can_continue_without_download is False
    assert availability.tool_names == ("fpcalc (Chromaprint)", "FFmpeg")
    assert availability.tool_list == "fpcalc (Chromaprint) and FFmpeg"
    assert "Settings -> External Tools" in availability.install_help_text


def test_sync_tool_availability_allows_missing_ffmpeg_only() -> None:
    availability = SyncToolAvailability(
        missing_ffmpeg=True,
        missing_fpcalc=False,
        can_download=True,
    )

    assert availability.has_missing is True
    assert availability.can_continue_without_download is True
    assert availability.tool_names == ("FFmpeg",)


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

    settings = SimpleNamespace(ffmpeg_path="missing-ffmpeg", fpcalc_path="fpcalc-ok")

    availability = check_sync_tool_availability(settings)

    assert availability.missing_ffmpeg is True
    assert availability.missing_fpcalc is False
    assert availability.can_download is False
    assert seen == {"ffmpeg": "missing-ffmpeg", "fpcalc": "fpcalc-ok"}


def test_collect_media_file_paths_expands_supported_files(tmp_path) -> None:
    media_dir = tmp_path / "album"
    media_dir.mkdir()
    track = media_dir / "song.mp3"
    nested = media_dir / "nested"
    nested.mkdir()
    video = nested / "clip.m4v"
    ignored = media_dir / "notes.txt"
    standalone = tmp_path / "single.flac"
    for path in (track, video, ignored, standalone):
        path.write_text("x", encoding="utf-8")

    assert is_media_drop_candidate(media_dir) is True
    assert is_media_drop_candidate(standalone) is True
    assert is_media_drop_candidate(ignored) is False

    assert collect_media_file_paths([media_dir, standalone, ignored]) == [
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
