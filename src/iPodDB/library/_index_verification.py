"""Independent checks of native browse order and alphabetical jump groups.

These checks deliberately do not call the index writer or consume its calculated
order. Ties must retain Library order. Untouched noncanonical indexes are retained
only when the values that determine their order are also unchanged.
"""

import unicodedata
from collections.abc import Sequence

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePayload,
)
from iPodDB.library.models import Track


def _text(value: str) -> str:
    prefix, separator, remainder = value.partition(" ")
    if separator and prefix.casefold() in {"a", "an", "the"}:
        value = remainder
    return unicodedata.normalize("NFKD", value).casefold()


def _keys(tracks: Sequence[Track], kind: int) -> tuple[tuple[str | int, ...], ...]:
    result: list[tuple[str | int, ...]] = []
    for track in tracks:
        meta = track.metadata
        title = _text(meta.sort_title or track.title)
        album = _text(meta.sort_album or track.album)
        artist = _text(meta.sort_artist or track.artist)
        album_order = (album, meta.disc_number, track.track_number, title)
        show = _text(meta.sort_show or track.show)
        season, episode = track.season_number, track.episode_number
        key: tuple[str | int, ...]
        match kind:
            case 3:
                key = (title,)
            case 4:
                key = album_order
            case 5:
                key = (artist, *album_order)
            case 7:
                key = (_text(track.genre), artist, *album_order)
            case 0x12:
                key = (_text(meta.sort_composer or meta.composer), *album_order)
            case 0x1D:
                key = (show, season, episode, title)
            case 0x1E:
                key = (season, episode, show, title)
            case 0x1F:
                key = (episode, season, show, title)
            case 0x23:
                key = (
                    _text(
                        meta.sort_album_artist
                        or track.album_artist
                        or meta.sort_artist
                        or track.artist
                    ),
                    *album_order,
                )
            case _:
                raise ValueError(f"Cannot verify library index sort type {kind}.")
        result.append(key)
    return tuple(result)


def _letter(value: str | int) -> int:
    if isinstance(value, int):
        return ord("0")
    for character in value:
        upper = character.upper()[0]
        if character.isalnum() and ord(upper) <= 0xFFFF:
            return ord("0") if character.isdigit() else ord(upper)
    return ord("0")


def verify_index(
    payload: MhodLibraryIndexPayload | MhodLibraryJumpTablePayload,
    kind: int,
    before: tuple[Track, ...],
    desired: tuple[Track, ...],
    *,
    retained: bool,
) -> str | None:
    try:
        keys = _keys(desired, kind)
        if (
            retained
            and tuple(t.track_id for t in before) == tuple(t.track_id for t in desired)
            and _keys(before, kind) == keys
        ):
            return None
    except ValueError as error:
        # Preserve unknown source indexes for edits outside browse dependencies,
        # such as ratings. Any changed browse key or Track order fails closed.
        unchanged_inputs = tuple(t.track_id for t in before) == tuple(
            t.track_id for t in desired
        ) and all(
            _keys(before, sort) == _keys(desired, sort)
            for sort in (3, 4, 5, 7, 0x12, 0x1D, 0x1E, 0x1F, 0x23)
        )
        return None if retained and unchanged_inputs else str(error)
    # Every key for a given kind has the same types in the same positions.
    order = tuple(sorted(range(len(keys)), key=lambda i: (*keys[i], i)))
    if isinstance(payload, MhodLibraryIndexPayload):
        if payload.indices != order:
            return "The library index does not have the required stable browse order."
        return None
    letters = tuple(_letter(keys[i][0]) for i in order)
    cursor = 0
    for entry in payload.entries:
        end = cursor + entry.entry_count
        if entry.start_index != cursor or entry.entry_count <= 0 or end > len(letters):
            return "The library jump table has invalid ranges."
        if any(letter != entry.letter_code for letter in letters[cursor:end]):
            return "The library jump table labels disagree with the sorted Tracks."
        if end < len(letters) and letters[end] == entry.letter_code:
            return "The library jump table splits one alphabetical group."
        cursor = end
    if cursor != len(letters):
        return "The library jump table does not cover the resulting Tracks."
    return None
