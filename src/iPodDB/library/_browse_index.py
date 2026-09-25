"""Compute immutable browse-index values during write resolution."""

import unicodedata
from dataclasses import dataclass, replace

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTableEntry,
)
from iPodDB.library.models import Track


def _text(value: str) -> str:
    for article in ("the ", "an ", "a "):
        if value.casefold().startswith(article):
            value = value[len(article) :]
            break
    return unicodedata.normalize("NFKD", value).casefold()


def _key(track: Track, kind: int) -> tuple[str, ...]:
    m = track.metadata
    title, album, artist = (
        _text(m.sort_title or track.title),
        _text(m.sort_album or track.album),
        _text(m.sort_artist or track.artist),
    )
    number = (f"{m.disc_number:020d}", f"{track.track_number:020d}")
    show = _text(m.sort_show or track.show)
    season, episode = f"{track.season_number:020d}", f"{track.episode_number:020d}"
    keys: dict[int, tuple[str, ...]] = {
        3: (title,),
        4: (album, *number, title),
        5: (artist, album, *number, title),
        7: (_text(track.genre), artist, album, *number, title),
        0x12: (_text(m.sort_composer or m.composer), album, *number, title),
        0x1D: (show, season, episode, title),
        0x1E: (season, episode, show, title),
        0x1F: (episode, season, show, title),
        0x23: (
            _text(
                m.sort_album_artist
                or track.album_artist
                or m.sort_artist
                or track.artist
            ),
            album,
            *number,
            title,
        ),
    }
    if kind not in keys:
        raise ValueError(f"Library index sort type {kind} is not understood.")
    return keys[kind]


def _jump(value: str) -> int:
    return next(
        (
            ord(c.upper()[0]) if not c.isdigit() else ord("0")
            for c in value
            if c.isalnum() and ord(c.upper()[0]) <= 0xFFFF
        ),
        ord("0"),
    )


INDEX_KINDS = (3, 4, 5, 7, 0x12, 0x1D, 0x1E, 0x1F, 0x23)


@dataclass(frozen=True, slots=True)
class BrowseIndex:
    sort_type: int
    order: tuple[int, ...]
    jumps: tuple[MhodLibraryJumpTableEntry, ...]
    affected: bool


def resolve_indexes(
    before: tuple[Track, ...], desired: tuple[Track, ...]
) -> tuple[BrowseIndex, ...]:
    result: list[BrowseIndex] = []
    structural = tuple(t.track_id for t in before) != tuple(t.track_id for t in desired)
    for kind in INDEX_KINDS:
        old_keys = tuple(_key(t, kind) for t in before)
        keys = tuple(_key(t, kind) for t in desired)
        order = tuple(sorted(range(len(keys)), key=lambda i: keys[i]))
        entries: list[MhodLibraryJumpTableEntry] = []
        for index, position in enumerate(order):
            letter = _jump(keys[position][0])
            if entries and entries[-1].letter_code == letter:
                entries[-1] = replace(
                    entries[-1], entry_count=entries[-1].entry_count + 1
                )
            else:
                entries.append(
                    MhodLibraryJumpTableEntry(
                        letter_code=letter, start_index=index, entry_count=1
                    )
                )
        result.append(
            BrowseIndex(kind, order, tuple(entries), structural or old_keys != keys)
        )
    return tuple(result)
