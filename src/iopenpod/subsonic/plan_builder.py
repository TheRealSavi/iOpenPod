"""Build a ``SyncPlan`` from a Subsonic-compatible server.

Mirrors ``iopenpod.podcasts.podcast_sync.build_podcast_sync_plan``: collect
candidate tracks (here: songs from named playlists), filter out those not
on the iPod, and emit **playlist-only** ``SyncItem``s.  No songs are
downloaded — the Subsonic source is playlist-only, referencing tracks
already in the iPod library by ``db_track_id``.

Selection model (per the approved design): the user chooses which Subsonic
playlists to sync; each playlist's entries are matched (by title+artist)
against the existing iPod library.  Matches become ``db_track_id``
references; non-matches are silently dropped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from iopenpod.sync.contracts import StorageSummary, SyncPlan

if TYPE_CHECKING:
    from .client import SubsonicClient

log = logging.getLogger(__name__)

SUBSONIC_PLAYLIST_SOURCE = "subsonic"

# Transliteration table that folds curly quotes and similar punctuation into
# ASCII equivalents for fuzzy (title, artist) matching.
_PUNCT_MAP = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"}


def _match_key(title: str, artist: str) -> tuple[str, str]:
    """Build a normalized (title, artist) key for fuzzy de-duplication.

    Folds case, strips leading/trailing whitespace, collapses internal
    whitespace, removes punctuation, and transliterates curly quotes to ASCII.
    """

    def _norm(s: str) -> str:
        s = (s or "").translate(_PUNCT_MAP)
        s = s.lower()
        s = "".join(c if (c.isalnum() or c.isspace()) else " " for c in s)
        return " ".join(s.split())

    return (_norm(title), _norm(artist))


def _collect_playlists(
    client: SubsonicClient, playlist_ids: list[str]
) -> list[tuple[str, str, list[dict]]]:
    """Fetch each named playlist's songs.

    Returns a list of ``(playlist_id, playlist_name, songs)`` tuples.
    Fetch failures are logged and skipped.
    """
    result: list[tuple[str, str, list[dict]]] = []
    for pid in playlist_ids:
        pid = (pid or "").strip()
        if not pid:
            continue
        try:
            playlist = client.get_playlist(pid)
        except Exception as exc:
            log.warning("Could not fetch Subsonic playlist %s: %s", pid, exc)
            continue
        name = str(playlist.get("name") or pid)
        entries = list(playlist.get("entry") or [])
        result.append((pid, name, entries))
    return result


def _playlist_id_for(subsonic_id: str, name: str) -> int:
    """Deterministic iPod playlist id from a Subsonic playlist id+name."""
    import hashlib

    key = f"{subsonic_id}\x00{name}".encode("utf-8", errors="surrogatepass")
    suffix = int.from_bytes(hashlib.blake2b(key, digest_size=5).digest(), "big")
    return (0x534F4E << 40) | suffix  # "SON" prefix


def _existing_playlist_items(existing: dict) -> list[dict]:
    """Extract the existing track references from an iPod playlist row."""
    items = existing.get("items") or existing.get("Playlist Items") or []
    result: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        db_id = it.get("db_track_id") or it.get("db_id")
        if db_id:
            result.append({"db_track_id": int(db_id)})
        else:
            tid = it.get("track_id") or it.get("Track ID")
            if tid:
                result.append({"track_id": int(tid)})
    return result


def build_subsonic_sync_plan(
    client: SubsonicClient,
    ipod_tracks: list[dict],
    cache_dir: str,
    *,
    playlist_ids: list[str] | None = None,
    playlist_mappings: dict[str, int] | None = None,
    ipod_playlists: list[dict] | None = None,
) -> SyncPlan:
    """Build a playlist-only ``SyncPlan`` from a Subsonic server.

    No tracks are downloaded — Subsonic sync is purely about organising songs
    already in the iPod library into playlists that mirror the server's
    playlists.  Each Subsonic playlist entry is matched (by title+artist,
    normalised) against the iPod library.  Matches become ``db_track_id``
    references; non-matching entries are silently dropped.

    When ``playlist_mappings`` maps a Subsonic playlist id to an existing
    iPod playlist id, the tracks are merged into that playlist instead of
    creating a new one, preserving the iPod playlist's existing members.

    Args:
        client: An authenticated ``SubsonicClient``.
        ipod_tracks: Parsed track dicts from the iPod library (must carry
            ``Title``, ``Artist``, and ``db_track_id`` fields).
        cache_dir: Transcode-cache dir (reserved).
        playlist_ids: Subsonic playlist ids to sync.
        playlist_mappings: Optional ``{subsonic_id: ipod_playlist_id}`` map.
        ipod_playlists: Existing iPod playlist rows for merging.

    Returns:
        A ``SyncPlan`` with ``playlists_to_add`` (new playlists),
        optional ``playlists_to_edit`` (merged), empty ``to_add``, and
        ``storage``.
    """
    playlist_mappings = playlist_mappings or {}

    # 1. Fetch playlists from the server.
    playlists = _collect_playlists(client, list(playlist_ids or [])) if playlist_ids else []

    # 2. Index existing iPod music tracks by (title, artist) so playlist
    #    entries can be resolved to db_track_ids.  We use _match_key for
    #    fuzzy matching (handles curly quotes, case, punctuation).
    ipod_track_id_by_key: dict[tuple[str, str], int] = {}
    for t in ipod_tracks:
        key = _match_key(t.get("Title") or "", t.get("Artist") or "")
        if key == ("", ""):
            continue
        try:
            db_id = int(t.get("db_track_id") or t.get("db_id") or 0)
        except (TypeError, ValueError):
            db_id = 0
        if db_id:
            ipod_track_id_by_key.setdefault(key, db_id)

    # Index existing iPod playlists for merging.
    ipod_playlist_by_id: dict[int, dict] = {}
    for pl in ipod_playlists or []:
        try:
            pid = int(pl.get("playlist_id") or pl.get("Playlist ID") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid:
            ipod_playlist_by_id.setdefault(pid, pl)

    # 3. Build playlist payloads.  Each playlist entry is matched against
    #    the iPod library; matches resolve to db_track_id, non-matches are
    #    dropped.  No songs are added to the device.
    playlists_to_add: list[dict] = []
    playlists_to_edit: list[dict] = []
    for subsonic_id, name, entries in playlists:
        items: list[dict] = []
        for entry in entries:
            db_id = ipod_track_id_by_key.get(
                _match_key(entry.get("title") or "", entry.get("artist") or "")
            )
            if db_id:
                items.append({"db_track_id": db_id})
        if not items:
            continue

        target_ipod_id = playlist_mappings.get(subsonic_id)
        if target_ipod_id is not None:
            overwrite = target_ipod_id < 0
            abs_id = abs(target_ipod_id)
            if abs_id in ipod_playlist_by_id:
                existing = ipod_playlist_by_id[abs_id]
                existing_items = [] if overwrite else _existing_playlist_items(existing)
                playlists_to_edit.append(
                    {
                        "Title": existing.get("Title") or existing.get("name") or name,
                        "playlist_id": abs_id,
                        "_isNew": False,
                        "_source": SUBSONIC_PLAYLIST_SOURCE,
                        "_mhsd_dataset_type": 2,
                        "_mhsd_result_key": "mhlp",
                        "items": existing_items + items,
                        "mhip_child_count": len(existing_items) + len(items),
                    }
                )
                continue
            # Negative without a matching iPod playlist → fall through to create.
        # Fallback: create a new same-named iPod playlist or overwrite-mode
        # without a matching target.
        playlists_to_add.append(
            {
                "Title": name,
                "playlist_id": _playlist_id_for(subsonic_id, name),
                "_isNew": True,
                "_source": SUBSONIC_PLAYLIST_SOURCE,
                "_mhsd_dataset_type": 2,
                "_mhsd_result_key": "mhlp",
                "items": items,
                "mhip_child_count": len(items),
            }
        )

    log.info(
        "Subsonic plan: %d playlist(s) — %d new, %d merged",
        len(playlists),
        len(playlists_to_add),
        len(playlists_to_edit),
    )

    return SyncPlan(
        to_add=[],
        playlists_to_add=playlists_to_add,
        playlists_to_edit=playlists_to_edit,
        storage=StorageSummary(bytes_to_add=0),
    )
