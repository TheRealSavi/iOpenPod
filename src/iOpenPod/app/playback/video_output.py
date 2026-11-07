"""Optional Qt presentation attachment, separate from playback transport policy."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject


@dataclass(frozen=True, slots=True)
class PlaybackSubtitleTrack:
    """One embedded subtitle stream reported by the current decoder."""

    index: int
    title: str = ""
    language: str = ""


class PlaybackVideoOutput(Protocol):
    """Attach a Qt video surface without exposing the decoder or media source."""

    def set_video_output(self, output: QObject | None) -> None:
        """Replace the presentation surface; None detaches it without stopping."""

        ...

    @property
    def subtitle_tracks(self) -> tuple[PlaybackSubtitleTrack, ...]: ...

    @property
    def active_subtitle_track(self) -> int:
        """Return the selected stream index, or -1 when subtitles are off."""

        ...

    def subscribe_subtitles_changed(self, callback: Callable[[], None]) -> None: ...

    def set_subtitle_track(self, index: int) -> None: ...
