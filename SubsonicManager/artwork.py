"""Cover-art handling for the Subsonic source.

Two concerns:

1. Navidrome (and some other servers) serve a static placeholder image for
   *every* album's cover art, even albums with no real cover.  A non-empty
   ``coverArt`` id therefore does not imply real artwork.  We detect the
   placeholder at connect time by hashing the response to an empty
   ``getCoverArt`` id and comparing later covers against it (lightweight
   version of podkit's ``subsonic/cache.ts`` placeholder probe).

2. Computing an ``art_hash`` (MD5) for a Subsonic cover so the sync plan can
   report artwork presence; the actual bytes are re-extracted from the
   downloaded file by the standard ArtworkDB pipeline at write time.
"""

from __future__ import annotations

import logging

from ArtworkDB_Writer.art_extractor import art_hash

from .client import SubsonicClient, SubsonicConnectionError

log = logging.getLogger(__name__)

# Covers smaller than this are almost certainly not real artwork.
_MIN_ARTWORK_BYTES = 100


def detect_placeholder_cover(client: SubsonicClient) -> str | None:
    """Probe the server for a Navidrome-style placeholder cover.

    Requests ``getCoverArt`` with an empty id.  If the server returns a
    real image, its MD5 is cached on ``client.placeholder_cover_hash`` and
    also returned, so callers can later treat matching covers as "no real
    artwork".  Servers that 404/error (Gonic) yield ``None`` and disable
    placeholder filtering.

    Safe to ignore failures — worst case we just don't filter placeholders.
    """
    try:
        # Empty id: Navidrome returns its placeholder; Gonic errors out.
        bytes_ = client.get_cover_art_bytes("")
    except SubsonicConnectionError:
        client.placeholder_cover_hash = None
        return None
    except Exception as exc:  # HTTP errors from raise_for_status, etc.
        log.debug("Placeholder cover probe failed: %s", exc)
        client.placeholder_cover_hash = None
        return None

    if not bytes_ or len(bytes_) < _MIN_ARTWORK_BYTES:
        client.placeholder_cover_hash = None
        return None

    digest = art_hash(bytes_)
    client.placeholder_cover_hash = digest
    log.debug("Detected Subsonic placeholder cover hash %s", digest)
    return digest


def classify_cover(
    client: SubsonicClient,
    cover_art_id: str | None,
) -> tuple[bool, str | None]:
    """Determine whether a song has real artwork.

    Returns ``(has_artwork, art_hash)``.  ``has_artwork`` is True only when a
    cover id is present and the fetched bytes are a real image (not the
    server's placeholder).  ``art_hash`` is the MD5 of the cover bytes when
    real, else None.

    When ``client.placeholder_cover_hash`` is None (placeholder detection
    disabled or unsupported) we cannot reliably tell, so we return
    ``(True, None)`` for any present cover id — meaning "assume real, hash
    unknown" — which matches podkit's flag-off behaviour.
    """
    if not cover_art_id:
        return (False, None)

    try:
        bytes_ = client.get_cover_art_bytes(cover_art_id)
    except Exception as exc:
        log.debug("Cover art fetch failed for %s: %s", cover_art_id, exc)
        # If placeholder detection is off we can't classify; be optimistic.
        return (True, None) if client.placeholder_cover_hash is None else (False, None)

    if not bytes_ or len(bytes_) < _MIN_ARTWORK_BYTES:
        return (False, None)

    digest = art_hash(bytes_)
    if client.placeholder_cover_hash and digest == client.placeholder_cover_hash:
        return (False, None)
    return (True, digest)
