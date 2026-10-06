"""Stable Host-authored Track fields used by Sync comparison and provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iPodDB.library import Track


TRACK_TAG_FIELDS = (
    "title",
    "artist",
    "album",
    "genre",
    "year",
    "track_number",
    "media_types",
    "show",
    "episode",
    "album_artist",
    "season_number",
    "episode_number",
)
METADATA_TAG_FIELDS = (
    "compilation",
    "total_tracks",
    "volume_adjustment_percent",
    "start_time_ms",
    "stop_time_ms",
    "disc_number",
    "total_discs",
    "bpm",
    "release_date",
    "content_advisory",
    "skip_shuffle",
    "remember_position",
    "podcast",
    "gapless_album",
    "equalizer",
    "comment",
    "category",
    "lyrics",
    "composer",
    "grouping",
    "description",
    "podcast_enclosure_url",
    "podcast_rss_url",
    "subtitle",
    "tv_network",
    "sort_artist",
    "track_keywords",
    "show_locale",
    "sort_title",
    "sort_album",
    "sort_album_artist",
    "sort_composer",
    "sort_show",
    "content_provider",
    "copyright",
    "encoding_quality",
    "purchase_account",
    "purchaser_name",
    "chapters",
)


def track_tag_values(track: Track) -> tuple[object, ...]:
    """The single projection for comparing and applying Host-authored fields."""
    return (
        *(getattr(track, name) for name in TRACK_TAG_FIELDS),
        *(getattr(track.metadata, name) for name in METADATA_TAG_FIELDS),
    )


def apply_track_tags(target: Track, source: Track) -> Track:
    """Apply that projection while retaining identity, payload and playback state."""
    return replace(
        target,
        **{name: getattr(source, name) for name in TRACK_TAG_FIELDS},
        metadata=replace(
            target.metadata,
            **{name: getattr(source.metadata, name) for name in METADATA_TAG_FIELDS},
        ),
    )


def track_tag_sha256(track: Track) -> str:
    """Fingerprint the semantic iPod Track fields recorded at verified Sync."""

    values = track_tag_values(track)
    chapters = tuple(
        (chapter.title, chapter.start_ms) for chapter in track.metadata.chapters
    )
    payload = json.dumps(
        (*values[:-1], chapters),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"iopenpod.sync.track-tags.v1\0" + payload).hexdigest()


__all__ = ["apply_track_tags", "track_tag_sha256", "track_tag_values"]
