"""Read-only Classic 120GB 2.0.1 Chapter interpretation, separate from metadata.

These observations describe the traced firmware, not a capability declaration for
every iPod. Retained Chapters are never sorted, filtered, or rewritten by this view.
"""

from dataclasses import dataclass
from itertools import pairwise

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    ChapterDataFlags,
    MhodChapterDataPayload,
)


def _validated_position(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 0xFFFFFFFF
    ):
        raise ValueError("Position must be an unsigned 32-bit millisecond value")
    return value


@dataclass(frozen=True, slots=True)
class NativeChapterEntry:
    """One indexed `chap`, with its one-based ordinal among the stored Chapters."""

    chapter_ordinal: int
    title: str
    raw_start_ms: int

    @property
    def start_ms(self) -> int:
        return 0 if self.raw_start_ms == 1 else self.raw_start_ms


@dataclass(frozen=True, slots=True)
class NativeChapterIndex:
    """Native named index and diagnostic codes; editable metadata stays separate."""

    flags: int | None
    entries: tuple[NativeChapterEntry, ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def chapter_artwork_eligible(self) -> bool:
        """Known provider gates only; this does not guarantee image delivery."""
        return bool(
            self.entries
            and self.flags is not None
            and self.flags & ChapterDataFlags.HAS_CHAPTER_ARTWORK
        )

    def index_at(self, position_ms: int) -> int:
        """Scan stored order until the first future start, or return -1."""
        position_ms = _validated_position(position_ms)
        index = -1
        for candidate, chapter in enumerate(self.entries):
            if chapter.start_ms > position_ms:
                break
            index = candidate
        return index


def interpret_native_chapters(payload: MhodChapterDataPayload) -> NativeChapterIndex:
    """Interpret the encoded shape, including pending newly authored name atoms."""
    # The lossless parser exposes the last hedr and retains earlier duplicates
    # as raw atoms, whereas firmware reads the first. Do not infer the first
    # header's flags from that last-header projection.
    duplicate_header = any(atom.atom_type == b"hedr" for atom in payload.other_atoms)
    flags = (
        payload.hedr.unk_0x18
        if payload.hedr is not None and not duplicate_header
        else None
    )
    named = tuple(
        NativeChapterEntry(index + 1, chapter.name, chapter.start_pos_ms)
        for index, chapter in enumerate(payload.chapters)
        if chapter.name_header is not None or chapter.name
    )
    diagnostics: list[str] = []
    if duplicate_header:
        diagnostics.append("duplicate_header")
    elif payload.chapters and flags is None:
        diagnostics.append("missing_header")
    elif named and not (flags or 0) & ChapterDataFlags.HAS_NAMED_CHAPTERS:
        diagnostics.append("navigation_disabled")
    if len(named) != len(payload.chapters):
        diagnostics.append("unnamed_chapters")
    starts = tuple(chapter.start_ms for chapter in named)
    if any(left > right for left, right in pairwise(starts)):
        diagnostics.append("unordered_starts")
    if len(starts) != len(set(starts)):
        diagnostics.append("duplicate_starts")
    entries = named if (flags or 0) & ChapterDataFlags.HAS_NAMED_CHAPTERS else ()
    return NativeChapterIndex(flags, entries, tuple(diagnostics))
