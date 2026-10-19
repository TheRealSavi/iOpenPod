"""Application playback requirements for Podcasts and timed video media.

Apply to incoming or desired Library state only. Retained database projections
remain truthful, and iPodDB keeps its lossless unchanged-document contract.
"""

from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime

from iOpenPod.app.podcasts.identity import track_podcast_identity
from iPodDB.library import LibrarySnapshot, MediaType, Track

_REQUIRED_TYPES = frozenset(
    (
        MediaType.PODCAST,
        MediaType.VIDEO_PODCAST,
        MediaType.VIDEO,
        MediaType.AUDIO_VIDEO,
        MediaType.TV_SHOW,
        MediaType.MUSIC_VIDEO,
    )
)


def requires_track_playback_policy(track: Track) -> bool:
    """Whether this Track must resume playback and stay out of Shuffle."""
    return track.metadata.podcast or any(
        kind in _REQUIRED_TYPES for kind in track.media_types
    )


def enforce_track_playback_policy(track: Track) -> Track:
    """Set required playback and Podcast display flags for desired Tracks."""
    podcast = track.metadata.podcast or any(
        kind in (MediaType.PODCAST, MediaType.VIDEO_PODCAST)
        for kind in track.media_types
    )
    if podcast:
        original = track
        metadata = track.metadata
        year = track.year
        if not year and metadata.release_date:
            with suppress(OverflowError, OSError, ValueError):
                year = datetime.fromtimestamp(metadata.release_date, UTC).year
        types = track.media_types
        if not any(
            kind in types
            for kind in (
                MediaType.VIDEO_PODCAST,
                MediaType.VIDEO,
                MediaType.AUDIO_VIDEO,
            )
        ):
            types = (MediaType.PODCAST,)
        track = replace(
            track,
            media_types=types,
            year=year,
            metadata=replace(
                metadata,
                podcast_guid=track_podcast_identity(track).guid,
                last_modified=metadata.last_modified
                or int(datetime.now(UTC).timestamp()),
                subtitle=metadata.subtitle or metadata.description[:255],
            ),
        )
        if track == original:
            track = original
    if not requires_track_playback_policy(track) or (
        track.metadata.skip_shuffle
        and track.metadata.remember_position
        and track.metadata.podcast == podcast
    ):
        return track
    return replace(
        track,
        metadata=replace(
            track.metadata, skip_shuffle=True, remember_position=True, podcast=podcast
        ),
    )


def enforce_library_playback_policy(snapshot: LibrarySnapshot) -> LibrarySnapshot:
    """Repair desired playback settings before application review/publication."""
    tracks = tuple(enforce_track_playback_policy(track) for track in snapshot.tracks)
    return snapshot if tracks == snapshot.tracks else replace(snapshot, tracks=tracks)


__all__ = [
    "enforce_library_playback_policy",
    "enforce_track_playback_policy",
    "requires_track_playback_policy",
]
