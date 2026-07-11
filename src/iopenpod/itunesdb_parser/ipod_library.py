"""
iPod Library Loader — standalone parser service, no GUI dependency.

Parses iTunesDB + Play Counts, inlines MHOD strings, converts timestamps
and field values, and returns a flat dict ready for consumption by any
layer (GUI, CLI, sync engine, tests).

Usage::

    from iopenpod.itunesdb_parser.ipod_library import load_ipod_library

    data = load_ipod_library("/Volumes/IPOD/iPod_Control/iTunes/iTunesDB")
    tracks = data["mhlt"]        # list[dict]
    albums = data["mhla"]        # list[dict]
    playlists = data["mhlp"]     # list[dict]
"""

import logging
import os

from iopenpod.itunesdb_shared.extraction import (
    extract_datasets,
    extract_mhod_strings,
    extract_playlist_extras,
    extract_playlist_item_extras,
    extract_track_extras,
)
from iopenpod.itunesdb_shared.field_base import filetype_to_string

from .parser import parse_itunesdb

logger = logging.getLogger(__name__)


def load_ipod_library(itunesdb_path: str,
                      merge_playcounts: bool = True) -> dict | None:
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
        from .artwork_links import hydrate_track_artwork_refs

        hydrate_track_artwork_refs(data.get("mhlt", []), itunesdb_path)
        _inline_album_strings(data)
        _inline_playlist_strings(data)
        _inline_artist_strings(data)

        if merge_playcounts:
            _merge_play_counts(data, itunesdb_path)

        # Import On-The-Go playlists from OTGPlaylistInfo files.
        # These are device-created playlists stored outside the iTunesDB.
        from .otg import load_otg_playlists
        itunes_dir = os.path.dirname(itunesdb_path)
        otg = load_otg_playlists(itunes_dir, data.get("mhlt", []))
        if otg:
            data.setdefault("mhlp", []).extend(otg)

        return data
    except Exception:
        logger.error("Error parsing iTunesDB", exc_info=True)
        return None


# ── Internal helpers ────────────────────────────────────────────────────────


def _inline_track_strings(data: dict) -> None:
    for track in data.get("mhlt", []):
        children = track.pop("children", [])
        strings = extract_mhod_strings(children)
        track.update(strings)
        track.update(extract_track_extras(children))
        # filetype u32 → ASCII
        ft = track.get("filetype")
        if isinstance(ft, int) and ft > 0:
            track["filetype"] = filetype_to_string(ft)
        # sample_rate_1 is already converted from 16.16 fixed-point to Hz
        # by the read_transform (fixed_to_sample_rate) in mhit_defs.py
        # sort_mhod_indicators raw bytes → list for JSON serialization
        raw = track.get("sort_mhod_indicators", b"")
        if isinstance(raw, (bytes, bytearray)):
            track["sort_mhod_indicators"] = list(raw)


def _inline_album_strings(data: dict) -> None:
    for album in data.get("mhla", []):
        strings = extract_mhod_strings(album.pop("children", []))
        album.update(strings)


def _inline_playlist_strings(data: dict) -> None:
    for key in ("mhlp", "mhlp_podcast", "mhlp_smart"):
        dataset_type = {"mhlp": 2, "mhlp_podcast": 3, "mhlp_smart": 5}[key]
        for pl in data.get(key, []):
            pl.setdefault("_mhsd_dataset_type", dataset_type)
            pl.setdefault("_mhsd_result_key", key)
            mhod_children = pl.pop("mhod_children", [])
            strings = extract_mhod_strings(mhod_children)
            pl.update(strings)
            extras = extract_playlist_extras(mhod_children)
            pl.update(extras)
            # Flatten MHIP children → items list.
            # parse_children always returns {"chunk_type": ..., "data": {...}}.
            items = []
            for mhip in pl.pop("mhip_children", []):
                if "data" in mhip:
                    item = mhip["data"]
                    item.update(extract_playlist_item_extras(item.get("children", [])))
                    items.append(item)
            pl["items"] = items


def _inline_artist_strings(data: dict) -> None:
    for artist in data.get("mhsd_type_8", []):
        strings = extract_mhod_strings(artist.pop("children", []))
        artist.update(strings)


def _merge_play_counts(data: dict, itunesdb_path: str) -> None:
    try:
        from .playcounts import merge_playcounts as _merge
        from .playcounts import parse_playcounts

        pc_path = os.path.join(os.path.dirname(itunesdb_path), "Play Counts")
        entries = parse_playcounts(pc_path)
        if entries is not None:
            tracks = data.get("mhlt", [])
            _merge(tracks, entries)
    except Exception:
        logger.debug("Play Counts merge skipped", exc_info=True)
