"""Native preparation validates header geometry and firmware sample clocks."""

from __future__ import annotations

import io
import struct
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app.media.inspection import MediaInspectionError
from iOpenPod.app.media.subtitles.compatibility import (
    normalize_clocks,
    verify_compatibility,
    verify_geometry,
)

if TYPE_CHECKING:
    from collections.abc import Buffer


def _atom(kind: bytes, payload: bytes, *, extended: bool = False) -> bytes:
    if extended:
        return struct.pack(">I4sQ", 1, kind, len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def _track(
    *,
    caption: bool = False,
    tkhd_version: int = 0,
    mdhd_version: int = 0,
    timescale: int = 1000,
    duration: int = 2000,
    runs: tuple[tuple[int, int], ...] = ((2, 1000),),
    width: int = 640,
    height: int = 54,
    text_box: tuple[int, int, int, int] = (0, 0, 54, 640),
    track_id: int = 3,
    entry_kind: bytes | None = None,
    declared_runs: int | None = None,
    declared_entries: int = 1,
    edit_version: int = 1,
    edit_times: tuple[int, ...] = (0,),
    composition_version: int = 0,
    composition_offset: int | None = None,
    extra_table: bytes = b"",
) -> bytes:
    tkhd = bytearray(84 if tkhd_version == 0 else 96)
    tkhd[0] = tkhd_version
    tkhd[3] = 3
    struct.pack_into(">I", tkhd, 12 if tkhd_version == 0 else 20, track_id)
    matrix_offset = 40 if tkhd_version == 0 else 52
    struct.pack_into(
        ">9i", tkhd, matrix_offset, 65536, 0, 0, 0, 65536, 0, 0, 306 << 16, 1 << 30
    )
    struct.pack_into(">II", tkhd, matrix_offset + 36, width << 16, height << 16)
    mdhd = bytearray(24 if mdhd_version == 0 else 36)
    mdhd[0] = mdhd_version
    clock_offset = 12 if mdhd_version == 0 else 20
    struct.pack_into(">I", mdhd, clock_offset, timescale)
    struct.pack_into(
        ">I" if mdhd_version == 0 else ">Q", mdhd, clock_offset + 4, duration
    )
    sample = bytearray(8 if caption else 38)
    sample[7] = 1
    if not caption:
        struct.pack_into(">4h", sample, 18, *text_box)
    entry = _atom(entry_kind or (b"c608" if caption else b"tx3g"), bytes(sample))
    stsd = _atom(b"stsd", struct.pack(">II", 0, declared_entries) + entry)
    stts = _atom(
        b"stts",
        struct.pack(">II", 0, len(runs) if declared_runs is None else declared_runs)
        + b"".join(struct.pack(">II", *run) for run in runs),
    )
    ctts = (
        _atom(
            b"ctts",
            bytes((composition_version, 0, 0, 0))
            + struct.pack(">II", 1, 2)
            + composition_offset.to_bytes(4, "big", signed=composition_version == 1),
        )
        if composition_offset is not None
        else b""
    )
    media = (
        _atom(b"mdhd", bytes(mdhd))
        + _atom(b"hdlr", bytes(8) + (b"clcp" if caption else b"sbtl") + bytes(12))
        + _atom(b"minf", _atom(b"stbl", stsd + stts + ctts + extra_table))
    )
    # A valid version-1 edit list must not be rejected with version-1 tkhd.
    edit = _atom(
        b"elst",
        bytes((edit_version, 0, 0, 0))
        + len(edit_times).to_bytes(4, "big")
        + b"".join(
            struct.pack(">IiI" if edit_version == 0 else ">QqI", 2000, time, 65536)
            for time in edit_times
        ),
    )
    return _atom(
        b"trak",
        _atom(b"tkhd", bytes(tkhd)) + _atom(b"edts", edit) + _atom(b"mdia", media),
    )


def _movie(*tracks: bytes) -> bytes:
    mvhd = bytearray(112)
    mvhd[0] = 1
    struct.pack_into(">IQ", mvhd, 20, 1000, 2000)
    return _atom(b"moov", _atom(b"mvhd", bytes(mvhd)) + b"".join(tracks))


class _HeaderOnlyStream(io.BytesIO):
    def __init__(self, data: bytes, media_end: int = 0) -> None:
        super().__init__(data)
        self.media_end = media_end

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and 0 <= size <= 44
        if self.media_end:
            assert self.tell() >= self.media_end or self.tell() + size <= 16
        return super().read(size)

    def write(self, data: Buffer, /) -> int:
        raise AssertionError("Compatibility validation must never write")


@pytest.mark.parametrize("mdhd_version", [0, 1])
def test_native_headers_preserve_bytes_and_accept_supported_version_one_timing(
    mdhd_version: int,
) -> None:
    media = _atom(b"mdat", b"unaltered compressed media" * 10_000, extended=True)
    before = media + _movie(_track(mdhd_version=mdhd_version))
    stream = _HeaderOnlyStream(before, len(media))
    stream.seek(7)

    verify_compatibility(stream, (0,))

    assert stream.tell() == 7
    assert stream.getvalue() == before


def test_native_geometry_need_not_use_converted_fifteen_percent_layout() -> None:
    stream = _HeaderOnlyStream(_movie(_track(height=80, text_box=(3, 8, 74, 620))))
    verify_compatibility(stream, (0,))


@pytest.mark.parametrize("timescale", [100, 1000, 90_000, 1_000_000])
def test_positive_exact_centisecond_divisors_are_compatible(timescale: int) -> None:
    verify_compatibility(io.BytesIO(_movie(_track(timescale=timescale))), (0,))


@pytest.mark.parametrize("timescale", [1, 99, 101, 44_101, 0x80000000])
def test_clock_truncation_or_signed_divisor_is_incompatible(timescale: int) -> None:
    before = _movie(_track(timescale=timescale))
    stream = _HeaderOnlyStream(before)
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(stream, (0,))
    assert caught.value.code == "media.subtitle_incompatible"
    assert stream.getvalue() == before


@pytest.mark.parametrize(
    "track",
    [
        _track(tkhd_version=1),
        _track(width=0),
        _track(height=0),
        _track(width=40000),
        _track(text_box=(0, 0, 0, 0)),
        _track(text_box=(-1, 0, 54, 640)),
        _track(text_box=(0, 0, 55, 640)),
        _track(text_box=(0, 0, 54, 641)),
        _track(entry_kind=b"text"),
        _track(mdhd_version=2),
        _track(duration=0x80000000),
        _track(mdhd_version=1, duration=1 << 63),
        _track(runs=((1, 0x80000000),)),
        _track(runs=((2, 0x40000000),)),
        _track(runs=((1, 0x40000000), (1, 0x40000000))),
        _track(runs=((0x80000000, 0),)),
        _track(runs=()),
    ],
)
def test_unsafe_but_parseable_native_headers_are_incompatible(track: bytes) -> None:
    stream = _HeaderOnlyStream(_movie(track))
    stream.seek(3)
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(stream, (0,))
    assert caught.value.code == "media.subtitle_incompatible"
    assert stream.tell() == 3


def test_signed_boundary_and_subcentisecond_sample_deltas_are_retained() -> None:
    stream = _HeaderOnlyStream(
        _movie(
            _track(mdhd_version=1, duration=0x7FFFFFFF, runs=((1, 0x7FFFFFFE), (1, 1)))
        )
    )
    verify_compatibility(stream, (0,))


@pytest.mark.parametrize(
    "track",
    [
        _track(timescale=0),
        _track(track_id=0),
        _track(runs=((0, 1000),)),
        _track(declared_runs=3),
        _track(declared_runs=0xFFFFFFFF),
        _track(declared_entries=2),
    ],
)
def test_malformed_headers_have_a_distinct_diagnostic(track: bytes) -> None:
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(io.BytesIO(_movie(track)), (0,))
    assert caught.value.code == "media.subtitle_structure_invalid"


@pytest.mark.parametrize("indices", [(-1,), (1,), (0, 0)])
def test_invalid_indices_are_not_interpreted_as_native_track_ids(
    indices: tuple[int, ...],
) -> None:
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(io.BytesIO(_movie(_track(track_id=5))), indices)
    assert caught.value.code == "media.subtitle_structure_invalid"


def test_only_selected_track_headers_are_inspected() -> None:
    stream = _HeaderOnlyStream(_movie(_track(tkhd_version=1), _track(track_id=5)))
    verify_compatibility(stream, (1,))


def test_no_selection_does_not_parse_the_stream() -> None:
    verify_compatibility(_HeaderOnlyStream(b"uninspected"), ())


def test_atom_verification_work_is_bounded() -> None:
    data = _movie(_track()) + _atom(b"free", b"") * 10_000
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(_HeaderOnlyStream(data), (0,))
    assert caught.value.code == "media.subtitle_incompatible"
    assert "verification limit" in str(caught.value)


def test_timing_verification_work_is_bounded_without_expanding_samples() -> None:
    data = _movie(_track(runs=((1, 1),) * 100_001))
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(_HeaderOnlyStream(data), (0,))
    assert caught.value.code == "media.subtitle_incompatible"
    assert "verification limit" in str(caught.value)


def test_captions_share_clock_checks_without_inferred_subtitle_geometry_limits() -> (
    None
):
    stream = _HeaderOnlyStream(
        _movie(_track(caption=True, tkhd_version=1, width=0, height=0, mdhd_version=1))
    )
    verify_compatibility(stream, (), (0,))


@pytest.mark.parametrize(
    "track",
    [
        _track(caption=True, timescale=101),
        _track(caption=True, runs=((2, 0x40000000),)),
        _track(caption=True, entry_kind=b"c708"),
    ],
)
def test_captions_reject_unsafe_clocks_and_unproven_sample_formats(
    track: bytes,
) -> None:
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(io.BytesIO(_movie(track)), (), (0,))
    assert caught.value.code == "media.subtitle_incompatible"


@pytest.mark.parametrize(
    "suffix",
    [
        b"\0\0\0",
        struct.pack(">I4s", 7, b"free"),
        struct.pack(">I4s", 99, b"free"),
        struct.pack(">I4sQ", 1, b"free", 15),
    ],
)
def test_atom_bounds_are_checked_without_reading_media(suffix: bytes) -> None:
    with pytest.raises(MediaInspectionError) as caught:
        verify_compatibility(io.BytesIO(_movie(_track()) + suffix), (0,))
    assert caught.value.code == "media.subtitle_structure_invalid"


class _ClockPatchStream(_HeaderOnlyStream):
    def write(self, data: Buffer, /) -> int:
        assert memoryview(data).nbytes <= 8
        assert self.tell() >= self.media_end
        return io.BytesIO.write(self, data)


@pytest.mark.parametrize("version", [0, 1])
@pytest.mark.parametrize("caption", [False, True])
def test_unsafe_clock_normalizes_exactly_without_rewriting_media(
    version: int,
    caption: bool,
) -> None:
    media = _atom(b"mdat", b"unchanged samples" * 10_000, extended=True)
    offset_table = _atom(b"stco", struct.pack(">III", 0, 1, 16))
    before = media + _movie(
        _track(
            caption=caption,
            mdhd_version=version,
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((2, 1_800_000_000),),
            edit_version=version,
            edit_times=(-1, 2_000_000),
            composition_version=version,
            composition_offset=-1_000_000 if version == 1 else 1_000_000,
            extra_table=offset_table,
        )
    )
    stream = _ClockPatchStream(before, len(media))
    stream.seek(7)
    subtitles, captions = ((), (0,)) if caption else ((0,), ())

    normalize_clocks(stream, subtitles, captions)

    after = stream.getvalue()
    assert stream.tell() == 7
    assert len(after) == len(before)
    assert after[: len(media)] == media
    assert offset_table in after
    mdhd = after.index(b"mdhd") + 4
    assert after[mdhd] == version
    clock = mdhd + (12 if version == 0 else 20)
    assert int.from_bytes(after[clock : clock + 4], "big") == 1000
    size = 4 if version == 0 else 8
    assert int.from_bytes(after[clock + 4 : clock + 4 + size], "big") == 3_600_000
    stts = after.index(b"stts") + 4
    assert struct.unpack_from(">II", after, stts + 8) == (2, 1_800_000)
    elst = after.index(b"elst") + 4
    stride = size * 2 + 4
    for index, expected_time in enumerate((-1, 2000)):
        start = elst + 8 + index * stride
        assert int.from_bytes(after[start : start + size], "big") == 2000
        assert (
            int.from_bytes(after[start + size : start + size * 2], "big", signed=True)
            == expected_time
        )
        assert after[start + size * 2 : start + stride] == (65536).to_bytes(4, "big")
    ctts = after.index(b"ctts") + 4
    assert int.from_bytes(after[ctts + 12 : ctts + 16], "big", signed=version == 1) == (
        -1000 if version == 1 else 1000
    )
    verify_compatibility(stream, subtitles, captions)
    normalize_clocks(stream, subtitles, captions)
    assert stream.getvalue() == after


@pytest.mark.parametrize("timescale", [99, 101, 44_101])
def test_noncentisecond_clock_can_be_repaired_when_every_timestamp_is_exact(
    timescale: int,
) -> None:
    stream = _ClockPatchStream(
        _movie(
            _track(timescale=timescale, duration=timescale * 2, runs=((2, timescale),))
        )
    )
    normalize_clocks(stream, (0,))
    verify_compatibility(stream, (0,))


def test_safe_clock_is_byte_exact_even_when_millisecond_rescaling_would_round() -> None:
    before = _movie(
        _track(
            timescale=1_000_000,
            duration=2001,
            runs=((1, 1000), (1, 1001)),
            edit_times=(1,),
        )
    )
    stream = _HeaderOnlyStream(before)
    normalize_clocks(stream, (0,))
    assert stream.getvalue() == before


@pytest.mark.parametrize(
    "track",
    [
        _track(timescale=1_000_000, duration=3_600_000_001, runs=((2, 1_800_000_000),)),
        _track(
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((1, 1_800_000_000), (1, 1_800_000_001)),
        ),
        _track(
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((2, 1_800_000_000),),
            edit_times=(1,),
        ),
        _track(
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((2, 1_800_000_000),),
            composition_version=1,
            composition_offset=-1,
        ),
        _track(
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((2, 1_800_000_000),),
            extra_table=_atom(b"cslg", bytes(24)),
        ),
        _track(
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((2, 1_800_000_000),),
            composition_version=2,
            composition_offset=1000,
        ),
        _track(timescale=1_000_000, duration=0xFFFFFFFF, runs=((2, 1_800_000_000),)),
        _track(
            timescale=1_000_000,
            mdhd_version=1,
            duration=3_000_000_000_000,
            runs=((3_000_000, 1_000_000),),
        ),
    ],
)
def test_inexact_or_unknown_timing_rejects_every_patch_before_writing(
    track: bytes,
) -> None:
    first = _track(
        timescale=1_000_000, duration=3_600_000_000, runs=((2, 1_800_000_000),)
    )
    before = _movie(first, track)
    stream = _HeaderOnlyStream(before)
    with pytest.raises(MediaInspectionError) as caught:
        normalize_clocks(stream, (0, 1))
    assert caught.value.code == "media.subtitle_incompatible"
    assert stream.getvalue() == before


def test_fragmented_timing_cannot_be_normalized_from_an_incomplete_sample_table() -> (
    None
):
    stream = _HeaderOnlyStream(_movie(_track()) + _atom(b"moof", bytes(8)))
    with pytest.raises(MediaInspectionError) as caught:
        normalize_clocks(stream, (0,))
    assert caught.value.code == "media.subtitle_incompatible"


def test_no_clock_selection_leaves_arbitrary_bytes_untouched() -> None:
    normalize_clocks(_HeaderOnlyStream(b"uninspected"), ())


def test_geometry_verification_does_not_reject_an_independently_unsafe_clock() -> None:
    stream = _HeaderOnlyStream(_movie(_track(timescale=101)))
    stream.seek(5)
    verify_geometry(stream, (0,))
    assert stream.tell() == 5
    with pytest.raises(MediaInspectionError):
        verify_compatibility(stream, (0,))


@pytest.mark.parametrize(
    "track", [_track(tkhd_version=1), _track(text_box=(0, 0, 0, 0))]
)
def test_geometry_verification_rejects_native_header_and_rectangle_problems(
    track: bytes,
) -> None:
    stream = _HeaderOnlyStream(_movie(track))
    stream.seek(5)
    with pytest.raises(MediaInspectionError) as caught:
        verify_geometry(stream, (0,))
    assert caught.value.code == "media.subtitle_incompatible"
    assert stream.tell() == 5


@pytest.mark.parametrize("version", [0, 1])
def test_source_clock_can_normalize_before_track_header_and_geometry_repair(
    version: int,
) -> None:
    before = _movie(
        _track(
            tkhd_version=version,
            text_box=(0, 0, 0, 0),
            timescale=1_000_000,
            duration=3_600_000_000,
            runs=((2, 1_800_000_000),),
        )
    )
    stream = _ClockPatchStream(before)
    normalize_clocks(stream, (0,), require_geometry=False)
    after = stream.getvalue()
    mdhd = after.index(b"mdhd") + 4
    assert int.from_bytes(after[mdhd + 12 : mdhd + 16], "big") == 1000
    tkhd = after.index(b"tkhd") + 4
    assert after[tkhd] == version
    sample = after.index(b"tx3g") + 4
    assert after[sample + 18 : sample + 26] == bytes(8)
    with pytest.raises(MediaInspectionError):
        verify_compatibility(stream, (0,))
    normalize_clocks(stream, (0,), require_geometry=False)
    assert stream.getvalue() == after


def test_clock_only_mode_still_rejects_inexact_source_timing_without_writing() -> None:
    before = _movie(
        _track(
            tkhd_version=1,
            text_box=(0, 0, 0, 0),
            timescale=1_000_000,
            duration=3_600_000_001,
            runs=((2, 1_800_000_000),),
        )
    )
    stream = _HeaderOnlyStream(before)
    with pytest.raises(MediaInspectionError) as caught:
        normalize_clocks(stream, (0,), require_geometry=False)
    assert caught.value.code == "media.subtitle_incompatible"
    assert stream.getvalue() == before
