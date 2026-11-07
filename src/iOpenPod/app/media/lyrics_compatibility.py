"""Verify known Classic lyrics constraints on a Storage-owned prepared stream.

The caller selects the applicable device policy. This checks the traced Classic
120GB RetailOS 2.0.1 storage/decoder path, not physical rendering or every model.
It neither changes source text nor converts tag versions. See the firmware lyrics
research for 0x08166074, 0x0812A700, 0x080586BC and 0x0827B04C.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text

if TYPE_CHECKING:
    from typing import BinaryIO, Literal

_LYRICS_LIMIT = 0x2800
_HEADER_LIMIT = 10_000
_MP4_AUDIO = frozenset((".m4a", ".m4b", ".m4p"))


def _incompatible(reason: str) -> ValueError:
    return ValueError(
        source_text(
            "Lyrics cannot be verified for this iPod's native player: {reason} "
            "The full lyrics and source file were not truncated.",
            reason=reason,
        )
    )


class _Reader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        stream.seek(0, io.SEEK_END)
        self.size = stream.tell()
        self.headers = 0

    def read(self, offset: int, size: int, end: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > end or end > self.size:
            raise _incompatible(
                source_text("a metadata field extends beyond its container.")
            )
        self.stream.seek(offset)
        value = self.stream.read(size)
        if len(value) != size:
            raise _incompatible(
                source_text("the metadata could not be read completely.")
            )
        return value

    def header(self, offset: int, size: int, end: int) -> bytes:
        self.headers += 1
        if self.headers > _HEADER_LIMIT:
            raise _incompatible(
                source_text("the bounded metadata verification limit was exceeded.")
            )
        return self.read(offset, size, end)


@dataclass(frozen=True, slots=True)
class _Atom:
    kind: bytes
    start: int
    payload: int
    end: int
    ordinary_header: bool


def _atoms(reader: _Reader, start: int, end: int) -> tuple[_Atom, ...]:
    result: list[_Atom] = []
    while start < end:
        header = reader.header(start, 8, end)
        size = int.from_bytes(header[:4], "big")
        ordinary_header = size not in (0, 1)
        payload = start + 8
        if size == 1:
            size = int.from_bytes(reader.read(payload, 8, end), "big")
            payload += 8
        elif size == 0:
            size = end - start
        if size < payload - start or size > end - start:
            raise _incompatible(
                source_text("an MP4 metadata atom has an invalid size.")
            )
        result.append(_Atom(header[4:], start, payload, start + size, ordinary_header))
        start += size
    return tuple(result)


def _one(atoms: tuple[_Atom, ...], kind: bytes) -> _Atom:
    found = tuple(atom for atom in atoms if atom.kind == kind)
    if len(found) != 1:
        raise _incompatible(
            source_text("the MP4 lyrics path must contain one unambiguous item.")
        )
    return found[0]


def _mp4_text(reader: _Reader) -> str:
    atoms = _atoms(reader, 0, reader.size)
    for kind in (b"moov", b"udta", b"meta", b"ilst", b"\xa9lyr"):
        item = _one(atoms, kind)
        if not item.ordinary_header:
            raise _incompatible(
                source_text("this MP4 lyrics path uses an unverified atom header.")
            )
        start = item.payload
        if kind == b"meta":
            if reader.read(start, 4, item.end) != bytes(4):
                raise _incompatible(
                    source_text("this MP4 metadata version is not verified.")
                )
            start += 4
        atoms = _atoms(reader, start, item.end)
    # The native reader subtracts fixed eight-byte atom headers here.
    if item.payload != item.start + 8 or len(atoms) != 1:
        raise _incompatible(
            source_text("native MP4 lyrics require one data child filling ©lyr.")
        )
    child = atoms[0]
    if child.kind != b"data" or not child.ordinary_header:
        raise _incompatible(
            source_text("native MP4 lyrics require an ordinary data atom header.")
        )
    if child.end - child.payload < 8:
        raise _incompatible(source_text("the MP4 lyrics data header is incomplete."))
    size = child.end - child.payload - 8
    if size > _LYRICS_LIMIT:
        raise _incompatible(
            source_text("MP4 lyrics exceed the native 10,240-byte text limit.")
        )
    text = reader.read(child.payload + 8, size, child.end)
    if b"\x00" in text:
        raise _incompatible(
            source_text("MP4 lyrics contain an ambiguous NUL terminator.")
        )
    return _utf8(text)


def _synchsafe(data: bytes) -> int:
    if any(value & 0x80 for value in data):
        raise _incompatible(source_text("the ID3 synchsafe size is malformed."))
    result = 0
    for value in data:
        result = (result << 7) | value
    return result


def _id3_location(reader: _Reader, suffix: str) -> tuple[int, int]:
    if suffix == ".mp3":
        return 0, reader.size
    header = reader.read(0, 12, reader.size)
    order: Literal["little", "big"]
    if suffix in (".wav", ".wave"):
        valid = header[:4] == b"RIFF" and header[8:] == b"WAVE"
        order = "little"
    elif suffix in (".aif", ".aiff", ".aifc"):
        valid = header[:4] == b"FORM" and header[8:] in (b"AIFF", b"AIFC")
        order = "big"
    else:
        raise _incompatible(
            source_text("this media filename has no verified lyrics decoder path.")
        )
    if not valid:
        raise _incompatible(
            source_text("the media container does not match its filename.")
        )
    end = int.from_bytes(header[4:8], order) + 8
    if end > reader.size or end < 12:
        raise _incompatible(
            source_text("the chunked media container has an invalid size.")
        )
    offset = 12
    while offset < end:
        chunk = reader.header(offset, 8, end)
        size = int.from_bytes(chunk[4:], order)
        start = offset + 8
        if size > end - start:
            raise _incompatible(
                source_text("an ID3-containing media chunk is truncated.")
            )
        if chunk[:4].upper() == b"ID3 ":
            return start, start + size
        offset = start + size + size % 2
    raise _incompatible(source_text("the media file has no embedded ID3 lyrics tag."))


def _id3_text(reader: _Reader, suffix: str) -> str:
    offset, end = _id3_location(reader, suffix)
    header = reader.read(offset, 10, end)
    if header[:3] != b"ID3" or header[3] not in (2, 3, 4):
        raise _incompatible(
            source_text("lyrics verification requires an ID3v2.2, v2.3 or v2.4 tag.")
        )
    version = header[3]
    if header[5]:
        raise _incompatible(
            source_text(
                "ID3 tag flags, extended headers or unsynchronization need explicit conversion first."
            )
        )
    tag_end = offset + 10 + _synchsafe(header[6:])
    if tag_end > end:
        raise _incompatible(
            source_text("the ID3 tag extends beyond its media container.")
        )
    offset += 10
    # 0x080E37C0 reads the v2.2 identifier and unsigned body size as three
    # bytes each. Its ULT body uses the same native text decoder as USLT.
    identifier_size, header_size = (3, 6) if version == 2 else (4, 10)
    lyrics_identifier = b"ULT" if version == 2 else b"USLT"
    while offset + header_size <= tag_end:
        frame = reader.header(offset, header_size, tag_end)
        identifier = frame[:identifier_size]
        if identifier == bytes(identifier_size):
            break
        if any(
            value not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for value in identifier
        ):
            raise _incompatible(source_text("an ID3 frame identifier is malformed."))
        size = int.from_bytes(frame[identifier_size : identifier_size * 2], "big")
        if version == 4 and size != _synchsafe(frame[4:8]):
            raise _incompatible(
                source_text(
                    "an ID3v2.4 frame size is misread by the native lyrics reader; "
                    "convert the tag to ID3v2.3 before writing lyrics."
                )
            )
        if size > tag_end - offset - header_size:
            raise _incompatible(source_text("an ID3 frame extends beyond its tag."))
        if identifier == lyrics_identifier:
            # Earlier frames are skipped by size. Only the selected body must
            # be decoded; status flags do not change its representation.
            if version != 2 and frame[9]:
                raise _incompatible(
                    source_text(
                        "compressed, encrypted or transformed ID3 frames cannot be verified."
                    )
                )
            if size > _LYRICS_LIMIT:
                raise _incompatible(
                    source_text(
                        "the ID3 lyrics body exceeds 10,240 bytes including its encoding, language and description."
                    )
                )
            return _decode_id3(reader.read(offset + header_size, size, tag_end))
        offset += header_size + size
    raise _incompatible(source_text("no unsynchronized lyrics frame was found."))


def _utf8(data: bytes, *, strip_bom: bool = False) -> str:
    # Native strings stop at NUL; standards-compliant Unicode is an authoring
    # requirement, not a claim that the firmware's checker is equally strict.
    try:
        return data.split(b"\x00", 1)[0].decode("utf-8-sig" if strip_bom else "utf-8")
    except UnicodeError as error:
        raise _incompatible(
            source_text("lyrics do not contain complete UTF-8 text.")
        ) from error


def _decode_id3(body: bytes) -> str:
    if len(body) < 5:
        raise _incompatible(source_text("the ID3 lyrics body is incomplete."))
    encoding = body[0]
    if encoding in (0, 3):
        end = body.find(b"\x00", 4)
        if end < 0:
            raise _incompatible(
                source_text("the ID3 lyrics description has no terminator.")
            )
        text = body[end + 1 :]
        return (
            text.split(b"\x00", 1)[0].decode("latin-1")
            if encoding == 0
            else _utf8(text, strip_bom=True)
        )
    if encoding != 1:
        raise _incompatible(
            source_text(
                "the native lyrics decoder cannot read this ID3 text encoding; use UTF-16 with BOM or UTF-8."
            )
        )
    offset = 4
    while offset + 2 <= len(body) and body[offset : offset + 2] != b"\x00\x00":
        offset += 2
    if offset + 2 > len(body):
        raise _incompatible(
            source_text("the UTF-16 lyrics description has no terminator.")
        )
    text = body[offset + 2 :]
    order = "utf-16-le"
    if text[:2] in (b"\xff\xfe", b"\xfe\xff"):
        if text[:2] == b"\xfe\xff":
            order = "utf-16-be"
        text = text[2:]
    if len(text) % 2:
        raise _incompatible(
            source_text("UTF-16 lyrics end with an incomplete code unit.")
        )
    terminator = next(
        (i for i in range(0, len(text), 2) if text[i : i + 2] == b"\x00\x00"), None
    )
    if terminator is None:
        raise _incompatible(
            source_text("UTF-16 lyrics need a terminator within the native read limit.")
        )
    try:
        return text[:terminator].decode(order)
    except UnicodeError as error:
        raise _incompatible(
            source_text("UTF-16 lyrics contain an incomplete character.")
        ) from error


def verify_native_lyrics(stream: BinaryIO, file_name: str, expected: str) -> None:
    """Check known native representation constraints without changing any bytes.

    Empty text permits removal. Nonempty text must survive the bounded decoder
    path exactly. Preserve the caller's stream position even when verification
    fails. Matching does not establish renderer, media-kind or physical support.
    """
    if not expected:
        return
    if "\x00" in expected:
        raise _incompatible(
            source_text("embedded NUL characters terminate native lyrics early.")
        )
    position = stream.tell()
    try:
        reader = _Reader(stream)
        suffix = PurePosixPath(file_name).suffix.casefold()
        if suffix in (".mp4", ".m4v", ".mov"):
            raise _incompatible(
                source_text(
                    "this filename does not select the native MP4 audio lyrics decoder."
                )
            )
        actual = (
            _mp4_text(reader) if suffix in _MP4_AUDIO else _id3_text(reader, suffix)
        )
        if actual != expected:
            raise _incompatible(
                source_text(
                    "the native decoder would not reproduce the complete requested text."
                )
            )
    finally:
        stream.seek(position)
