"""
iPod Library Loader — standalone parser service, no GUI dependency.

Parses iTunesDB + Play Counts, inlines MHOD strings, converts timestamps
and field values, and returns a flat dict ready for consumption by any
layer (GUI, CLI, sync engine, tests).

Usage::

    from iTunesDB_Parser.ipod_library import load_ipod_library

    data = load_ipod_library("/Volumes/IPOD/iPod_Control/iTunes/iTunesDB")
    tracks = data["mhlt"]        # list[dict]
    albums = data["mhla"]        # list[dict]
    playlists = data["mhlp"]     # list[dict]
"""

import logging
import os
from typing import Optional

from .parser import parse_itunesdb
from iTunesDB_Shared.constants import (
    extract_datasets,
    extract_mhod_strings,
    extract_playlist_extras,
    filetype_to_string,
    sample_rate_to_hz,
)

logger = logging.getLogger(__name__)


def load_ipod_library(itunesdb_path: str,
                      merge_playcounts: bool = True) -> Optional[dict]:
    """Parse an iTunesDB file and return normalised data.

    Args:
        itunesdb_path: Absolute path to the iTunesDB binary file.
        merge_playcounts: If True (default), also read the sibling
            ``Play Counts`` file and merge deltas into the track dicts.

    Returns:
        A dict with keys ``mhlt``, ``mhla``, ``mhlp``, ``mhlp_podcast``,
        ``mhlp_smart``, ``mhsd_type_8``, etc.  Returns ``None`` when the
        file does not exist or cannot be parsed.
    """
    if not itunesdb_path or not os.path.exists(itunesdb_path):
        return None

    try:
        raw = parse_itunesdb(itunesdb_path)
        data = extract_datasets(raw)

        _inline_track_strings(data)
        _inline_album_strings(data)
        _inline_playlist_strings(data)
        _inline_artist_strings(data)

        if merge_playcounts:
            _merge_play_counts(data, itunesdb_path)

        return data
    except Exception as e:
        logger.error("Error parsing iTunesDB: %s", e)
        return None


# ── Internal helpers ────────────────────────────────────────────────────────


def _inline_track_strings(data: dict) -> None:
    for track in data.get("mhlt", []):
        strings = extract_mhod_strings(track.pop("children", []))
        track.update(strings)
        # filetype u32 → ASCII
        ft = track.get("filetype")
        if isinstance(ft, int) and ft > 0:
            track["filetype"] = filetype_to_string(ft)
        # sample_rate 16.16 → Hz
        sr = track.get("sample_rate_1")
        if isinstance(sr, int) and sr > 65535:
            track["sample_rate_1"] = sample_rate_to_hz(sr)


def _inline_album_strings(data: dict) -> None:
    for album in data.get("mhla", []):
        strings = extract_mhod_strings(album.pop("children", []))
        album.update(strings)


def _inline_playlist_strings(data: dict) -> None:
    for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
        for pl in data.get(key, []):
            mhod_children = pl.pop("mhod_children", [])
            strings = extract_mhod_strings(mhod_children)
            pl.update(strings)
            extras = extract_playlist_extras(mhod_children)
            pl.update(extras)
            # Flatten MHIP children → items list
            items = []
            for mhip in pl.pop("mhip_children", []):
                mhip_data = (mhip.get("data", {})
                             if isinstance(mhip, dict) and "data" in mhip
                             else mhip)
                items.append({"track_id": mhip_data.get("track_id", 0)})
            pl["items"] = items


def _inline_artist_strings(data: dict) -> None:
    for artist in data.get("mhsd_type_8", []):
        strings = extract_mhod_strings(artist.pop("children", []))
        artist.update(strings)


def _merge_play_counts(data: dict, itunesdb_path: str) -> None:
    try:
        from .playcounts import parse_playcounts
        from .playcounts import merge_playcounts as _merge

        pc_path = os.path.join(os.path.dirname(itunesdb_path), "Play Counts")
        entries = parse_playcounts(pc_path)
        if entries is not None:
            tracks = data.get("mhlt", [])
            _merge(tracks, entries)
    except Exception as e:
        logger.debug("Play Counts merge skipped: %s", e)
