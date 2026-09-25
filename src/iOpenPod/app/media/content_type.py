"""Explicit file metadata establishes content roles without guessing from genres."""

from __future__ import annotations

from typing import TYPE_CHECKING

from iPodDB.library import MediaType

if TYPE_CHECKING:
    from collections.abc import Mapping


def classify_content_type(
    suffix: str, tags: Mapping[str, str], *, video: bool
) -> MediaType:
    """Original iOpenPod's stik/pcst evidence plus the dedicated M4B container."""
    kind = (
        tags.get("stik")
        or tags.get("media_type")
        or tags.get("media type")
        or tags.get("media_kind")
        or ""
    )
    kind = kind.strip().casefold().replace("_", " ")
    podcast = tags.get("pcst") or tags.get("podcast") or ""
    if kind in ("21", "podcast") or podcast.casefold() in ("1", "true", "yes"):
        return MediaType.VIDEO_PODCAST if video else MediaType.PODCAST
    if not video and (
        kind in ("2", "audiobook", "audio book") or suffix.casefold() == ".m4b"
    ):
        return MediaType.AUDIOBOOK
    if video:
        if kind in ("6", "music video"):
            return MediaType.MUSIC_VIDEO
        if kind in ("10", "tv show"):
            return MediaType.TV_SHOW
        return MediaType.VIDEO
    return MediaType.AUDIO
