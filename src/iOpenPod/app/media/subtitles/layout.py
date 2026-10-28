"""Configure converted tx3g tracks using Apple's bottom subtitle rectangle.

Only bounded atom headers are read. Samples and atom sizes remain untouched;
Storage supplies the private, seekable stream and owns its persistence.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.media.inspection import MediaInspectionError

if TYPE_CHECKING:
    from typing import BinaryIO

_VERTICAL_PLACEMENT = 0x20000000
_IDENTITY = (65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824)


@dataclass(frozen=True, slots=True)
class _Atom:
    kind: bytes
    payload: int
    end: int


def _invalid(message: str) -> MediaInspectionError:
    return MediaInspectionError(
        "media.subtitle_layout_invalid",
        f"Cannot configure the iPod subtitle display rectangle: {message}",
    )


def _read(stream: BinaryIO, offset: int, size: int, end: int) -> bytes:
    if offset < 0 or size < 0 or offset + size > end:
        raise _invalid("an MP4 header extends beyond its container.")
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise _invalid("an MP4 header is truncated.")
    return data


def _atoms(stream: BinaryIO, start: int, end: int) -> tuple[_Atom, ...]:
    children: list[_Atom] = []
    offset = start
    while offset < end:
        if len(children) >= 10_000:
            raise _invalid("the MP4 header contains too many atoms.")
        size, kind = struct.unpack(">I4s", _read(stream, offset, 8, end))
        header_size = 8
        if size == 1:
            size = int.from_bytes(_read(stream, offset + 8, 8, end), "big")
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or size > end - offset:
            raise _invalid("an MP4 atom has an invalid size.")
        children.append(_Atom(kind, offset + header_size, offset + size))
        offset += size
    return tuple(children)


def _one(atoms: tuple[_Atom, ...], kind: bytes) -> _Atom:
    matches = tuple(atom for atom in atoms if atom.kind == kind)
    if len(matches) != 1:
        raise _invalid(f"expected one {kind.decode('ascii')} atom.")
    return matches[0]


def _children(stream: BinaryIO, atom: _Atom) -> tuple[_Atom, ...]:
    return _atoms(stream, atom.payload, atom.end)


def _matrix_offset(stream: BinaryIO, header: _Atom) -> int:
    version = _read(stream, header.payload, 1, header.end)[0]
    if version not in (0, 1):
        raise _invalid("the track header version is unsupported.")
    offset = header.payload + (40 if version == 0 else 52)
    _read(stream, offset, 44, header.end)
    return offset


def _patches(
    stream: BinaryIO, output_indices: tuple[int, ...]
) -> tuple[tuple[int, bytes], ...]:
    if len(set(output_indices)) != len(output_indices) or any(
        index < 0 for index in output_indices
    ):
        raise _invalid("the selected subtitle indices are invalid.")
    end = stream.seek(0, io.SEEK_END)
    movie = _one(_atoms(stream, 0, end), b"moov")
    tracks = tuple(atom for atom in _children(stream, movie) if atom.kind == b"trak")
    if any(index >= len(tracks) for index in output_indices):
        raise _invalid("a selected subtitle track is missing.")
    headers: list[_Atom] = []
    media: list[_Atom] = []
    handlers: list[bytes] = []
    for track in tracks:
        children = _children(stream, track)
        headers.append(_one(children, b"tkhd"))
        media.append(_one(children, b"mdia"))
        handler = _one(_children(stream, media[-1]), b"hdlr")
        handlers.append(_read(stream, handler.payload + 8, 4, handler.end))
    videos = tuple(i for i, handler in enumerate(handlers) if handler == b"vide")
    if len(videos) != 1:
        raise _invalid("the prepared movie must contain exactly one video track.")
    video = headers[videos[0]]
    width_fixed, height_fixed = struct.unpack(
        ">II", _read(stream, _matrix_offset(stream, video) + 36, 8, video.end)
    )
    width, height = (width_fixed + 32768) >> 16, (height_fixed + 32768) >> 16
    if not 1 <= width <= 32767 or not 1 <= height <= 32767:
        raise _invalid("the video display dimensions are invalid.")
    subtitle_height = max(1, round(height * 0.15))
    matrix = (*_IDENTITY[:7], (height - subtitle_height) << 16, _IDENTITY[8])
    patches: list[tuple[int, bytes]] = []
    for index in output_indices:
        if handlers[index] not in (b"sbtl", b"text", b"subt"):
            raise _invalid("a selected track is not a subtitle track.")
        track_header = headers[index]
        if _read(stream, track_header.payload, 1, track_header.end)[0] == 1:
            raise MediaInspectionError(
                "media.subtitle_incompatible",
                "The prepared subtitle uses a version-1 track header that the "
                "native subtitle reader misinterprets. Prepare a version-0 "
                "track header before configuring its display rectangle.",
            )
        matrix_offset = _matrix_offset(stream, track_header)
        minf = _one(_children(stream, media[index]), b"minf")
        stbl = _one(_children(stream, minf), b"stbl")
        stsd = _one(_children(stream, stbl), b"stsd")
        description = _read(stream, stsd.payload, 8, stsd.end)
        if description[:4] != bytes(4) or int.from_bytes(description[4:], "big") != 1:
            raise _invalid("the subtitle sample description is unsupported.")
        entries = _atoms(stream, stsd.payload + 8, stsd.end)
        if len(entries) != 1:
            raise _invalid("the subtitle sample count does not match its entries.")
        entry = _one(entries, b"tx3g")
        sample_header = _read(stream, entry.payload, 38, entry.end)
        flags = int.from_bytes(sample_header[8:12], "big") & ~_VERTICAL_PLACEMENT
        patches.extend(
            (
                (matrix_offset, struct.pack(">9i", *matrix)),
                (
                    matrix_offset + 36,
                    struct.pack(">II", width << 16, subtitle_height << 16),
                ),
                (entry.payload + 8, struct.pack(">I", flags)),
                (entry.payload + 18, struct.pack(">4h", 0, 0, subtitle_height, width)),
            )
        )
    return tuple(patches)


def configure_layout(stream: BinaryIO, output_indices: tuple[int, ...]) -> None:
    """Set selected converted tracks' display geometry after validating all headers."""
    if not output_indices:
        return
    patches = _patches(stream, output_indices)
    for offset, data in patches:
        stream.seek(offset)
        if stream.write(data) != len(data):
            raise _invalid("the subtitle header could not be written completely.")
    verify_layout(stream, output_indices)


def verify_layout(stream: BinaryIO, output_indices: tuple[int, ...]) -> None:
    """Require the selected tracks' geometry to match the video presentation."""
    if not output_indices:
        return
    for offset, expected in _patches(stream, output_indices):
        if _read(stream, offset, len(expected), offset + len(expected)) != expected:
            raise MediaInspectionError(
                "media.subtitle_layout_mismatch",
                "The prepared subtitle display rectangle does not match the iPod layout.",
            )
