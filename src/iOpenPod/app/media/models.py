"""Observed facts; missing values never imply device compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fractions import Fraction

    from storage import FileFingerprint, HostPath


class StreamKind(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLE = "subtitle"
    DATA = "data"
    ATTACHMENT = "attachment"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MediaTag:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class MediaStream:
    index: int
    kind: StreamKind
    codec: str
    codec_tag: str
    profile: str
    level: int | None
    duration_seconds: Fraction | None
    start_seconds: Fraction | None
    time_base: Fraction | None
    duration_ticks: int | None
    bitrate_bps: int | None
    sample_rate_hz: int | None
    channels: int | None
    channel_layout: str
    bits_per_sample: int | None
    bits_per_raw_sample: int | None
    width: int | None
    height: int | None
    pixel_format: str
    frame_rate: Fraction | None
    nominal_frame_rate: Fraction | None
    sample_aspect_ratio: Fraction | None
    attached_picture: bool | None
    default: bool | None
    dispositions: tuple[str, ...]
    tags: tuple[MediaTag, ...]


@dataclass(frozen=True, slots=True)
class MediaChapter:
    chapter_id: int
    start_seconds: Fraction
    end_seconds: Fraction
    tags: tuple[MediaTag, ...]


@dataclass(frozen=True, slots=True)
class MediaInspection:
    source: HostPath
    fingerprint: FileFingerprint
    containers: tuple[str, ...]
    duration_seconds: Fraction | None
    start_seconds: Fraction | None
    bitrate_bps: int | None
    tags: tuple[MediaTag, ...]
    streams: tuple[MediaStream, ...]
    chapters: tuple[MediaChapter, ...]

    @property
    def audio_streams(self) -> tuple[MediaStream, ...]:
        return tuple(s for s in self.streams if s.kind is StreamKind.AUDIO)

    @property
    def video_streams(self) -> tuple[MediaStream, ...]:
        """Known motion-video streams; an absent disposition remains unknown."""
        return tuple(
            s
            for s in self.streams
            if s.kind is StreamKind.VIDEO and s.attached_picture is False
        )

    @property
    def pictures(self) -> tuple[MediaStream, ...]:
        return tuple(s for s in self.streams if s.attached_picture is True)
