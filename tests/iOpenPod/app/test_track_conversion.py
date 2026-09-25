from dataclasses import replace

from iOpenPod.app.track_conversion import (
    convert_track_to_podcast,
    podcast_conversion_needed,
)
from iPodDB.library import MediaType, Track, TrackMetadata


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
