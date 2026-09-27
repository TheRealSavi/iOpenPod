from dataclasses import replace

import pytest

from iOpenPod.app.track_conversion import (
    convert_track_to_podcast,
    podcast_conversion_needed,
    reclassify_track,
)
from iPodDB.library import MediaType, Track, TrackMetadata


@pytest.mark.parametrize(
    "before,after",
    [
        (MediaType.VIDEO, MediaType.TV_SHOW),
        (MediaType.TV_SHOW, MediaType.VIDEO),
        (MediaType.VIDEO, MediaType.MUSIC_VIDEO),
        (MediaType.VIDEO, MediaType.VIDEO_PODCAST),
        (MediaType.AUDIO, MediaType.AUDIOBOOK),
        (MediaType.AUDIO, MediaType.PODCAST),
        (MediaType.AUDIOBOOK, MediaType.AUDIO),
    ],
)
def test_reclassification_preserves_unrelated_metadata(
    before: MediaType, after: MediaType
) -> None:
    track = Track(
        1,
        "Title",
        "Artist",
        "Album",
        1000,
        size_bytes=1024,
        media_types=(before,),
        metadata=TrackMetadata(location="iPod_Control/Music/F00/media.mp4"),
    )

    required = after in (
        MediaType.PODCAST,
        MediaType.VIDEO,
        MediaType.TV_SHOW,
        MediaType.MUSIC_VIDEO,
        MediaType.VIDEO_PODCAST,
    )
    assert reclassify_track(track, after) == replace(
        track,
        media_types=(after,),
        metadata=replace(
            track.metadata,
            skip_shuffle=required,
            remember_position=required,
            podcast=after in (MediaType.PODCAST, MediaType.VIDEO_PODCAST),
        ),
    )


@pytest.mark.parametrize(
    "before,after",
    [
        ((MediaType.AUDIO,), MediaType.TV_SHOW),
        ((MediaType.TV_SHOW,), MediaType.AUDIO),
        ((MediaType.EPUB_BOOK,), MediaType.AUDIO),
        ((MediaType.VIDEO, MediaType.PDF_BOOK), MediaType.TV_SHOW),
        ((), MediaType.AUDIO),
    ],
)
def test_reclassification_rejects_unknown_or_incompatible_media(
    before: tuple[MediaType, ...], after: MediaType
) -> None:
    track = Track(1, "Title", "", "", 1000, media_types=before)

    with pytest.raises(ValueError, match="compatible"):
        reclassify_track(track, after)


def test_video_podcast_conversion_preserves_existing_presentation_values() -> None:
    track = Track(
        1,
        "Episode",
        "Host",
        "Show",
        1,
        genre="News",
        play_count=3,
        media_types=(MediaType.VIDEO,),
        show="Series",
        metadata=TrackMetadata(category="Current"),
    )

    converted = convert_track_to_podcast(track)

    assert converted.media_types == (MediaType.VIDEO_PODCAST,)
    assert (converted.album, converted.genre, converted.show) == (
        "Show",
        "News",
        "Series",
    )
    assert converted.metadata.category == "Current"
    assert converted.metadata.played
    assert not podcast_conversion_needed(converted)
    assert convert_track_to_podcast(converted) == converted


def test_podcast_readiness_requires_all_firmware_facing_flags() -> None:
    track = Track(1, "Episode", "", "", 1, media_types=(MediaType.PODCAST,))

    assert podcast_conversion_needed(track)
    assert podcast_conversion_needed(
        replace(
            track,
            metadata=replace(
                track.metadata,
                podcast=True,
                skip_shuffle=True,
                remember_position=False,
            ),
        )
    )


@pytest.mark.parametrize(
    ("before", "after"),
    (
        (MediaType.AUDIO, MediaType.PODCAST),
        (MediaType.VIDEO, MediaType.VIDEO),
        (MediaType.VIDEO, MediaType.TV_SHOW),
        (MediaType.VIDEO, MediaType.MUSIC_VIDEO),
        (MediaType.VIDEO, MediaType.VIDEO_PODCAST),
    ),
)
def test_podcast_and_video_reclassification_enforces_playback_flags(
    before: MediaType,
    after: MediaType,
) -> None:
    track = Track(1, "Episode", "", "", 1_000, media_types=(before,))

    updated = reclassify_track(track, after)

    assert updated.metadata.remember_position
    assert updated.metadata.skip_shuffle
    assert not track.metadata.remember_position
    assert not track.metadata.skip_shuffle
