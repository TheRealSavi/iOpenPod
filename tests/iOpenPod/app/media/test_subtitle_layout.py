"""Converted text uses the subtitle rectangle expected by QuickTime/iPod."""

import io
import struct

import pytest

from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.subtitles.layout import configure_layout, verify_layout


def _atom(kind: bytes, payload: bytes, *, extended: bool = False) -> bytes:
    if extended:
        return struct.pack(">I4sQ", 1, kind, len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _track(
    handler: bytes,
    width: int,
    height: int,
    *,
    version: int = 0,
    entry: bytes = b"tx3g",
    extended: bool = False,
) -> bytes:
    header = bytearray(84 if version == 0 else 96)
    header[0] = version
    header[3] = 3
    matrix_offset = 40 if version == 0 else 52
    struct.pack_into(
        ">9i", header, matrix_offset, 65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824
    )
    struct.pack_into(">II", header, matrix_offset + 36, width << 16, height << 16)
    sample = bytearray(38)
    sample[7] = 1  # data_reference_index
    struct.pack_into(">I", sample, 8, 0x20000020)  # vertical placement + other flag
    sample[33] = 16
    description = _atom(b"stsd", b"\0\0\0\0\0\0\0\1" + _atom(entry, bytes(sample)))
    media = _atom(b"hdlr", bytes(8) + handler + bytes(12))
    if handler != b"vide":
        media += _atom(b"minf", _atom(b"stbl", description))
    return _atom(
        b"trak",
        _atom(b"tkhd", bytes(header)) + _atom(b"mdia", media),
        extended=extended,
    )


@pytest.mark.parametrize("version", [0, 1])
def test_converted_subtitle_occupies_bottom_fifteen_percent(version: int) -> None:
    video = _track(b"vide", 640, 360, version=version)
    subtitle = _track(b"sbtl", 640, 360, version=version)
    untouched = _track(b"sbtl", 640, 54, version=version)
    media = _atom(b"mdat", b"video and subtitle samples remain byte exact")
    before = _atom(b"moov", video + subtitle + untouched) + media
    stream = io.BytesIO(before)
    with pytest.raises(MediaInspectionError):
        verify_layout(stream, (1,))

    configure_layout(stream, (1,))

    after = stream.getvalue()
    selected_start = 8 + len(video)
    tkhd_payload = selected_start + 16
    matrix_offset = tkhd_payload + (40 if version == 0 else 52)
    assert struct.unpack_from(">9i", after, matrix_offset) == (
        65536,
        0,
        0,
        0,
        65536,
        0,
        0,
        20054016,
        1073741824,
    )
    assert struct.unpack_from(">II", after, matrix_offset + 36) == (41943040, 3538944)
    tx3g_payload = after.index(b"tx3g", selected_start) + 4
    assert struct.unpack_from(">4h", after, tx3g_payload + 18) == (0, 0, 54, 640)
    assert struct.unpack_from(">I", after, tx3g_payload + 8) == (0x20,)
    assert (
        after[tx3g_payload + 26 : tx3g_payload + 38]
        == before[tx3g_payload + 26 : tx3g_payload + 38]
    )
    assert after[:selected_start] == before[:selected_start]
    assert (
        after[selected_start + len(subtitle) :]
        == before[selected_start + len(subtitle) :]
    )
    assert len(after) == len(before)
    verify_layout(stream, (1,))
    configure_layout(stream, (1,))
    assert stream.getvalue() == after


def test_inconsistent_sample_count_rejects_all_changes_before_writing() -> None:
    video = _track(b"vide", 640, 360)
    first = _track(b"sbtl", 640, 360)
    second = bytearray(_track(b"sbtl", 640, 360))
    stsd_payload = second.index(b"stsd") + 4
    # It claims one sample entry but contains two: do not modify either track.
    extra = _atom(b"text", bytes(38))
    for kind in (b"trak", b"mdia", b"minf", b"stbl", b"stsd"):
        offset = second.index(kind) - 4
        size = struct.unpack_from(">I", second, offset)[0]
        struct.pack_into(">I", second, offset, size + len(extra))
    second.extend(extra)
    assert second[stsd_payload + 4 : stsd_payload + 8] == b"\0\0\0\1"
    before = _atom(b"moov", video + first + second)
    stream = io.BytesIO(before)

    with pytest.raises(MediaInspectionError):
        configure_layout(stream, (1, 2))

    assert stream.getvalue() == before


class _HeaderOnlyStream(io.BytesIO):
    """Fail if a parser loads samples or reads more than one small header."""

    def __init__(self, data: bytes, sample_start: int, sample_end: int) -> None:
        super().__init__(data)
        self._sample_start = sample_start
        self._sample_end = sample_end

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and 0 <= size <= 44
        start = self.tell()
        assert start >= self._sample_end or start + size <= self._sample_start
        return super().read(size)


def test_extended_atom_sizes_skip_samples_even_when_movie_header_is_last() -> None:
    media = _atom(b"mdat", b"untouched samples" * 10_000, extended=True)
    movie = _atom(
        b"moov",
        _track(b"vide", 320, 240, extended=True)
        + _track(b"sbtl", 320, 240, version=1, extended=True),
        extended=True,
    )
    before = media + movie
    stream = _HeaderOnlyStream(before, 16, len(media))

    configure_layout(stream, (1,))
    verify_layout(stream, (1,))

    after = stream.getvalue()
    assert after[: len(media)] == media
    tx3g_payload = after.index(b"tx3g") + 4
    assert struct.unpack_from(">4h", after, tx3g_payload + 18) == (0, 0, 36, 320)


@pytest.mark.parametrize(
    ("invalid_track", "indices"),
    [
        (_track(b"soun", 640, 360), (1, 2)),
        (_track(b"sbtl", 640, 360, entry=b"text"), (1, 2)),
        (_track(b"sbtl", 640, 360, version=2), (1, 2)),
        (_track(b"vide", 640, 360), (1,)),
        (_track(b"sbtl", 640, 360), (1, 4)),
        (_track(b"sbtl", 640, 360), (1, 1)),
        (_track(b"sbtl", 640, 360), (-1,)),
    ],
)
def test_invalid_tracks_cannot_partially_modify_an_earlier_track(
    invalid_track: bytes, indices: tuple[int, ...]
) -> None:
    before = _atom(
        b"moov",
        _track(b"vide", 640, 360) + _track(b"sbtl", 640, 360) + invalid_track,
    )
    stream = io.BytesIO(before)

    with pytest.raises(MediaInspectionError) as caught:
        configure_layout(stream, indices)

    assert caught.value.code == "media.subtitle_layout_invalid"
    assert stream.getvalue() == before


@pytest.mark.parametrize(
    "suffix",
    [
        b"\0\0\0",
        struct.pack(">I4s", 7, b"free"),
        struct.pack(">I4s", 100, b"free"),
        struct.pack(">I4sQ", 1, b"free", 15),
    ],
)
def test_invalid_atom_bounds_reject_before_any_write(suffix: bytes) -> None:
    before = (
        _atom(b"moov", _track(b"vide", 640, 360) + _track(b"sbtl", 640, 360)) + suffix
    )
    stream = io.BytesIO(before)

    with pytest.raises(MediaInspectionError):
        configure_layout(stream, (1,))

    assert stream.getvalue() == before


@pytest.mark.parametrize(("width", "height"), [(0, 360), (640, 0), (40000, 360)])
def test_unrepresentable_video_rectangle_rejects_before_writing(
    width: int, height: int
) -> None:
    before = _atom(b"moov", _track(b"vide", width, height) + _track(b"sbtl", 640, 360))
    stream = io.BytesIO(before)

    with pytest.raises(MediaInspectionError):
        configure_layout(stream, (1,))

    assert stream.getvalue() == before


def test_no_selected_conversions_leaves_native_tracks_uninspected() -> None:
    stream = io.BytesIO(b"not a parsed MP4: no converted tracks requested")
    before = stream.getvalue()

    configure_layout(stream, ())
    verify_layout(stream, ())

    assert stream.getvalue() == before
