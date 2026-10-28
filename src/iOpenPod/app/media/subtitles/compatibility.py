"""Validate and exactly normalize native clocks in a Storage-owned stream.

Classic 120GB RetailOS 2.0.1 reads subtitle tkhd using version-0 offsets and
builds subtitle/caption sample times with signed division after mediaTimescale/100.
Verification preserves bytes; normalization changes only exactly rescalable
timing fields. Neither emulates playback nor infers that version-1 mdhd, elst,
or mvhd are generally unsupported.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.media.inspection import MediaInspectionError

if TYPE_CHECKING:
    from typing import BinaryIO

_SIGNED_MAX = (1 << 31) - 1
_ATOM_LIMIT = 10_000
_TIMING_RUN_LIMIT = 100_000


def _invalid(message: str) -> MediaInspectionError:
    return MediaInspectionError(
        "media.subtitle_structure_invalid",
        f"The prepared subtitle or caption headers are malformed: {message}",
    )


def _incompatible(message: str) -> MediaInspectionError:
    return MediaInspectionError(
        "media.subtitle_incompatible",
        f"The prepared subtitle or caption cannot be verified for native playback: "
        f"{message} Choose another stream or prepare compatible media.",
    )


@dataclass(frozen=True, slots=True)
class _Atom:
    kind: bytes
    payload: int
    end: int


@dataclass(frozen=True, slots=True)
class _Clock:
    timescale: int
    duration: int
    offset: int
    duration_size: int


@dataclass(frozen=True, slots=True)
class _Run:
    count: int
    delta: int
    offset: int


@dataclass(frozen=True, slots=True)
class _Track:
    children: tuple[_Atom, ...]
    media: tuple[_Atom, ...]
    tables: tuple[_Atom, ...]


class _Reader:
    """Bound total atom work and individual reads; skip every media payload."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.atom_count = 0
        self.timing_run_count = 0

    def read(self, offset: int, size: int, end: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > end:
            raise _invalid("a header extends beyond its container.")
        self.stream.seek(offset)
        data = self.stream.read(size)
        if len(data) != size:
            raise _invalid("a header is truncated.")
        return data

    def atoms(self, start: int, end: int) -> tuple[_Atom, ...]:
        atoms: list[_Atom] = []
        offset = start
        while offset < end:
            self.atom_count += 1
            if self.atom_count > _ATOM_LIMIT:
                raise _incompatible("the header atom verification limit was exceeded.")
            size, kind = struct.unpack(">I4s", self.read(offset, 8, end))
            header_size = 8
            if size == 1:
                size = int.from_bytes(self.read(offset + 8, 8, end), "big")
                header_size = 16
            elif size == 0:
                size = end - offset
            if size < header_size or size > end - offset:
                raise _invalid("an atom has an invalid size.")
            atoms.append(_Atom(kind, offset + header_size, offset + size))
            offset += size
        return tuple(atoms)

    def children(self, atom: _Atom) -> tuple[_Atom, ...]:
        return self.atoms(atom.payload, atom.end)


def _one(atoms: tuple[_Atom, ...], kind: bytes) -> _Atom:
    matches = tuple(atom for atom in atoms if atom.kind == kind)
    if len(matches) != 1:
        raise _invalid(f"expected one {kind.decode('ascii')} atom.")
    return matches[0]


def _sample_entry(reader: _Reader, table: _Atom, kind: bytes) -> _Atom:
    description = reader.read(table.payload, 8, table.end)
    if description[:4] != bytes(4):
        raise _incompatible("the sample-description version or flags are unsupported.")
    entries = reader.atoms(table.payload + 8, table.end)
    if int.from_bytes(description[4:], "big") != len(entries):
        raise _invalid("the sample-description count differs from its entries.")
    if len(entries) != 1 or entries[0].kind != kind:
        raise _incompatible(f"expected one {kind.decode('ascii')} sample description.")
    return entries[0]


def _subtitle_geometry(reader: _Reader, header: _Atom, entry: _Atom) -> None:
    version = reader.read(header.payload, 1, header.end)[0]
    if version != 0:
        raise _incompatible("the native subtitle reader requires a version-0 tkhd.")
    # Check the complete required header in small reads, preserving unknown data.
    identity = reader.read(header.payload, 40, header.end)
    if int.from_bytes(identity[12:16], "big") == 0:
        raise _invalid("the subtitle track ID is zero.")
    matrix_and_size = reader.read(header.payload + 40, 44, header.end)
    width_fixed, height_fixed = struct.unpack_from(">II", matrix_and_size, 36)
    width, height = width_fixed >> 16, height_fixed >> 16
    if not 1 <= width <= 32767 or not 1 <= height <= 32767:
        raise _incompatible("the subtitle display dimensions are not representable.")
    sample_header = reader.read(entry.payload, 38, entry.end)
    top, left, bottom, right = struct.unpack_from(">4h", sample_header, 18)
    if not (0 <= top < bottom <= height and 0 <= left < right <= width):
        raise _incompatible(
            "the subtitle default text box is empty or outside its track."
        )


def _media_clock(reader: _Reader, header: _Atom) -> _Clock:
    version = reader.read(header.payload, 1, header.end)[0]
    if version not in (0, 1):
        raise _incompatible("the media-header version is unsupported.")
    data = reader.read(header.payload, 24 if version == 0 else 36, header.end)
    offset = 12 if version == 0 else 20
    timescale = int.from_bytes(data[offset : offset + 4], "big")
    if timescale == 0:
        raise _invalid("the media timescale is zero.")
    duration = int.from_bytes(
        data[offset + 4 : offset + (8 if version == 0 else 12)], "big"
    )
    return _Clock(
        timescale, duration, header.payload + offset, 4 if version == 0 else 8
    )


def _check_clock(clock: _Clock) -> None:
    if clock.timescale < 100 or clock.timescale > _SIGNED_MAX or clock.timescale % 100:
        raise _incompatible(
            "the media timescale must be a positive signed value divisible by 100 "
            "to preserve the native centisecond clock."
        )
    if clock.duration > (1 << (clock.duration_size * 8 - 1)) - 1:
        raise _incompatible("the media duration crosses the native signed range.")


def _sample_clock(reader: _Reader, table: _Atom) -> tuple[_Run, ...]:
    header = reader.read(table.payload, 8, table.end)
    if header[:4] != bytes(4):
        raise _incompatible("the time-to-sample version or flags are unsupported.")
    run_count = int.from_bytes(header[4:], "big")
    if table.end - table.payload != 8 + run_count * 8:
        raise _invalid("the time-to-sample count differs from its entries.")
    reader.timing_run_count += run_count
    if reader.timing_run_count > _TIMING_RUN_LIMIT:
        raise _incompatible("the time-to-sample verification limit was exceeded.")
    runs: list[_Run] = []
    for index in range(run_count):
        count, delta = struct.unpack(
            ">II", reader.read(table.payload + 8 + index * 8, 8, table.end)
        )
        if count == 0:
            raise _invalid("a time-to-sample run contains no samples.")
        runs.append(_Run(count, delta, table.payload + 12 + index * 8))
    if run_count == 0:
        raise _incompatible("the selected track has no timed samples.")
    return tuple(runs)


def _check_sample_clock(runs: tuple[_Run, ...]) -> None:
    accumulated = 0
    for run in runs:
        # Both cache builders accumulate in a 32-bit register before signed
        # division. Widen only for checking; never alter the stored clock.
        accumulated += run.count * run.delta
        if (
            run.count > _SIGNED_MAX
            or run.delta > _SIGNED_MAX
            or accumulated > _SIGNED_MAX
        ):
            raise _incompatible(
                "accumulated sample timing crosses the native signed range."
            )
    # Deliberately allow the centisecond quantization inherent in native playback.
    # A nonmultiple timescale was rejected before dividing; samples need not be
    # multiples of a centisecond, and short/empty timing samples remain intact.


def _track_headers(
    reader: _Reader, track: _Atom, *, caption: bool, require_geometry: bool = True
) -> _Track:
    children = reader.children(track)
    media = reader.children(_one(children, b"mdia"))
    handler = _one(media, b"hdlr")
    handler_kind = reader.read(handler.payload + 8, 4, handler.end)
    expected_handlers = (b"clcp",) if caption else (b"sbtl", b"text", b"subt")
    if handler_kind not in expected_handlers:
        raise _incompatible("a selected track has the wrong media handler.")
    info = reader.children(_one(media, b"minf"))
    tables = reader.children(_one(info, b"stbl"))
    entry = _sample_entry(
        reader, _one(tables, b"stsd"), b"c608" if caption else b"tx3g"
    )
    if caption:
        reader.read(entry.payload, 8, entry.end)
    elif require_geometry:
        _subtitle_geometry(reader, _one(children, b"tkhd"), entry)
    else:
        reader.read(entry.payload, 38, entry.end)
    return _Track(children, media, tables)


def _selected_tracks(reader: _Reader, indices: tuple[int, ...]) -> tuple[_Atom, ...]:
    if len(set(indices)) != len(indices) or any(index < 0 for index in indices):
        raise _invalid("the selected track indices are invalid.")
    end = reader.stream.seek(0, io.SEEK_END)
    top = reader.atoms(0, end)
    movie = _one(top, b"moov")
    children = reader.children(movie)
    if any(atom.kind == b"moof" for atom in top) or any(
        atom.kind == b"mvex" for atom in children
    ):
        raise _incompatible(
            "fragmented timing cannot be verified from the sample table."
        )
    tracks = tuple(atom for atom in children if atom.kind == b"trak")
    if any(index >= len(tracks) for index in indices):
        raise _invalid("a selected track is missing.")
    return tuple(tracks[index] for index in indices)


def verify_geometry(stream: BinaryIO, subtitle_indices: tuple[int, ...]) -> None:
    """Check native subtitle identity and geometry independently of its clock."""
    if not subtitle_indices:
        return
    position = stream.tell()
    try:
        reader = _Reader(stream)
        for track in _selected_tracks(reader, subtitle_indices):
            _track_headers(reader, track, caption=False)
    finally:
        stream.seek(position)


def _verify_selected(
    stream: BinaryIO,
    subtitle_indices: tuple[int, ...],
    caption_indices: tuple[int, ...],
    *,
    require_geometry: bool,
) -> None:
    indices = (*subtitle_indices, *caption_indices)
    if not indices:
        return
    position = stream.tell()
    try:
        reader = _Reader(stream)
        for ordinal, atom in enumerate(_selected_tracks(reader, indices)):
            track = _track_headers(
                reader,
                atom,
                caption=ordinal >= len(subtitle_indices),
                require_geometry=require_geometry,
            )
            _check_clock(_media_clock(reader, _one(track.media, b"mdhd")))
            _check_sample_clock(_sample_clock(reader, _one(track.tables, b"stts")))
    finally:
        stream.seek(position)


def verify_compatibility(
    stream: BinaryIO,
    subtitle_indices: tuple[int, ...],
    caption_indices: tuple[int, ...] = (),
) -> None:
    """Validate selected prepared MP4 track ordinals without modifying bytes.

    Indices identify ordered moov/trak entries, never native tkhd track IDs.
    The preparation caller supplies them from its captured output inspection.
    Call both before and after tagging through Storage's private-file read access.
    """
    _verify_selected(stream, subtitle_indices, caption_indices, require_geometry=True)


def _rescale(value: int, timescale: int, *, size: int, signed: bool = False) -> bytes:
    scaled, remainder = divmod(value * 1000, timescale)
    if remainder:
        raise _incompatible(
            "the media clock cannot be changed to 1000 without rounding a timestamp."
        )
    minimum = -(1 << (size * 8 - 1)) if signed else 0
    maximum = (1 << (size * 8 - int(signed))) - 1
    if not minimum <= scaled <= maximum:
        raise _incompatible("an exactly rescaled timestamp exceeds its stored range.")
    return scaled.to_bytes(size, "big", signed=signed)


def _edit_patches(
    reader: _Reader, track: _Track, timescale: int
) -> tuple[tuple[int, bytes], ...]:
    containers = tuple(atom for atom in track.children if atom.kind == b"edts")
    if not containers:
        return ()
    if len(containers) != 1:
        raise _invalid("the track has duplicate edit containers.")
    children = reader.children(containers[0])
    if any(atom.kind not in (b"elst", b"free", b"skip") for atom in children):
        raise _incompatible("unknown edit timing prevents exact clock normalization.")
    table = _one(children, b"elst")
    header = reader.read(table.payload, 8, table.end)
    version = header[0]
    if version not in (0, 1) or header[1:4] != bytes(3):
        raise _incompatible(
            "the edit-list version or flags prevent clock normalization."
        )
    count = int.from_bytes(header[4:], "big")
    size = 4 if version == 0 else 8
    stride = size * 2 + 4
    if table.end - table.payload != 8 + count * stride:
        raise _invalid("the edit-list count differs from its entries.")
    reader.timing_run_count += count
    if reader.timing_run_count > _TIMING_RUN_LIMIT:
        raise _incompatible("the edit-list verification limit was exceeded.")
    patches: list[tuple[int, bytes]] = []
    for index in range(count):
        offset = table.payload + 8 + index * stride + size
        media_time = int.from_bytes(
            reader.read(offset, size, table.end), "big", signed=True
        )
        if media_time != -1:
            patches.append(
                (offset, _rescale(media_time, timescale, size=size, signed=True))
            )
    return tuple(patches)


def _composition_patches(
    reader: _Reader, track: _Track, timescale: int
) -> tuple[tuple[int, bytes], ...]:
    tables = tuple(atom for atom in track.tables if atom.kind == b"ctts")
    if not tables:
        return ()
    if len(tables) != 1:
        raise _invalid("the track has duplicate composition timing tables.")
    table = tables[0]
    header = reader.read(table.payload, 8, table.end)
    version = header[0]
    if version not in (0, 1) or header[1:4] != bytes(3):
        raise _incompatible(
            "the composition timing version or flags prevent normalization."
        )
    count = int.from_bytes(header[4:], "big")
    if table.end - table.payload != 8 + count * 8:
        raise _invalid("the composition timing count differs from its entries.")
    reader.timing_run_count += count
    if reader.timing_run_count > _TIMING_RUN_LIMIT:
        raise _incompatible("the composition timing verification limit was exceeded.")
    patches: list[tuple[int, bytes]] = []
    for index in range(count):
        offset = table.payload + 8 + index * 8
        row = reader.read(offset, 8, table.end)
        if int.from_bytes(row[:4], "big") == 0:
            raise _invalid("a composition timing run contains no samples.")
        value = int.from_bytes(row[4:], "big", signed=version == 1)
        patches.append(
            (offset + 4, _rescale(value, timescale, size=4, signed=version == 1))
        )
    return tuple(patches)


def _clock_patches(reader: _Reader, track: _Track) -> tuple[tuple[int, bytes], ...]:
    clock = _media_clock(reader, _one(track.media, b"mdhd"))
    runs = _sample_clock(reader, _one(track.tables, b"stts"))
    try:
        _check_clock(clock)
        _check_sample_clock(runs)
    except MediaInspectionError:
        pass
    else:
        return ()
    # Unknown timing must stay untouched, rather than retaining a stale clock.
    allowed_tables = {
        b"stsd",
        b"stts",
        b"stsz",
        b"stz2",
        b"stsc",
        b"stco",
        b"co64",
        b"stss",
        b"stsh",
        b"sdtp",
        b"padb",
        b"ctts",
        b"free",
        b"skip",
    }
    if (
        any(atom.kind not in allowed_tables for atom in track.tables)
        or any(
            atom.kind not in (b"mdhd", b"hdlr", b"minf", b"elng", b"free", b"skip")
            for atom in track.media
        )
        or any(
            atom.kind
            not in (
                b"tkhd",
                b"mdia",
                b"edts",
                b"tref",
                b"udta",
                b"meta",
                b"free",
                b"skip",
            )
            for atom in track.children
        )
    ):
        raise _incompatible(
            "unknown timing metadata prevents exact clock normalization."
        )
    if clock.duration == (1 << (clock.duration_size * 8)) - 1:
        raise _incompatible("an unknown media duration cannot be normalized exactly.")
    duration = _rescale(clock.duration, clock.timescale, size=clock.duration_size)
    normalized = _Clock(
        1000, int.from_bytes(duration, "big"), clock.offset, clock.duration_size
    )
    _check_clock(normalized)
    patches: list[tuple[int, bytes]] = [
        (clock.offset, (1000).to_bytes(4, "big")),
        (clock.offset + 4, duration),
    ]
    normalized_runs: list[_Run] = []
    for run in runs:
        delta = _rescale(run.delta, clock.timescale, size=4)
        normalized_runs.append(
            _Run(run.count, int.from_bytes(delta, "big"), run.offset)
        )
        patches.append((run.offset, delta))
    _check_sample_clock(tuple(normalized_runs))
    patches.extend(_edit_patches(reader, track, clock.timescale))
    patches.extend(_composition_patches(reader, track, clock.timescale))
    return tuple(patches)


def normalize_clocks(
    stream: BinaryIO,
    subtitle_indices: tuple[int, ...],
    caption_indices: tuple[int, ...] = (),
    *,
    require_geometry: bool = True,
) -> None:
    """Exactly rescale unsafe selected clocks to 1000 on a private Storage stream.

    Plan every patch before writing any bytes. Preserve atom sizes, header
    versions, sample bytes, movie-unit edit durations and chunk offsets. Safe
    clocks remain unchanged; inexact or unrecognized timing fails preparation.
    Set require_geometry=False for a captured source whose tkhd/geometry will
    subsequently be repaired or remuxed, to normalize clocks before FFmpeg can
    truncate an unrepresentable signed sample delta. Final output still needs
    verify_compatibility with its full geometry checks.
    """
    indices = (*subtitle_indices, *caption_indices)
    if not indices:
        return
    position = stream.tell()
    try:
        reader = _Reader(stream)
        patches: list[tuple[int, bytes]] = []
        for ordinal, atom in enumerate(_selected_tracks(reader, indices)):
            track = _track_headers(
                reader,
                atom,
                caption=ordinal >= len(subtitle_indices),
                require_geometry=require_geometry,
            )
            patches.extend(_clock_patches(reader, track))
        for offset, value in patches:
            stream.seek(offset)
            if stream.write(value) != len(value):
                raise _invalid(
                    "a normalized clock field could not be written completely."
                )
        _verify_selected(
            stream, subtitle_indices, caption_indices, require_geometry=require_geometry
        )
    finally:
        stream.seek(position)
