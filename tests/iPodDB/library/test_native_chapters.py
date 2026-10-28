"""Classic named-Chapter interpretation is distinct from editable metadata."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    ChapterDataFlags,
    MhodChapterDataChapter,
    MhodChapterDataHedrHeader,
    MhodChapterDataNameHeader,
    MhodChapterDataPayload,
    MhodChapterDataPreamble,
    MhodChapterDataRawAtom,
    MhodChapterDataSeanHeader,
)
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.library.native_chapters import interpret_native_chapters


def chapter_payload(
    flags: int | None = 1,
    chapters: tuple[MhodChapterDataChapter, ...] | None = None,
) -> MhodChapterDataPayload:
    return MhodChapterDataPayload(
        MhodChapterDataPreamble(0, 0, 0),
        MhodChapterDataSeanHeader(atom_type=b"sean"),
        MhodChapterDataHedrHeader(atom_type=b"hedr", unk_0x08=1, unk_0x18=flags)
        if flags is not None
        else None,
        chapters
        if chapters is not None
        else (
            MhodChapterDataChapter("Start", 0, ()),
            MhodChapterDataChapter("Later", 500, ()),
        ),
        (),
    )


def chapter_source(payload: MhodChapterDataPayload) -> IPodLibrary:
    document = parse_iTunesDB(library().serialize().itunes)
    selection = document.find_chunks(MhitHeader)[0]
    document = document.replace_chunk(
        selection,
        selection.chunk.append_child(
            new_itunes_chunk(
                MHOD, MhodHeader(mhod_type=MhodType.CHAPTER_DATA), payload=payload
            )
        ),
    )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize("flags", [0, 1, 2, 3, 0x80000003])
def test_flags_gate_named_index_and_artwork_without_losing_unknown_bits(
    flags: int,
) -> None:
    payload = chapter_payload(flags)
    assert payload.hedr is not None
    assert int(payload.hedr.flags) == flags
    assert payload.hedr.named_chapters_enabled == bool(flags & 1)
    assert payload.hedr.chapter_artwork_enabled == bool(flags & 2)
    assert int(ChapterDataFlags.HAS_NAMED_CHAPTERS) == 1
    assert int(ChapterDataFlags.HAS_CHAPTER_ARTWORK) == 2
    native = interpret_native_chapters(payload)
    assert len(native.entries) == (2 if flags & 1 else 0)
    assert native.chapter_artwork_eligible == (flags & 3 == 3)


@pytest.mark.parametrize(("first_flags", "last_flags"), [(0, 3), (3, 0)])
def test_duplicate_headers_remain_uninterpreted_and_lossless(
    first_flags: int,
    last_flags: int,
) -> None:
    raw = struct.pack(">I4sIIIII", 28, b"hedr", 1, 0, 0, 0, first_flags)
    payload = replace(
        chapter_payload(last_flags),
        other_atoms=(MhodChapterDataRawAtom(b"hedr", raw),),
        chapter_atom_indices=(1, 2),
        hedr_atom_index=3,
    )
    source = chapter_source(payload)
    original = source.serialize().itunes
    track = source.snapshot.tracks[0]
    assert track.ipod is not None and track.ipod.native_chapters is not None
    native = track.ipod.native_chapters
    assert native.flags is None
    assert native.entries == ()
    assert not native.chapter_artwork_eligible
    assert native.diagnostics == ("duplicate_header",)
    assert len(track.metadata.chapters) == 2
    plan = source.analyze(source.begin_draft())
    assert "source.chapter_duplicate_header" in {issue.code for issue in plan.issues}
    assert source.serialize().itunes == original


def test_name_atom_presence_and_raw_start_one_have_separate_meanings() -> None:
    payload = chapter_payload(
        chapters=(
            MhodChapterDataChapter("", 0, ()),
            MhodChapterDataChapter(
                "", 1, (), name_header=MhodChapterDataNameHeader(atom_type=b"name")
            ),
            MhodChapterDataChapter("Later", 500, ()),
        )
    )
    native = interpret_native_chapters(payload)
    assert [
        (c.chapter_ordinal, c.raw_start_ms, c.start_ms) for c in native.entries
    ] == [(2, 1, 0), (3, 500, 500)]
    assert native.index_at(0) == 0
    assert native.diagnostics == ("unnamed_chapters",)
    assert len(payload.chapters) == 3
    assert payload.chapters[1].start_pos_ms == 1


@pytest.mark.parametrize("position", [True, -1, 0x100000000, 1.5, "invalid", None])
def test_native_lookup_rejects_positions_outside_unsigned_contract(
    position: int,
) -> None:
    native = interpret_native_chapters(chapter_payload())
    with pytest.raises(ValueError, match="unsigned 32-bit"):
        native.index_at(position)


@pytest.mark.parametrize(
    ("starts", "position", "expected"),
    [
        ((0, 500), 499, 0),
        ((0, 500), 500, 1),
        ((0, 500, 500), 500, 2),
        ((0, 800, 400), 500, 0),
        ((500,), 0, -1),
        ((), 0, -1),
    ],
)
def test_native_scan_keeps_order_and_duplicate_boundary(
    starts: tuple[int, ...], position: int, expected: int
) -> None:
    payload = chapter_payload(
        chapters=tuple(
            MhodChapterDataChapter(str(i), start, ()) for i, start in enumerate(starts)
        )
    )
    native = interpret_native_chapters(payload)
    assert native.index_at(position) == expected
    assert ("unordered_starts" in native.diagnostics) == (
        starts != tuple(sorted(starts))
    )
    assert ("duplicate_starts" in native.diagnostics) == (
        len(starts) != len(set(starts))
    )


def test_projected_native_diagnostics_do_not_filter_editable_chapters_or_rewrite_bytes() -> (
    None
):
    source = chapter_source(chapter_payload(2))
    original = source.serialize().itunes
    track = source.snapshot.tracks[0]
    assert len(track.metadata.chapters) == 2
    assert track.ipod is not None and track.ipod.native_chapters is not None
    assert track.ipod.native_chapters.entries == ()
    plan = source.analyze(source.begin_draft())
    assert "source.chapter_navigation_disabled" in {issue.code for issue in plan.issues}
    assert source.serialize().itunes == original
    changed = replace(track, title="A new title")
    desired = replace(source.snapshot, tracks=(changed, *source.snapshot.tracks[1:]))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    saved = IPodLibrary(result.prepared.itunes).snapshot.tracks[0]
    assert saved.ipod is not None and saved.ipod.native_chapters is not None
    assert saved.ipod.native_chapters.flags == 2
    assert saved.metadata.chapters == track.metadata.chapters
