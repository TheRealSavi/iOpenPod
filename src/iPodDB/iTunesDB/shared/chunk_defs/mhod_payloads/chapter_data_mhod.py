"""Chapter data MHOD payload definitions."""

from __future__ import annotations

from dataclasses import dataclass
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
    unk_0x08: int = cf(0x08, "be_u32")
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


@dataclass(frozen=True, slots=True)
class MhodChapterDataHedrHeader(BinaryStruct):
    """Final `hedr` atom normally terminating the `sean` children."""

    total_size: int = cf(0x00, "be_u32")
    atom_type: bytes = cf(0x04, "raw", size=4)
    unk_0x08: int = cf(0x08, "be_u32")
    child_count: int = cf(0x0C, "be_u32")
    unk_0x10: int = cf(0x10, "be_u32")
    unk_0x14: int = cf(0x14, "be_u32")
    unk_0x18: int = cf(0x18, "be_u32")


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
