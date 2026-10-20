"""Explicit source stream intent shared by Sync review and media preparation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text
from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.models import MediaStream, StreamKind
from iOpenPod.app.media.subtitles import supports

if TYPE_CHECKING:
    from device_registry import DeviceProfile
    from iOpenPod.app.media.models import MediaInspection, MediaScanMetadata


class SubtitleHandling(StrEnum):
    COPY = "copy"
    CONVERT = "convert"
    UNSUPPORTED = "unsupported"


def is_caption(stream: MediaStream) -> bool:
    return stream.codec in {"eia_608", "cea_708"} or stream.codec_tag in {
        "c608",
        "c708",
    }


def subtitle_handling(stream: MediaStream, profile: DeviceProfile) -> SubtitleHandling:
    """Keep capability and text-conversion policy out of the GUI."""
    caps = profile.capabilities.video
    if stream.kind is not StreamKind.SUBTITLE or not caps.supported:
        return SubtitleHandling.UNSUPPORTED
    if is_caption(stream):
        return (
            SubtitleHandling.COPY
            if caps.supports_cea608_captions
            and stream.codec == "eia_608"
            and stream.codec_tag == "c608"
            else SubtitleHandling.UNSUPPORTED
        )
    if not caps.supports_tx3g_subtitles:
        return SubtitleHandling.UNSUPPORTED
    if (
        stream.codec == "mov_text"
        and stream.codec_tag == "tx3g"
        and stream.width is not None
        and stream.width > 0
        and stream.height is not None
        and stream.height > 0
    ):
        return SubtitleHandling.COPY
    if supports(stream.codec):
        return SubtitleHandling.CONVERT
    return SubtitleHandling.UNSUPPORTED


@dataclass(frozen=True, slots=True)
class MediaStreamSelection:
    """Selected streams include observed facts, so indices cannot silently drift."""

    video: MediaStream | None
    audio: MediaStream | None
    subtitles: tuple[MediaStream, ...] = ()
    captions: tuple[MediaStream, ...] = ()

    def __post_init__(self) -> None:
        if self.video is None and self.audio is None:
            raise ValueError(source_text("Select at least one playable stream"))
        if self.video is not None and (
            self.video.kind is not StreamKind.VIDEO
            or self.video.attached_picture is not False
        ):
            raise ValueError("Select a motion-video stream")
        if self.audio is not None and self.audio.kind is not StreamKind.AUDIO:
            raise ValueError("Select an audio stream")
        if self.video is None and (self.subtitles or self.captions):
            raise ValueError("Subtitles and captions require video")
        for streams, captions in ((self.subtitles, False), (self.captions, True)):
            if any(
                stream.kind is not StreamKind.SUBTITLE
                or is_caption(stream) is not captions
                for stream in streams
            ):
                raise ValueError("Select the correct subtitle or caption stream kind")
        indices = [stream.index for stream in self.streams]
        if len(indices) != len(set(indices)):
            raise ValueError("A stream may only be selected once")

    @property
    def streams(self) -> tuple[MediaStream, ...]:
        return (
            *((self.video,) if self.video is not None else ()),
            *((self.audio,) if self.audio is not None else ()),
            *self.subtitles,
            *self.captions,
        )

    def validate(
        self, observed: MediaInspection | MediaScanMetadata, profile: DeviceProfile
    ) -> None:
        actual = {stream.index: stream for stream in observed.streams}
        if any(actual.get(stream.index) != stream for stream in self.streams):
            raise MediaInspectionError(
                "media.stream_selection_changed",
                source_text(
                    "The selected streams changed. Rescan the source and choose its streams again."
                ),
            )
        if bool(observed.video_streams) != (self.video is not None):
            raise MediaInspectionError(
                "media.stream_selection_invalid",
                source_text("Select one video stream for this video."),
            )
        if self.video is not None and not profile.capabilities.video.supported:
            raise MediaInspectionError(
                "media.video_unsupported", source_text("This iPod cannot play video.")
            )
        if any(
            subtitle_handling(stream, profile) is SubtitleHandling.UNSUPPORTED
            for stream in (*self.subtitles, *self.captions)
        ):
            raise MediaInspectionError(
                "media.stream_selection_unsupported",
                source_text(
                    "A selected subtitle or caption cannot be prepared for this iPod. Choose another stream."
                ),
            )


def preferred_stream(streams: tuple[MediaStream, ...]) -> MediaStream | None:
    return next((s for s in streams if s.default), next(iter(streams), None))
