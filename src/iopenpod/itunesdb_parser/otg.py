"""On-The-Go (OTG) playlist parser for iPod devices.

The iPod firmware stores device-created playlists in a separate MHPO binary
file (``OTGPlaylistInfo``) rather than in the iTunesDB.  iTunes and libgpod
both read these files on connect, import the playlists into the database as
regular MHYP entries, and then delete the source file.

Reference: libgpod ``process_OTG_file`` / ``read_OTG_playlists`` in ``src/itdb_itunesdb.c``.

MHPO binary layout (little-endian; big-endian devices use magic ``ohpm``):

  +0x00  magic       4 B   "mhpo" (LE) or "ohpm" (BE)
  +0x04  header_len  u32   size of the header block — always 0x14 (20 B)
  +0x08  entry_len   u32   size of each track entry — always 0x04 (4 B)
  +0x0C  entry_num   u32   number of track entries
  +0x10  (reserved)  4 B   unknown; ignored
  +0x14  entries     entry_num x entry_len bytes
           each entry: u32 = 0-based index into the iTunesDB track list (mhlt)

File naming (all in ``iPod_Control/iTunes/``):
  OTGPlaylistInfo      — first saved OTG playlist
  OTGPlaylistInfo_1    — second saved OTG playlist
  OTGPlaylistInfo_2    — third, etc.

The PC sync manager deletes only the base ``OTGPlaylistInfo`` file after
writing the database.  The iPod firmware removes the numbered variants itself
once it has processed the updated database.
(libgpod comment: "the iPod will remove the remaining files".)
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct

logger = logging.getLogger(__name__)


def load_otg_playlists(itunes_dir: str, track_list: list) -> list[dict]:
    """Parse OTGPlaylistInfo files and return them as regular playlist dicts.

    Each returned dict has the same shape as a playlist produced by
    ``_inline_playlist_strings`` in ``ipod_library.py``:

      ``Title``       — "On-The-Go 1", "On-The-Go 2", …
      ``items``       — list of ``{"track_id": <sequential-id>}`` dicts
      ``playlist_id`` — stable 64-bit ID derived from the file's MD5 so that
                        repeated rescans without an intervening write don't
                        introduce duplicates (same file → same ID)

    Args:
        itunes_dir:  Path to the ``iPod_Control/iTunes`` directory.
        track_list:  Ordered list of track dicts as returned by the iTunesDB
                     parser (``data["mhlt"]``).  Entry indices in the MHPO
                     file are 0-based positions into this list.
    """
    paths = _collect_otg_paths(itunes_dir)
    result: list[dict] = []

    for pl_num, path_str in enumerate(paths, 1):
        playlist = _parse_one_otg_file(path_str, pl_num, track_list)
        if playlist is not None:
            result.append(playlist)

    return result


def delete_otg_files(itunes_dir: str) -> None:
    """Delete the base OTGPlaylistInfo file after a successful database write.

    Matches libgpod's ``itdb_rename_files()`` behaviour: only the base
    ``OTGPlaylistInfo`` file is removed by the PC sync manager.  The iPod
    firmware removes the numbered variants (``OTGPlaylistInfo_1``, ``_2``, …)
    after it processes the new database.
    """
    base = os.path.join(itunes_dir, "OTGPlaylistInfo")
    if not os.path.exists(base):
        return
    try:
        os.unlink(base)
        logger.info("Deleted OTGPlaylistInfo")
    except OSError as exc:
        logger.warning("Could not delete OTGPlaylistInfo: %s", exc)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _collect_otg_paths(itunes_dir: str) -> list[str]:
    """Return the ordered list of OTGPlaylistInfo paths that exist.

    Mirrors libgpod's iteration: start with the base file; if it exists,
    also collect ``_1``, ``_2``, … stopping at the first missing numbered
    file.  If the base file is absent, return an empty list (libgpod comment:
    "only parse if OTGPlaylistInfo exists").
    """
    base = os.path.join(itunes_dir, "OTGPlaylistInfo")
    if not os.path.exists(base):
        return []

    paths = [base]
    for i in range(1, 20):
        p = os.path.join(itunes_dir, f"OTGPlaylistInfo_{i}")
        if not os.path.exists(p):
            break
        paths.append(p)
    return paths


def _parse_one_otg_file(
    path_str: str,
    pl_num: int,
    track_list: list,
) -> dict | None:
    """Parse a single MHPO file and return a playlist dict, or None on failure."""
    try:
        with open(path_str, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        logger.warning("OTG: could not read %s: %s", path_str, exc)
        return None

    if len(raw) < 0x14:
        logger.warning("OTG: %s too short (%d B)", os.path.basename(path_str), len(raw))
        return None

    magic = raw[0:4]
    if magic == b"mhpo":
        fmt = "<I"
    elif magic == b"ohpm":
        fmt = ">I"
    else:
        logger.warning("OTG: %s has unrecognised magic %r — skipping",
                       os.path.basename(path_str), magic)
        return None

    header_len = struct.unpack_from(fmt, raw, 4)[0]
    entry_len = struct.unpack_from(fmt, raw, 8)[0]
    entry_num = struct.unpack_from(fmt, raw, 12)[0]

    if header_len < 0x14:
        logger.warning("OTG: %s header_len %d < 20 — skipping",
                       os.path.basename(path_str), header_len)
        return None
    if entry_len < 4:
        logger.warning("OTG: %s entry_len %d < 4 — skipping",
                       os.path.basename(path_str), entry_len)
        return None

    items: list[dict] = []
    for i in range(entry_num):
        offset = header_len + entry_len * i
        if offset + 4 > len(raw):
            logger.warning("OTG: %s entry %d extends past EOF — truncating",
                           os.path.basename(path_str), i)
            break
        track_index = struct.unpack_from(fmt, raw, offset)[0]
        if track_index >= len(track_list):
            logger.warning(
                "OTG: %s entry %d references track index %d but track list "
                "has only %d entries — skipping entry",
                os.path.basename(path_str), i, track_index, len(track_list),
            )
            continue
        tid = track_list[track_index].get("track_id", 0)
        if tid:
            items.append({"track_id": tid})

    # Consistent with libgpod: don't create a playlist for an empty file.
    if not items:
        return None

    # Stable playlist_id derived from file content so that re-scanning the
    # same OTG file before a sync produces the same ID each time, preventing
    # duplicates in the deduplication step of read_existing_database.
    playlist_id = int.from_bytes(hashlib.md5(raw).digest()[:8], "little")

    name = f"On-The-Go {pl_num}"
    logger.info("OTG: imported '%s' (%d tracks) from %s",
                name, len(items), os.path.basename(path_str))
    return {
        "Title": name,
        "items": items,
        "playlist_id": playlist_id,
    }
