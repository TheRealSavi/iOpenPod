"""Chapter data MHOD payload definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from typing import NamedTuple

from iPodDB.shared.chunk import BinaryStruct, MhodPayload
from iPodDB.shared.chunk_field import chunk_field as cf


class MhodChapterDataPreamble(NamedTuple):
    unk_0x18: int
    unk_0x1C: int
    unk_0x20: int


class MhodChapterDataRawAtom(NamedTuple):
    """Opaque chapter-data atom preserved byte-for-byte in its source position."""

    atom_type: bytes
    raw: bytes


@dataclass(frozen=True, slots=True)
class MhodChapterDataSeanHeader(BinaryStruct):
    """Root `sean` atom header."""

    total_size: int = cf(0x00, "be_u32")
    atom_type: bytes = cf(0x04, "raw", size=4)
    # Original iOpenPod and libgpod author 1 here; parsed values stay retained.
    unk_0x08: int = cf(0x08, "be_u32", default=1)
    child_count: int = cf(0x0C, "be_u32")
    unk_0x10: int = cf(0x10, "be_u32")


@dataclass(frozen=True, slots=True)
class MhodChapterDataChapHeader(BinaryStruct):
    """One `chap` atom header."""

    total_size: int = cf(0x00, "be_u32")
    atom_type: bytes = cf(0x04, "raw", size=4)
    start_position_ms: int = cf(0x08, "be_u32")
    child_count: int = cf(0x0C, "be_u32")
    unk_0x10: int = cf(0x10, "be_u32")


@dataclass(frozen=True, slots=True)
class MhodChapterDataNameHeader(BinaryStruct):
    """`name` child atom preceding a UTF-16BE chapter title."""

    total_size: int = cf(0x00, "be_u32")
    atom_type: bytes = cf(0x04, "raw", size=4)
    unk_0x08: int = cf(0x08, "be_u32")
    unk_0x0C: int = cf(0x0C, "be_u32")
    unk_0x10: int = cf(0x10, "be_u32")
    string_length: int = cf(0x14, "be_u16")


class ChapterDataFlags(IntFlag):
    """Classic 120GB 2.0.1 `hedr` flags; other bits remain retained."""

    HAS_NAMED_CHAPTERS = 0x1
    HAS_CHAPTER_ARTWORK = 0x2


@dataclass(frozen=True, slots=True)
class MhodChapterDataHedrHeader(BinaryStruct):
    """Final `hedr` atom normally terminating the `sean` children."""

    total_size: int = cf(0x00, "be_u32")
    atom_type: bytes = cf(0x04, "raw", size=4)
    unk_0x08: int = cf(0x08, "be_u32")
    child_count: int = cf(0x0C, "be_u32")
    unk_0x10: int = cf(0x10, "be_u32")
    # Classic 120GB 2.0.1's 0x080a42c0 copies both hedr payload words,
    # but the known navigation/artwork flags are in the second one (+0x18).
    unk_0x14: int = cf(0x14, "be_u32")
    # Raw flags: mask 0x1 gates named Chapters (0x08023050); mask 0x2
    # enables the import-side chapter-artwork flags (0x08074980).
    # Other bits remain unknown. Keep the raw name for compatibility and use
    # .flags for the named view (ADR-0202); this is not sean +0x08.
    # See docs/research/unknown-field-reconciliation.md.
    unk_0x18: int = cf(0x18, "be_u32")

    @property
    def flags(self) -> ChapterDataFlags:
        """Expose known masks without discarding unknown bits or renaming storage."""
        return ChapterDataFlags(self.unk_0x18)

    @property
    def named_chapters_enabled(self) -> bool:
        return bool(self.flags & ChapterDataFlags.HAS_NAMED_CHAPTERS)

    @property
    def chapter_artwork_enabled(self) -> bool:
        return bool(self.flags & ChapterDataFlags.HAS_CHAPTER_ARTWORK)


@dataclass(frozen=True, slots=True)
class MhodChapterDataChapter:
    name: str
    start_pos_ms: int
    other_atoms: tuple[MhodChapterDataRawAtom, ...]
    chap_header: MhodChapterDataChapHeader | None = None
    name_header: MhodChapterDataNameHeader | None = None
    name_atom_index: int | None = None
    name_trailing_data: bytes = b""
    trailing_data: bytes = b""


@dataclass(frozen=True, slots=True)
class MhodChapterDataPayload(MhodPayload):
    preamble: MhodChapterDataPreamble
    sean: MhodChapterDataSeanHeader
    hedr: MhodChapterDataHedrHeader | None
    chapters: tuple[MhodChapterDataChapter, ...]
    other_atoms: tuple[MhodChapterDataRawAtom, ...]
    chapter_atom_indices: tuple[int, ...] = ()
    hedr_atom_index: int | None = None
    hedr_trailing_data: bytes = b""
    sean_trailing_data: bytes = b""
    trailing_data: bytes = b""
