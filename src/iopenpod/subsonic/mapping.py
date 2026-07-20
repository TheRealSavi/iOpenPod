"""Map OpenSubsonic song dicts into iOpenPod's ``PCTrack`` domain model.

Mirrors podkit's ``mapSongToTrack`` (``adapters/subsonic.ts``), adapted to
the field set of ``iopenpod.sync.pc_library.PCTrack``.  A song's ``path`` is
set to the virtual URI ``subsonic://<track_id>``; the executor's fetch
phase (``_fetch_subsonic_tracks``) recognises this scheme and replaces it
with a real local cache path before the track is copied to the device.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from iopenpod.sync._formats import IPOD_NATIVE_AUDIO
from iopenpod.sync.pc_library import PCTrack

log = logging.getLogger(__name__)

# IPOD_NATIVE_AUDIO is imported from the canonical SyncEngine._formats module
# to avoid a divergent duplicate set (see iopenpod/sync/_formats.py).


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def song_to_pc_track(
    song: dict,
    *,
    album: dict | None = None,
    check_artwork: bool = False,
    client: Any = None,
) -> PCTrack:
    """Convert an OpenSubsonic song dict into a ``PCTrack``.

    Args:
        song: A ``Child`` (song) dict from ``getStarred2``/``getPlaylist``/
            ``getAlbum``.  Fields follow OpenSubsonic naming (title, artist,
            album, suffix, duration, bitRate, track, discNumber, ...).
        album: Optional parent album dict (``AlbumWithSongsID3``) used to fill
            gaps (albumArtist, genre, year, isCompilation).
        check_artwork: When True and ``client`` is provided, probe the cover
            via :func:`iopenpod.subsonic.artwork.classify_cover` to set
            ``art_hash``.  When False, ``art_hash`` is left None and resolved
            later from the downloaded file (matches podcast behaviour).
        client: ``SubsonicClient`` used for the artwork probe.

    Returns:
        A ``PCTrack`` with all required fields populated.  ``path`` is the
        virtual ``subsonic://<track_id>`` URI pending execution-time download.
    """
    album = album or {}
    track_id = _as_str(song.get("id"))
    suffix = _as_str(song.get("suffix")).lower()
    ext = f".{suffix}" if suffix else ""

    title = _as_str(song.get("title"), "Unknown Title")
    artist = _as_str(song.get("artist") or album.get("artist"), "Unknown Artist")
    album_name = _as_str(song.get("album") or album.get("name"), "Unknown Album")
    album_artist = song.get("albumArtist") or album.get("artist")
    genre = song.get("genre") or album.get("genre")
    year = _as_int(song.get("year") or album.get("year")) or None

    # OpenSubsonic durations are whole seconds; PCTrack uses milliseconds.
    duration_ms = _as_int(song.get("duration")) * 1000
    bitrate = _as_int(song.get("bitRate")) or None
    size = _as_int(song.get("size"))
    sample_rate = _as_int(song.get("sampleRate")) or None

    track_number = _as_int(song.get("track")) or None
    track_total = _as_int(song.get("trackCount")) or None
    disc_number = _as_int(song.get("discNumber")) or None
    disc_total = _as_int(song.get("discCount")) or None

    # Optional artwork hash when explicitly probing (otherwise resolved later).
    art_hash: str | None = None
    if check_artwork and client is not None:
        try:
            from .artwork import classify_cover

            _, art_hash = classify_cover(client, song.get("coverArt"))
        except Exception as exc:  # artwork failures must never break the track
            log.debug("Artwork probe failed for track %s: %s", track_id, exc)

    needs_transcoding = bool(ext) and ext not in IPOD_NATIVE_AUDIO

    return PCTrack(
        # File info — path is virtual until the fetch phase downloads it.
        path=f"subsonic://{track_id}",
        relative_path=f"{track_id}{ext}",
        filename=f"{track_id}{ext}",
        extension=ext,
        mtime=time.time(),
        size=size,
        # Metadata
        title=title,
        artist=artist,
        album=album_name,
        album_artist=album_artist or None,
        genre=genre or None,
        year=year,
        track_number=track_number,
        track_total=track_total,
        disc_number=disc_number,
        disc_total=disc_total,
        duration_ms=duration_ms,
        bitrate=bitrate,
        sample_rate=sample_rate,
        rating=None,
        # Derived flags
        compilation=bool(album.get("isCompilation")),
        needs_transcoding=needs_transcoding,
        art_hash=art_hash,
    )
