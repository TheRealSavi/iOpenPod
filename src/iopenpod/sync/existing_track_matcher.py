"""Existing iPod track matching shared by sync and import planning.

The sync engine has two ways to discover that a PC track already exists on the
device: a persisted mapping entry, or a fingerprint match against a small set
of likely iPod-side candidates. Keep those matching rules together so drop
imports, playlist imports, and full sync agree.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .ipod_track_paths import existing_ipod_track_file_path
from .path_identity import coerce_int, stable_path_key

logger = logging.getLogger(__name__)

DEFAULT_IMPORT_IPOD_MATCH_MIN_SCORE = 70
DEFAULT_IMPORT_IPOD_MATCH_MAX_CANDIDATES = 8
_DIRECT_PATH_MATCH_SCORE = 1000


def score_pc_to_ipod_track(pc_track: Any, ipod_track: dict) -> int:
    """Score how well a PC track's metadata matches an iPod track row."""

    score = 0

    pc_album = _norm_text(getattr(pc_track, "album", ""))
    ip_album = _norm_text(ipod_track.get("Album"))
    if pc_album and ip_album and pc_album == ip_album:
        score += 40

    pc_title = _norm_text(getattr(pc_track, "title", ""))
    ip_title = _norm_text(ipod_track.get("Title"))
    if pc_title and ip_title and pc_title == ip_title:
        score += 30

    pc_artist = _norm_text(getattr(pc_track, "artist", ""))
    ip_artist = _norm_text(ipod_track.get("Artist"))
    if pc_artist and ip_artist and pc_artist == ip_artist:
        score += 25

    pc_track_num = coerce_int(getattr(pc_track, "track_number", 0))
    ip_track_num = coerce_int(ipod_track.get("track_number", 0))
    if pc_track_num > 0 and ip_track_num > 0 and pc_track_num == ip_track_num:
        score += 15

    pc_disc_num = coerce_int(getattr(pc_track, "disc_number", 0))
    ip_disc_num = coerce_int(ipod_track.get("disc_number", 0))
    if pc_disc_num > 0 and ip_disc_num > 0 and pc_disc_num == ip_disc_num:
        score += 8

    pc_year = coerce_int(getattr(pc_track, "year", 0))
    ip_year = coerce_int(ipod_track.get("year", 0))
    if pc_year > 0 and ip_year > 0 and pc_year == ip_year:
        score += 4

    pc_len = coerce_int(getattr(pc_track, "duration_ms", 0))
    ip_len = coerce_int(ipod_track.get("length", 0))
    if pc_len > 0 and ip_len > 0:
        delta = abs(pc_len - ip_len)
        if delta <= 1500:
            score += 12
        elif delta <= 5000:
            score += 7
        elif delta <= 12000:
            score += 3

    pc_bitrate = coerce_int(getattr(pc_track, "bitrate", 0))
    ip_bitrate = coerce_int(ipod_track.get("bitrate", 0))
    if pc_bitrate > 0 and ip_bitrate > 0 and abs(pc_bitrate - ip_bitrate) <= 16:
        score += 3

    pc_sr = coerce_int(getattr(pc_track, "sample_rate", 0))
    ip_sr = coerce_int(ipod_track.get("sample_rate_1", 0))
    if pc_sr > 0 and ip_sr > 0 and abs(pc_sr - ip_sr) <= 1000:
        score += 2

    return score


def mapping_match_db_track_id(
    mapping: Any,
    fingerprint: str,
    valid_db_track_ids: Iterable[int] | None,
) -> int:
    """Return a valid mapped iPod db_track_id for a fingerprint, if present."""

    valid_ids = {coerce_int(db_track_id) for db_track_id in (valid_db_track_ids or ())}
    valid_ids.discard(0)
    for entry in mapping.get_entries(fingerprint):
        db_track_id = _mapping_entry_db_track_id(entry)
        if db_track_id and (not valid_ids or db_track_id in valid_ids):
            return db_track_id
    return 0


def existing_track_match_db_track_id(
    ipod_root: Path,
    ipod_tracks: Iterable[dict],
    pc_track: Any,
    source_path: Path,
    fingerprint: str,
    *,
    mapping: Any | None,
    valid_db_track_ids: Iterable[int] | None = None,
    fpcalc_path: str | None = None,
    fingerprint_cache: dict[str, str | None] | None = None,
) -> int:
    """Resolve whether a PC track already exists on the iPod.

    Mapping entries are authoritative when they still point at a current iPod
    row. Otherwise, fingerprint only the most plausible iPod-side candidates
    instead of scanning the whole device.
    """

    if mapping is not None:
        mapped_db_track_id = mapping_match_db_track_id(
            mapping,
            fingerprint,
            valid_db_track_ids,
        )
        if mapped_db_track_id:
            return mapped_db_track_id

    return candidate_ipod_fingerprint_match_db_track_id(
        ipod_root,
        ipod_tracks,
        pc_track,
        source_path,
        fingerprint,
        fpcalc_path=fpcalc_path,
        fingerprint_cache=fingerprint_cache,
    )


def candidate_ipod_fingerprint_match_db_track_id(
    ipod_root: Path,
    ipod_tracks: Iterable[dict],
    pc_track: Any,
    source_path: Path,
    fingerprint: str,
    *,
    fpcalc_path: str | None,
    fingerprint_cache: dict[str, str | None] | None = None,
    min_score: int = DEFAULT_IMPORT_IPOD_MATCH_MIN_SCORE,
    max_candidates: int = DEFAULT_IMPORT_IPOD_MATCH_MAX_CANDIDATES,
) -> int:
    """Fingerprint likely iPod-side candidates and return the best db_track_id."""

    from . import audio_fingerprint

    cache = fingerprint_cache if fingerprint_cache is not None else {}
    matches: list[tuple[int, dict]] = []
    for db_track_id, ipod_track, ipod_file in ipod_fingerprint_match_candidates(
        ipod_root,
        ipod_tracks,
        pc_track,
        source_path,
        min_score=min_score,
        max_candidates=max_candidates,
    ):
        cache_key = _path_key(ipod_file)
        if cache_key in cache:
            ipod_fingerprint = cache[cache_key]
        else:
            try:
                ipod_fingerprint, _fingerprint_status = (
                    audio_fingerprint.get_or_compute_fingerprint_with_status(
                        ipod_file,
                        fpcalc_path=fpcalc_path,
                        write_to_file=False,
                    )
                )
            except Exception as exc:
                logger.debug(
                    "Could not fingerprint candidate iPod file %s: %s",
                    ipod_file,
                    exc,
                )
                ipod_fingerprint = None
            cache[cache_key] = ipod_fingerprint
        if ipod_fingerprint == fingerprint:
            matches.append((db_track_id, ipod_track))
    return best_ipod_track_match(matches, pc_track)


def ipod_fingerprint_match_candidates(
    ipod_root: Path,
    ipod_tracks: Iterable[dict],
    pc_track: Any,
    source_path: Path,
    *,
    min_score: int = DEFAULT_IMPORT_IPOD_MATCH_MIN_SCORE,
    max_candidates: int = DEFAULT_IMPORT_IPOD_MATCH_MAX_CANDIDATES,
) -> tuple[tuple[int, dict, Path], ...]:
    """Return likely iPod fingerprint candidates ordered by match confidence."""

    source_key = _path_key(source_path)
    scored: list[tuple[int, int, dict, Path]] = []
    for ipod_track in ipod_tracks:
        db_track_id = _ipod_track_db_track_id(ipod_track)
        if not db_track_id:
            continue
        ipod_file = existing_ipod_track_file_path(ipod_root, ipod_track)
        if ipod_file is None:
            continue

        score = score_pc_to_ipod_track(pc_track, ipod_track)
        if _path_key(ipod_file) == source_key:
            score = max(score, _DIRECT_PATH_MATCH_SCORE)
        elif score < min_score:
            continue
        scored.append((score, db_track_id, ipod_track, ipod_file))

    scored.sort(key=lambda row: (-row[0], row[1]))
    bounded = scored[: max(0, max_candidates)]
    if len(scored) > len(bounded):
        logger.debug(
            "Limited iPod fingerprint comparison to %d of %d metadata candidates",
            len(bounded),
            len(scored),
        )
    return tuple(
        (db_track_id, ipod_track, ipod_file)
        for _score, db_track_id, ipod_track, ipod_file in bounded
    )


def best_ipod_track_match(candidates: Iterable[tuple[int, dict]], pc_track: Any) -> int:
    """Select the best iPod row from fingerprint-matched candidates."""

    candidate_list = list(candidates)
    if not candidate_list:
        return 0
    if len(candidate_list) == 1:
        return candidate_list[0][0]
    scored = [
        (score_pc_to_ipod_track(pc_track, ipod_track), db_track_id)
        for db_track_id, ipod_track in candidate_list
    ]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored[0][1]


def _norm_text(value: object) -> str:
    return re.sub(r"\W+", "", str(value or "")).casefold()


def _ipod_track_db_track_id(ipod_track: dict) -> int:
    return coerce_int(ipod_track.get("db_track_id", ipod_track.get("db_id", 0)))


def _mapping_entry_db_track_id(entry: Any) -> int:
    if isinstance(entry, dict):
        return coerce_int(entry.get("db_track_id", entry.get("db_id", 0)))
    return coerce_int(getattr(entry, "db_track_id", 0))


def _path_key(path: Path) -> str:
    try:
        return stable_path_key(path)
    except (TypeError, ValueError, OSError):
        return str(path).strip().casefold()
