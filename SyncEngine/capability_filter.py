"""Shared helpers for filtering media against device playback capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._formats import VIDEO_EXTENSIONS


def is_video_path(path: str | Path) -> bool:
    """Return whether *path* names a supported video container."""

    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_video_track(track: Any) -> bool:
    """Return whether a scanned PC track requires video support."""

    if bool(getattr(track, "is_video", False)):
        return True
    extension = str(getattr(track, "extension", "") or "").lower()
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    return extension in VIDEO_EXTENSIONS


def is_podcast_track(track: Any) -> bool:
    """Return whether a scanned PC track requires podcast DB support."""

    return bool(getattr(track, "is_podcast", False))


def is_track_supported_by_device(
    track: Any,
    *,
    supports_video: bool = True,
    supports_podcast: bool = True,
) -> bool:
    """Return whether *track* can be added to a device with these flags."""

    if not supports_video and is_video_track(track):
        return False
    if not supports_podcast and is_podcast_track(track):
        return False
    return True


def unsupported_track_reason(
    track: Any,
    *,
    supports_video: bool = True,
    supports_podcast: bool = True,
) -> str:
    """Return a short reason string for an unsupported track, or ``""``."""

    if not supports_video and is_video_track(track):
        return "video is not supported by this iPod"
    if not supports_podcast and is_podcast_track(track):
        return "podcasts are not supported by this iPod"
    return ""
