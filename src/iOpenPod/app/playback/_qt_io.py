"""Shared Qt I/O bridge for playback and its runtime check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QIODevice, QObject, Signal

if TYPE_CHECKING:
    from iOpenPod.app.playback.backend import PlaybackSource


class QtPlaybackIODevice(QIODevice):
    """Expose range-readable Track bytes as a seekable Qt device."""

    sourceFailed = Signal(object)

    def __init__(
        self,
        source: PlaybackSource,
        parent: QObject | None = None,
    ) -> None:
        if parent is None:
            super().__init__()
        else:
            super().__init__(parent)
        self._source = source

    def isSequential(self) -> bool:
        return False

    def size(self) -> int:
        return self._source.byte_count

    def readData(self, max_length: int) -> bytes:
        remaining = self.size() - self.pos()
        if max_length <= 0 or remaining <= 0:
            return b""
        try:
            return self._source.read_at(
                self.pos(),
                min(max_length, remaining),
            )
        except Exception as error:
            self.setErrorString(str(error))
            self.sourceFailed.emit(error)
            return b""

    def writeData(
        self,
        _data: bytes | bytearray | memoryview[int],
        _length: int,
    ) -> int:
        return -1
