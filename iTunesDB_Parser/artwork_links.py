"""Helpers for reconciling track artwork links with ArtworkDB.

Older iPod database versions can omit the MHIT ``artwork_id_ref`` field even
when the track has album art. In those databases the reliable link lives in
ArtworkDB's MHII ``songId`` field, which equals the track ``db_track_id``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _artworkdb_path_from_itunesdb(itunesdb_path: str | Path) -> Path:
    itunes_path = Path(itunesdb_path)
    ipod_control = itunes_path.parent.parent
    return ipod_control / "Artwork" / "ArtworkDB"


def _build_song_to_artwork_id(artworkdb_path: Path) -> dict[int, int]:
    if not artworkdb_path.exists():
        return {}

    try:
        from ArtworkDB_Parser.parser import parse_artworkdb

        artworkdb = parse_artworkdb(str(artworkdb_path))
    except Exception as exc:
        logger.debug("Could not parse ArtworkDB for artwork links: %s", exc)
        return {}

    links: dict[int, int] = {}
    for entry in artworkdb.get("mhli", []):
        if not isinstance(entry, dict):
            continue
        try:
            song_id = int(entry.get("songId") or entry.get("song_id") or 0)
            img_id = int(entry.get("img_id") or 0)
        except (TypeError, ValueError):
            continue
        if song_id and img_id:
            links.setdefault(song_id, img_id)
    return links


def hydrate_track_artwork_refs(
    tracks: list[dict[str, Any]],
    itunesdb_path: str | Path,
) -> int:
    """Fill missing ``artwork_id_ref`` values from ArtworkDB ``songId`` links.

    Returns the number of tracks updated.
    """
    if not tracks:
        return 0

    song_to_artwork_id = _build_song_to_artwork_id(
        _artworkdb_path_from_itunesdb(itunesdb_path)
    )
    if not song_to_artwork_id:
        return 0

    hydrated = 0
    for track in tracks:
        if not isinstance(track, dict):
            continue
        if track.get("artwork_id_ref") not in (None, "", 0):
            continue
        try:
            db_track_id = int(track.get("db_track_id") or track.get("db_id") or 0)
        except (TypeError, ValueError):
            continue
        artwork_id = song_to_artwork_id.get(db_track_id)
        if not artwork_id:
            continue
        track["artwork_id_ref"] = artwork_id
        if track.get("mhii_link") in (None, "", 0):
            track["mhii_link"] = artwork_id
        if not track.get("artwork_count"):
            track["artwork_count"] = 1
        hydrated += 1

    if hydrated:
        logger.info("Hydrated %d track artwork refs from ArtworkDB song links", hydrated)
    return hydrated
