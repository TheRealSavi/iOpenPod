"""
Play Counts file parser for iPod.

The iPod firmware does NOT modify the iTunesDB directly.  Instead it creates
a separate binary file at ``/iPod_Control/iTunes/Play Counts`` that records
per-track deltas (play count, skip count, rating, timestamps) accumulated
since the last sync.

File layout (iTunes 7+ / entry_length 0x1C):

    Header  (``mhdp``)
    ┌─────────────┬────────────────────┐
    │ 0x00  4B    │ magic  "mhdp"      │
    │ 0x04  4B    │ header_length      │
    │ 0x08  4B    │ entry_length       │
    │ 0x0C  4B    │ entry_count        │
    │ 0x10 …      │ padding → header_length │
    └─────────────┴────────────────────┘

    Per-entry  (28 bytes for entry_length == 0x1C)
    ┌─────────────┬────────────────────┐
    │ 0x00  4B    │ play_count         │
    │ 0x04  4B    │ last_played (Mac)  │
    │ 0x08  4B    │ bookmark_time      │
    │ 0x0C  4B    │ rating (0-100)     │
    │ 0x10  4B    │ unk16 / podcast    │
    │ 0x14  4B    │ skip_count         │
    │ 0x18  4B    │ last_skipped (Mac) │
    └─────────────┴────────────────────┘

Entries are ordered 1:1 with tracks in the mhlt (matched by index, **not**
by track ID).  After a sync tool reads this file and folds the deltas into
the iTunesDB, the file must be **deleted** so the iPod creates a fresh one.

Reference: libgpod ``itdb_itunesdb.c`` → ``playcounts_read()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ._parsing import UINT32_LE
from iTunesDB_Shared.field_base import MAC_EPOCH_OFFSET

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlayCountEntry:
    """Delta values for a single track from the Play Counts file."""

    play_count: int = 0
    last_played: int = 0        # Mac timestamp (0 = not played)
    bookmark_time: int = 0
    rating: int = -1            # -1 = no change; 0-100 = new rating
    skip_count: int = 0
    last_skipped: int = 0       # Mac timestamp (0 = not skipped)

    # Convenience: is there any delta data in this entry?
    @property
    def has_data(self) -> bool:
        return (
            self.play_count > 0
            or self.skip_count > 0
            or self.rating >= 0
        )

    @property
    def last_played_unix(self) -> int:
        """Last-played as Unix timestamp (0 if never played)."""
        if self.last_played == 0:
            return 0
        return self.last_played - MAC_EPOCH_OFFSET

    @property
    def last_skipped_unix(self) -> int:
        """Last-skipped as Unix timestamp (0 if never skipped)."""
        if self.last_skipped == 0:
            return 0
        return self.last_skipped - MAC_EPOCH_OFFSET


def parse_playcounts(path: str | Path) -> Optional[list[PlayCountEntry]]:
    """
    Parse an iPod Play Counts file.

    Args:
        path: Path to the ``Play Counts`` file.

    Returns:
        List of :class:`PlayCountEntry` (one per track, ordered by mhlt
        index), or ``None`` if the file doesn't exist or can't be parsed.
    """
    path = Path(path)
    if not path.exists():
        logger.debug("No Play Counts file at %s", path)
        return None

    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("Could not read Play Counts file: %s", exc)
        return None

    if len(data) < 16:
        logger.warning("Play Counts file too small (%d bytes)", len(data))
        return None

    magic = data[0:4]
    if magic != b"mhdp":
        logger.warning("Play Counts file bad magic: %r (expected b'mhdp')", magic)
        return None

    header_len = UINT32_LE.unpack_from(data, 4)[0]
    entry_len = UINT32_LE.unpack_from(data, 8)[0]
    entry_count = UINT32_LE.unpack_from(data, 12)[0]

    expected_size = header_len + entry_len * entry_count
    if len(data) < expected_size:
        logger.warning(
            "Play Counts file truncated: %d bytes < expected %d",
            len(data), expected_size,
        )
        return None

    logger.info(
        "Play Counts: header=%d, entry_len=%d, entries=%d",
        header_len, entry_len, entry_count,
    )

    entries: list[PlayCountEntry] = []
    for i in range(entry_count):
        offset = header_len + i * entry_len
        entry = PlayCountEntry()

        # Minimum fields (always present)
        entry.play_count = UINT32_LE.unpack_from(data, offset)[0]

        if entry_len >= 8:
            entry.last_played = UINT32_LE.unpack_from(data, offset + 4)[0]

        if entry_len >= 12:
            entry.bookmark_time = UINT32_LE.unpack_from(data, offset + 8)[0]

        if entry_len >= 16:
            raw_rating = UINT32_LE.unpack_from(data, offset + 12)[0]
            # Convention: rating=0 in the Play Counts file means "no change"
            # when the track had no user interaction.  The iPod firmware
            # initialises all entries to zero.  We treat 0 as "unchanged"
            # to avoid accidentally clearing ratings set on the PC.
            #
            # Ratings 20-100 (1-5 stars) are genuine user-set values.
            # A user *removing* a rating on the iPod is indistinguishable
            # from "no interaction" — this is a known limitation shared
            # with libgpod (which checks ``rating != NO_PLAYCOUNT (-1)``
            # but the firmware never writes -1).
            if raw_rating > 0:
                entry.rating = raw_rating
            # else: stays -1 (no change)

        # entry_len >= 20: unk16 / podcast flag — skipped

        if entry_len >= 24:
            entry.skip_count = UINT32_LE.unpack_from(data, offset + 20)[0]

        if entry_len >= 28:
            entry.last_skipped = UINT32_LE.unpack_from(data, offset + 24)[0]

        entries.append(entry)

    active = sum(1 for e in entries if e.has_data)
    logger.info("Play Counts: %d / %d entries have activity", active, entry_count)
    return entries


def merge_playcounts(
    tracks: list[dict],
    entries: list[PlayCountEntry],
) -> None:
    """
    Fold Play Counts deltas into parsed track dicts **in place**.

    After calling this:

    - ``track["play_count_1"]`` is the **new cumulative** play count
    - ``track["skip_count"]`` is the **new cumulative** skip count
    - ``track["recent_playcount"]`` is the delta from this session
    - ``track["recent_skipcount"]`` is the delta from this session
    - ``track["rating"]`` may be updated if the user rated on the iPod
    - ``track["last_played"]`` / ``track["last_skipped"]`` may be updated

    This mirrors libgpod's ``get_mhit()`` merge logic.
    """
    count = min(len(tracks), len(entries))
    if len(tracks) != len(entries):
        logger.warning(
            "Track count (%d) != Play Counts entry count (%d); "
            "merging first %d",
            len(tracks), len(entries), count,
        )

    merged_plays = 0
    merged_skips = 0
    merged_ratings = 0

    for i in range(count):
        track = tracks[i]
        entry = entries[i]

        # --- Play count (additive) ---
        track["recent_playcount"] = entry.play_count
        track["play_count_1"] = track.get("play_count_1", 0) + entry.play_count
        if entry.play_count > 0:
            merged_plays += 1

        # --- Skip count (additive) ---
        track["recent_skipcount"] = entry.skip_count
        track["skip_count"] = track.get("skip_count", 0) + entry.skip_count
        if entry.skip_count > 0:
            merged_skips += 1

        # --- Rating (override if changed) ---
        if entry.rating >= 0:  # -1 = no change
            old_rating = track.get("rating", 0)
            if old_rating != entry.rating:
                track["app_rating"] = old_rating  # backup (libgpod convention)
                track["rating"] = entry.rating
                merged_ratings += 1

        # --- Bookmark (override — iPod always has the latest position) ---
        if entry.bookmark_time > 0:
            track["bookmark_time"] = entry.bookmark_time

        # --- Timestamps (use more-recent value) ---
        # IMPORTANT: track["last_played"] is a Unix timestamp (converted by
        # _load_data from Mac), but entry.last_played is a raw Mac timestamp.
        # Use the .last_played_unix / .last_skipped_unix properties to
        # compare in the same unit and avoid double-conversion downstream.
        if entry.last_played > 0:
            unix_ts = entry.last_played_unix
            if unix_ts > track.get("last_played", 0):
                track["last_played"] = unix_ts

        if entry.last_skipped > 0:
            unix_ts = entry.last_skipped_unix
            if unix_ts > track.get("last_skipped", 0):
                track["last_skipped"] = unix_ts

    # Tracks beyond the Play Counts entries get zero deltas
    for i in range(count, len(tracks)):
        tracks[i]["recent_playcount"] = 0
        tracks[i]["recent_skipcount"] = 0

    logger.info(
        "Merged Play Counts: %d plays, %d skips, %d ratings across %d tracks",
        merged_plays, merged_skips, merged_ratings, count,
    )
