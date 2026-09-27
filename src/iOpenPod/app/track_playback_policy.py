"""Application playback requirements for Podcasts and timed video media.

Apply to incoming or desired Library state only. Retained database projections
remain truthful, and iPodDB keeps its lossless unchanged-document contract.
"""

from dataclasses import replace

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
