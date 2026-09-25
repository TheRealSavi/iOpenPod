"""Read embedded lyrics through bounded, identity-checked media access."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Protocol, cast

import mutagen

from iOpenPod.app.media.lyrics import embedded_lyrics

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.playback.backend import PlaybackSource

_READ_BUDGET = 16 * 1024 * 1024
_READ_CHUNK = 64 * 1024
_OPERATION_BUDGET = 65_536


class _SourceReader:
    """Mutagen's read/seek/tell interface without materializing the media file."""

    def __init__(self, source: PlaybackSource, checkpoint: Callable[[], None]) -> None:
        self.name = source.file_name
        self._source = source
        self._checkpoint = checkpoint
        self._position = 0
        self._remaining = _READ_BUDGET
        self._operations = _OPERATION_BUDGET

    def _check(self) -> None:
        self._checkpoint()
        self._operations -= 1
        if self._operations < 0:
            raise ValueError("Lyrics metadata exceeds the operation limit.")

    def tell(self) -> int:
        self._check()
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._check()
        match whence:
            case io.SEEK_SET:
                position = offset
            case io.SEEK_CUR:
                position = self._position + offset
            case io.SEEK_END:
                position = self._source.byte_count + offset
            case _:
                raise ValueError("Invalid media seek origin.")
        if position < 0:
            raise ValueError("Cannot seek before the media start.")
        self._position = position
        return position

    def read(self, size: int = -1) -> bytes:
        self._check()
        available = max(0, self._source.byte_count - self._position)
        size = available if size < 0 else min(size, available)
        if size > self._remaining:
            raise ValueError("Lyrics metadata exceeds the read limit.")
        result = bytearray()
        while len(result) < size:
            self._check()
            requested = min(size - len(result), _READ_CHUNK)
            data = self._source.read_at(self._position, requested)
            if not data or len(data) > requested:
                raise OSError("The lyrics source changed while reading metadata.")
            result.extend(data)
            self._position += len(data)
            self._remaining -= len(data)
        return bytes(result)


class _MutagenReader(Protocol):
    def File(self, *, fileobj: _SourceReader) -> Any: ...


def read_embedded_lyrics(
    source: PlaybackSource,
    *,
    checkpoint: Callable[[], None],
) -> str:
    """Read native lyric tags without trusting the database presence flag."""

    checkpoint()
    reader = _SourceReader(source, checkpoint)
    try:
        parsed = cast("_MutagenReader", mutagen).File(fileobj=reader)
    except (mutagen.MutagenError, OSError) as error:
        raise ValueError(f"Could not read embedded lyrics: {error}") from error
    checkpoint()
    return embedded_lyrics(parsed)
