"""Lossless, bounded readers for firmware playback and On-The-Go sidecars.

Format evidence is libgpod's itdb_itunesdb.c. These readers own no paths or I/O.
Raw dates remain raw here; Library projection supplies the Device Time Context.
"""

from __future__ import annotations

import plistlib
import re
import struct
from contextlib import suppress
from typing import cast
from xml.parsers.expat import ExpatError

from iPodDB.shared.diagnostics import log_unknown_data, report_unknown_data
from iPodDB.sidecars.models import (
    OTGPlaylistDocument,
    PlaybackDateKind,
    PlaybackDocument,
    PlaybackEntry,
    PositionalSidecar,
)

MAX_SIDECAR_BYTES = 16 * 1024 * 1024
_U32 = 0xFFFFFFFF


def is_playback_sidecar(name: str) -> bool:
    name = name.casefold()
    return not name.endswith((".bak", ".backup")) and name.startswith(
        ("play counts", "playcounts", "otgplaylist", "on-the-go", "itunesstats")
    )


def otg_number(name: str) -> int | None:
    match = re.fullmatch(r"otgplaylistinfo(?:_([1-9][0-9]*))?", name.casefold())
    if match is None:
        return None
    return int(match[1]) if match[1] else 0


def _bounded(data: bytes) -> None:
    if len(data) > MAX_SIDECAR_BYTES:
        raise ValueError("Playback sidecar exceeds the capture limit.")


@log_unknown_data("positional playback sidecar")
def parse_positional_sidecar(data: bytes) -> PositionalSidecar:
    """Validate framing independently of whether individual fields are known."""
    _bounded(data)
    if len(data) < 16 or data[:4] not in (b"mhdp", b"pdhm", b"mhpo", b"ophm"):
        raise ValueError("Unsupported playback sidecar header.")
    endian = "<" if data[:4] in (b"mhdp", b"mhpo") else ">"
    counts = data[:4] in (b"mhdp", b"pdhm")
    header, width, count = struct.unpack_from(endian + "III", data, 4)
    if header < (96 if counts else 20) or width < (12 if counts else 4):
        raise ValueError("Invalid playback sidecar layout.")
    end = header + width * count
    if end > len(data):
        raise ValueError("Truncated playback sidecar data.")
    if end < len(data):
        report_unknown_data("sidecar suffix", end, len(data) - end)
    return PositionalSidecar(
        bytes(data),
        header,
        width,
        endian,
        tuple(
            data[header + i * width : header + (i + 1) * width] for i in range(count)
        ),
        data[end:],
    )


def _rating(value: int) -> int | None:
    if value == _U32:
        return None
    if not 0 <= value <= 100:
        raise ValueError("Playback rating is outside the 0-100 range.")
    return value


@log_unknown_data("Play Counts")
def parse_play_counts(data: bytes) -> PlaybackDocument:
    table = parse_positional_sidecar(data)
    if data[:4] not in (b"mhdp", b"pdhm"):
        raise ValueError("Play Counts requires an mhdp header.")
    entries: list[PlaybackEntry] = []
    for row in table.rows:

        def value(offset: int, row: bytes = row) -> int:
            return int(struct.unpack_from(table.byte_order + "I", row, offset)[0])

        entries.append(
            PlaybackEntry(
                play_count=value(0),
                last_played=value(4),
                bookmark_time_ms=value(8),
                rating=_rating(value(12)) if len(row) >= 16 else None,
                skip_count=value(20) if len(row) >= 28 else 0,
                last_skipped=value(24) if len(row) >= 28 else 0,
                unknown=(row[12:16] if len(row) < 16 else b"")
                + row[16:20]
                + (row[28:] if len(row) >= 28 else row[20:]),
            )
        )
    return PlaybackDocument(
        bytes(data), tuple(entries), "Play Counts", table.trailing_data
    )


@log_unknown_data("OTGPlaylist")
def parse_otg_playlist(data: bytes) -> OTGPlaylistDocument:
    table = parse_positional_sidecar(data)
    if data[:4] not in (b"mhpo", b"ophm"):
        raise ValueError("On-The-Go Playlist requires an mhpo header.")
    return OTGPlaylistDocument(
        table,
        tuple(
            int(struct.unpack_from(table.byte_order + "I", row)[0])
            for row in table.rows
        ),
    )


def _stats(data: bytes, word: int) -> PlaybackDocument:
    header = word * 2
    minimum = 18 if word == 3 else 32
    if len(data) < header:
        raise ValueError("Truncated iTunesStats header.")
    count = int.from_bytes(data[:word], "little")
    if count > (len(data) - header) // minimum:
        raise ValueError("Truncated iTunesStats entries.")
    entries: list[PlaybackEntry] = []
    offset = header
    for _ in range(count):
        width = int.from_bytes(data[offset : offset + word], "little")
        if width < minimum or offset + width > len(data):
            raise ValueError("Invalid iTunesStats entry length.")
        row = data[offset : offset + width]

        def value(index: int, row: bytes = row) -> int:
            return int.from_bytes(row[index * word : (index + 1) * word], "little")

        entries.append(
            PlaybackEntry(
                play_count=value(4 if word == 3 else 2),
                bookmark_time_ms=value(1),
                last_played=value(3) if word == 4 else 0,
                last_skipped=value(5) if word == 4 else 0,
                skipped=value(5 if word == 3 else 4),
                date_kind=PlaybackDateKind.UNIX,
                unknown=(row[6:12] + row[18:]) if word == 3 else row[24:],
            )
        )
        offset += width
    return PlaybackDocument(
        bytes(data), tuple(entries), f"iTunesStats{word * 8}", data[offset:]
    )


@log_unknown_data("iTunesStats")
def parse_itunes_stats(data: bytes) -> PlaybackDocument:
    """Recognize exactly one fully bounded 24-bit or 32-bit Shuffle layout."""
    _bounded(data)
    matches: list[PlaybackDocument] = []
    for word in (3, 4):
        with suppress(ValueError):
            matches.append(_stats(data, word))
    # An exact layout takes precedence over a candidate that leaves a suffix.
    # If neither is exact, only an unambiguous bounded prefix is interpretable.
    exact = [document for document in matches if not document.trailing_data]
    if exact:
        matches = exact
    if len(matches) != 1:
        raise ValueError("Invalid or ambiguous iTunesStats layout.")
    result = matches[0]
    if result.trailing_data:
        report_unknown_data(
            "iTunesStats suffix",
            len(data) - len(result.trailing_data),
            len(result.trailing_data),
        )
    return result


def parse_play_counts_plist(data: bytes) -> PlaybackDocument:
    _bounded(data)
    if b"<!ENTITY" in data:
        raise ValueError("Entity declarations are not supported in PlayCounts.plist.")
    try:
        root: object = plistlib.loads(data)
    except (ValueError, TypeError, OverflowError, RecursionError, ExpatError) as error:
        raise ValueError("Invalid PlayCounts.plist.") from error
    if not isinstance(root, dict):
        raise ValueError("PlayCounts.plist requires a tracks array.")
    tracks = cast("dict[object, object]", root).get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("PlayCounts.plist requires a tracks array.")
    entries: list[PlaybackEntry] = []
    seen: set[int] = set()
    for record in cast("list[object]", tracks):
        if not isinstance(record, dict):
            raise ValueError("Invalid PlayCounts.plist Track record.")
        item = cast("dict[object, object]", record)

        def integer(
            key: str, maximum: int = _U32, item: dict[object, object] = item
        ) -> int:
            value = item.get(key, 0)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"Invalid PlayCounts.plist {key}.")
            return value

        raw_identity = item.get("persistentID", 0)
        if type(raw_identity) is not int or not -(1 << 63) <= raw_identity < (1 << 64):
            raise ValueError("Invalid PlayCounts.plist persistentID.")
        # Some plist producers expose the same 64-bit identifier as signed.
        identity = raw_identity & ((1 << 64) - 1)
        if not identity or identity in seen:
            raise ValueError("Missing or duplicate PlayCounts.plist persistentID.")
        seen.add(identity)
        rating = integer("userRating")
        entries.append(
            PlaybackEntry(
                persistent_id=identity,
                play_count=integer("playCount"),
                last_played=integer("playMacOSDate"),
                bookmark_time_ms=integer("bookmarkTimeInMS"),
                rating=_rating(rating) if rating else None,
                skip_count=integer("skipCount"),
                last_skipped=integer("skipMacOSDate"),
            )
        )
    return PlaybackDocument(bytes(data), tuple(entries), "PlayCounts.plist")


def parse_playback(name: str, data: bytes) -> PlaybackDocument:
    match name.casefold():
        case "play counts":
            return parse_play_counts(data)
        case "itunesstats":
            return parse_itunes_stats(data)
        case "playcounts.plist":
            return parse_play_counts_plist(data)
        case _:
            raise ValueError(f"Unsupported playback sidecar: {name}.")
