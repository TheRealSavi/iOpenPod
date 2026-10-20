"""Caller-observed playback characteristics of a final video file."""

from dataclasses import dataclass

from iPodDB.library.models import MediaType, Track


def is_video_track(track: Track) -> bool:
    return bool(
        set(track.media_types)
        & {
            MediaType.VIDEO,
            MediaType.AUDIO_VIDEO,
            MediaType.VIDEO_PODCAST,
            MediaType.TV_SHOW,
            MediaType.MUSIC_VIDEO,
        }
    )


@dataclass(frozen=True, slots=True)
class SubtitleSelection:
    """A native MP4 track ID, zero-based stream index, and packed ISO language."""

    track_id: int
    track_index: int
    language: int

    def __post_init__(self) -> None:
        if not 0 < self.track_id <= 0xFFFFFFFF or not 0 <= self.track_index <= 0xFFFF:
            raise ValueError("Subtitle track identity or index is out of range")
        if not 0 < self.language < 0x8000 or any(
            not 1 <= (self.language >> shift) & 31 <= 26 for shift in (10, 5, 0)
        ):
            raise ValueError("Subtitle language must be a packed ISO 639-2 code")


@dataclass(frozen=True, slots=True)
class VideoPlaybackMetadata:
    """Presence flags and the initial soft-subtitle selection, independent of UI."""

    subtitle: SubtitleSelection | None = None
    has_closed_captions: bool = False
