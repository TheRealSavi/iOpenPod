"""Read final MP4 stream descriptors without altering or decoding the video."""

from __future__ import annotations

import json
from typing import Any, cast

from iPodDB.library import SubtitleSelection, VideoPlaybackMetadata

# Only the MOV/MP4 demuxer, with external references disabled by its defaults.
# No packet/frame enumeration: these are bounded container-header observations.
VIDEO_METADATA_ARGUMENTS = (
    "-v",
    "error",
    "-hide_banner",
    "-max_alloc",
    "67108864",
    "-protocol_whitelist",
    "file",
    "-format_whitelist",
    "mov",
    "-probesize",
    "16777216",
    "-analyzeduration",
    "10000000",
    "-show_entries",
    "stream=index,id,codec_type,codec_name,codec_tag_string:"
    "stream_disposition=default,attached_pic:stream_tags=language",
    "-of",
    "json",
    "-i",
)


def parse_video_metadata(data: bytes) -> VideoPlaybackMetadata:
    """Select the default supported text track, otherwise the first in file order."""
    try:
        document = json.loads(data)
        raw_streams = document["streams"]
        if not isinstance(raw_streams, list):
            raise ValueError("The final video has an invalid stream inventory.")
        entries = cast("list[object]", raw_streams)
        if not 1 <= len(entries) <= 1024 or not all(
            isinstance(s, dict) for s in entries
        ):
            raise ValueError("The final video has an invalid stream inventory.")
        streams = cast("list[dict[str, Any]]", entries)
        if not any(
            s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic", 0)
            for s in streams
        ):
            raise ValueError("The final file has no timed video stream.")
        subtitles = sorted(
            (
                s
                for s in streams
                if s.get("codec_name") == "mov_text"
                and s.get("codec_tag_string") == "tx3g"
            ),
            key=lambda s: (
                not s.get("disposition", {}).get("default", 0),
                int(s["index"]),
            ),
        )
        selection = _selection(subtitles[0]) if subtitles else None
        captions = any(s.get("codec_tag_string") == "c608" for s in streams)
        return VideoPlaybackMetadata(selection, captions)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError(f"Cannot inspect video playback metadata: {error}") from error


def _selection(stream: dict[str, Any]) -> SubtitleSelection:
    raw_id = stream["id"]
    identity = int(raw_id, 0) if isinstance(raw_id, str) else int(raw_id)
    language = str(stream.get("tags", {}).get("language", "und")).lower()
    # An absent/invalid tag is undefined, never implicitly English.
    if len(language) != 3 or not all("a" <= char <= "z" for char in language):
        language = "und"
    packed = sum(
        (ord(char) - 96) << shift
        for char, shift in zip(language, (10, 5, 0), strict=True)
    )
    return SubtitleSelection(identity, int(stream["index"]), packed)
