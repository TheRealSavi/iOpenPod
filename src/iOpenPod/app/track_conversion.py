"""Semantic Track reclassification workflows owned by the Application Layer."""

from dataclasses import replace

from iOpenPod.app.track_playback_policy import enforce_track_playback_policy
from iPodDB.library import MediaType, Track

_VIDEO_TYPES = frozenset(
    (
        MediaType.VIDEO,
        MediaType.AUDIO_VIDEO,
        MediaType.MUSIC_VIDEO,
        MediaType.TV_SHOW,
        MediaType.VIDEO_PODCAST,
    )
)
_AUDIO_CHOICES = (MediaType.AUDIO, MediaType.AUDIOBOOK, MediaType.PODCAST)
_VIDEO_CHOICES = (
    MediaType.VIDEO,
    MediaType.TV_SHOW,
    MediaType.MUSIC_VIDEO,
    MediaType.VIDEO_PODCAST,
)
_AUDIO_TYPES = frozenset(
    (*_AUDIO_CHOICES, MediaType.RINGTONE, MediaType.MEMO, MediaType.ITUNES_U)
)


def media_type_choices(track: Track) -> tuple[MediaType, ...]:
    """Return supported classifications for this Track's retained media family."""
    if any(
        kind in track.media_types for kind in (MediaType.EPUB_BOOK, MediaType.PDF_BOOK)
    ):
        return ()
    if any(kind in _VIDEO_TYPES for kind in track.media_types):
        return _VIDEO_CHOICES
    if any(kind in _AUDIO_TYPES for kind in track.media_types):
        return _AUDIO_CHOICES
    return ()


def reclassify_track(track: Track, media_type: MediaType) -> Track:
    """Change Library classification without changing the retained media or tags."""
    if not isinstance(media_type, MediaType) or media_type not in media_type_choices(  # pyright: ignore[reportUnnecessaryIsInstance]
        track
    ):
        raise ValueError(
            f"Track {track.track_id}: choose a media type compatible with its "
            "retained audio or video."
        )
    return enforce_track_playback_policy(replace(track, media_types=(media_type,)))


def podcast_conversion_needed(track: Track) -> bool:
    """Return whether firmware-facing podcast flags still need to be applied."""

    return not (
        any(
            media_type in (MediaType.PODCAST, MediaType.VIDEO_PODCAST)
            for media_type in track.media_types
        )
        and track.metadata.podcast
        and track.metadata.skip_shuffle
        and track.metadata.remember_position
    )


def convert_track_to_podcast(track: Track) -> Track:
    """Return the semantic values that make an existing Track a Podcast.

    This reclassifies the retained media; it does not transcode or replace its
    bytes. Missing presentation fields follow the Original iOpenPod fallback
    order so the firmware has a stable show and category to group.
    """

    podcast_types = (MediaType.PODCAST, MediaType.VIDEO_PODCAST)
    if any(media_type in podcast_types for media_type in track.media_types):
        media_types = track.media_types
    elif any(media_type in _VIDEO_TYPES for media_type in track.media_types):
        media_types = (MediaType.VIDEO_PODCAST,)
    else:
        media_types = (MediaType.PODCAST,)

    show_title = next(
        (
            value.strip()
            for value in (track.show, track.album, track.artist, track.album_artist)
            if value.strip()
        ),
        "Podcasts",
    )
    metadata = track.metadata
    converted = replace(
        track,
        album=track.album if track.album.strip() else show_title,
        genre=track.genre if track.genre.strip() else "Podcast",
        show=track.show if track.show.strip() else show_title,
        media_types=media_types,
        metadata=replace(
            metadata,
            category=(
                metadata.category
                if metadata.category.strip()
                else track.genre.strip() or "Podcast"
            ),
            podcast=True,
            played=track.play_count > 0,
        ),
    )
    return enforce_track_playback_policy(converted)
