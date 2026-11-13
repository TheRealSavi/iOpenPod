"""Host tag comparison and lossless, compatible retained Track provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from iOpenPod.app.track_conversion import media_type_choices
from iPodDB.library import MediaType, metadata_edit_issues

if TYPE_CHECKING:
    from iPodDB.library import Track, WriteIssue


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
    "podcast_guid",
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
    """Compare Host-owned tags; EQ is edited only in the iPod Library."""
    return (
        *(getattr(track, name) for name in TRACK_TAG_FIELDS),
        *(
            getattr(track.metadata, name)
            for name in METADATA_TAG_FIELDS
            if name != "equalizer"
        ),
    )


def apply_track_tags(target: Track, source: Track) -> Track:
    """Apply Host tags while retaining identity, media facts and playback state."""
    # Scanned chapters are not removal intent. Keep their existing comparison and
    # digest representation, but only captured media preparation or explicit
    # Library edits may replace the retained Track's chapter evidence.
    # EQ has no Host tag mapping or clear intent; only explicit Library edits
    # author its value, including choosing Use iPod setting.
    return replace(
        target,
        **{name: getattr(source, name) for name in TRACK_TAG_FIELDS},
        metadata=replace(
            target.metadata,
            **{
                name: getattr(source.metadata, name)
                for name in METADATA_TAG_FIELDS
                if name not in ("chapters", "equalizer")
            },
        ),
    )


def track_tag_edit_issues(before: Track, after: Track) -> tuple[WriteIssue, ...]:
    """Validate Sync tags and compatible retained-media classification together."""
    classification = after.media_types
    if (
        type(classification) is tuple
        and len(classification) == 1
        and type(classification[0]) is MediaType
        and classification[0] in media_type_choices(before)
    ):
        # Classification belongs to the Application Layer (ADR-0088), not the
        # ordinary metadata editor. Approve only a compatible classification;
        # validate every other changed field against the actual retained Track.
        before = replace(before, media_types=classification)
    return metadata_edit_issues(before, after)


def track_tag_sha256(track: Track) -> str:
    """Fingerprint the semantic iPod Track fields recorded at verified Sync."""

    # Keep the persisted v1 digest byte-for-byte compatible, including retained
    # EQ. This fingerprints committed iPod state, unlike the Host-owned comparison
    # above. Removing a field here would invalidate existing Sync baselines.
    values = (
        *(getattr(track, name) for name in TRACK_TAG_FIELDS),
        *(getattr(track.metadata, name) for name in METADATA_TAG_FIELDS),
    )
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


__all__ = [
    "apply_track_tags",
    "track_tag_edit_issues",
    "track_tag_sha256",
    "track_tag_values",
]
