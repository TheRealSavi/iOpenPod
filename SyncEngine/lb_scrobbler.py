"""
Scrobbling support for ListenBrainz.

Scrobbling records what you've listened to on your iPod.  After syncing
play counts from the iPod, this module submits the plays to ListenBrainz.

API reference:
  https://listenbrainz.readthedocs.io/en/latest/users/api/core.html
JSON payload docs:
  https://listenbrainz.readthedocs.io/en/latest/users/json.html

Key ListenBrainz constraints (from the API constants):
  MAX_LISTENS_PER_REQUEST  = 1000
  MAX_LISTEN_SIZE          = 10240 bytes
  MAX_LISTEN_PAYLOAD_SIZE  = 10240000 bytes
  LISTEN_MINIMUM_TS        = 1033430400  (2002-10-01)

Scrobbling rules (per LB docs):
  - Submit a listen when the user has listened to >4 min or >50% of the
    track, whichever is lower.
  - Tracks shorter than 30 s are not scrobbled (widely adopted convention).
  - `listened_at` must be a UTC Unix epoch ≥ LISTEN_MINIMUM_TS.
  - Only submit new plays (deltas from the iPod Play Counts file).
  - For multiple plays of the same track, space timestamps backwards from
    `last_played` by `track_duration` per play.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── ListenBrainz constants ──────────────────────────────────────────────────


LISTENBRAINZ_API_ROOT = "https://api.listenbrainz.org"

# Submission client identity — included in every listen payload so
# ListenBrainz can attribute the source.
SUBMISSION_CLIENT = "iOpenPod"
SUBMISSION_CLIENT_VERSION = "1.0.0"
MEDIA_PLAYER = "iPod"
IMPORT_SERVICE = "iopenpod"

# The minimum acceptable value for listened_at (from LB source).
LISTEN_MINIMUM_TS = 1033430400  # 2002-10-01 00:00:00 UTC

# Conservative batch size.  The API allows up to 1 000 per request but
# smaller batches are friendlier to rate limits and reduce the blast
# radius of a single failed request.
BATCH_SIZE = 500

# Minimum track length to scrobble (widely adopted convention).
MIN_SCROBBLE_DURATION_MS = 30_000

# Maximum retries when we hit a 429 (Too Many Requests) response.
MAX_RATE_LIMIT_RETRIES = 5

# Default headers sent with every request.
_BASE_HEADERS = {
    "User-Agent": f"{SUBMISSION_CLIENT}/{SUBMISSION_CLIENT_VERSION}",
    "Content-Type": "application/json",
}


# ── Data ────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ScrobbleEntry:
    """One play of one track to be scrobbled."""

    artist: str
    track: str
    album: str
    duration_secs: int          # Track duration in seconds
    timestamp: int              # Unix epoch when the play occurred
    track_number: int = 0       # Optional
    album_artist: str = ""      # Optional
    genre: str = ""             # Optional — sent as a tag
    disc_number: int = 0        # Optional
    isrc: str = ""              # Optional — ISRC code if available
    recording_mbid: str = ""    # Optional — MusicBrainz Recording ID


@dataclass(slots=True)
class ScrobbleResult:
    """Summary of a scrobble submission batch."""

    service: str = "listenbrainz"
    submitted: int = 0
    accepted: int = 0
    ignored: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RateLimitInfo:
    """Parsed rate-limit headers from a ListenBrainz response."""

    limit: int = 0
    remaining: int = 0
    reset_in: float = 0.0  # seconds until the window resets

    @classmethod
    def from_headers(cls, headers) -> RateLimitInfo:
        """Parse X-RateLimit-* headers from an HTTP response."""
        def _int(name: str) -> int:
            try:
                return int(headers.get(name, 0))
            except (TypeError, ValueError):
                return 0

        def _float(name: str) -> float:
            try:
                return float(headers.get(name, 0))
            except (TypeError, ValueError):
                return 0.0

        return cls(
            limit=_int("X-RateLimit-Limit"),
            remaining=_int("X-RateLimit-Remaining"),
            reset_in=_float("X-RateLimit-Reset-In"),
        )


class ScrobbleAborted(Exception):
    """Raised when the user chooses to stop retrying scrobbles."""


def _sleep_with_abort(
    seconds: float,
    should_abort: Callable[[], bool] | None = None,
) -> None:
    """Sleep in short increments so cancellation remains responsive."""
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        if should_abort and should_abort():
            raise ScrobbleAborted("User gave up while connecting to ListenBrainz")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.25))


def _is_timeout_error(exc: BaseException) -> bool:
    """Return True when an exception represents a network timeout."""
    if isinstance(exc, TimeoutError | socket.timeout):
        return True

    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError | socket.timeout):
            return True
        text = str(reason).lower()
        return "timed out" in text or "timeout" in text

    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


# ── Low-level HTTP helpers ──────────────────────────────────────────────────

def _make_request(
    method: str,
    path: str,
    token: str = "",
    body: bytes | None = None,
    params: dict[str, str] | None = None,
    timeout: int = 30,
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> tuple[dict, RateLimitInfo]:
    """Send an HTTP request to the ListenBrainz API.

    Handles 429 (Too Many Requests) automatically by sleeping for the
    duration indicated in the `X-RateLimit-Reset-In` header and
    retrying up to `MAX_RATE_LIMIT_RETRIES` times.

    Returns:
        (json_body, rate_limit_info)

    Raises:
        urllib.error.HTTPError: on non-retryable HTTP errors.
        urllib.error.URLError: on network errors.
    """
    url = f"{LISTENBRAINZ_API_ROOT}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    rate_limit_attempt = 0
    timeout_attempt = 0
    timeout_start = time.monotonic()

    while True:
        if should_abort and should_abort():
            raise ScrobbleAborted("User gave up while connecting to ListenBrainz")

        req = urllib.request.Request(url, data=body, method=method)
        for k, v in _BASE_HEADERS.items():
            req.add_header(k, v)
        if token:
            req.add_header("Authorization", f"Token {token}")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                rl = RateLimitInfo.from_headers(resp.headers)
                data = json.loads(resp.read().decode("utf-8"))
                return data, rl

        except urllib.error.HTTPError as exc:
            rl = RateLimitInfo.from_headers(exc.headers)
            if exc.code == 429:
                rate_limit_attempt += 1
            if exc.code == 429 and rate_limit_attempt < MAX_RATE_LIMIT_RETRIES:
                wait = max(rl.reset_in, 1.0)
                logger.warning(
                    "ListenBrainz 429 rate-limited; sleeping %.1fs (attempt %d/%d)",
                    wait, rate_limit_attempt, MAX_RATE_LIMIT_RETRIES,
                )
                _sleep_with_abort(wait, should_abort)
                continue
            raise

        except Exception as exc:
            if _is_timeout_error(exc):
                timeout_attempt += 1
                elapsed = time.monotonic() - timeout_start
                if on_timeout:
                    on_timeout(elapsed, timeout_attempt, timeout)
                logger.warning(
                    "ListenBrainz request timed out after %ds (attempt %d, %.1fs elapsed)",
                    timeout,
                    timeout_attempt,
                    elapsed,
                )
                # Keep trying until the user gives up.
                continue
            raise

    # Should not reach here, but satisfy the type checker.
    raise RuntimeError("Exhausted rate-limit retries")


# ── Public API: token validation ────────────────────────────────────────────

def listenbrainz_validate_token(token: str) -> str | None:
    """Validate a ListenBrainz user token.

    Returns:
        The username if valid, `None` otherwise.
    """
    try:
        data, _rl = _make_request("GET", "/1/validate-token", token=token, timeout=15)
        if data.get("valid"):
            return data.get("user_name", "")
    except Exception as exc:
        logger.error("ListenBrainz token validation failed: %s", exc)
    return None


# ── Public API: latest-import tracking ──────────────────────────────────────

def get_latest_import(
    username: str,
    token: str = "",
    service: str = IMPORT_SERVICE,
    *,
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Get the Unix timestamp of the newest listen previously imported.

    Returns 0 if the user has never imported.
    """
    try:
        data, _rl = _make_request(
            "GET", "/1/latest-import",
            token=token,
            params={"user_name": username, "service": service},
            timeout=15,
            on_timeout=on_timeout,
            should_abort=should_abort,
        )
        return int(data.get("latest_import", 0))
    except ScrobbleAborted:
        raise
    except Exception as exc:
        logger.warning("Failed to get latest import timestamp: %s", exc)
        return 0


def set_latest_import(
    ts: int,
    token: str,
    service: str = IMPORT_SERVICE,
    *,
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> bool:
    """Update the latest-import timestamp for the authenticated user.

    Returns `True` on success.
    """
    try:
        body = json.dumps({"ts": ts, "service": service}).encode("utf-8")
        data, _rl = _make_request(
            "POST", "/1/latest-import",
            token=token,
            body=body,
            timeout=15,
            on_timeout=on_timeout,
            should_abort=should_abort,
        )
        return data.get("status") == "ok"
    except ScrobbleAborted:
        raise
    except Exception as exc:
        logger.warning("Failed to set latest import timestamp: %s", exc)
        return False


# ── Public API: submit listens ──────────────────────────────────────────────

def _build_listen_payload(entry: ScrobbleEntry) -> dict:
    """Convert a ScrobbleEntry into a ListenBrainz listen dict.

    Follows the JSON payload format documented at
    https://listenbrainz.readthedocs.io/en/latest/users/json.html
    """
    additional_info: dict = {
        "submission_client": SUBMISSION_CLIENT,
        "submission_client_version": SUBMISSION_CLIENT_VERSION,
        "media_player": MEDIA_PLAYER,
    }
    if entry.duration_secs > 0:
        additional_info["duration_ms"] = entry.duration_secs * 1000
    if entry.track_number > 0:
        additional_info["tracknumber"] = entry.track_number
    if entry.disc_number > 0:
        additional_info["discnumber"] = entry.disc_number
    if entry.isrc:
        additional_info["isrc"] = entry.isrc
    if entry.recording_mbid:
        additional_info["recording_mbid"] = entry.recording_mbid
    if entry.genre:
        additional_info["tags"] = [entry.genre]

    listen: dict = {
        "listened_at": entry.timestamp,
        "track_metadata": {
            "artist_name": entry.artist,
            "track_name": entry.track,
            "additional_info": additional_info,
        },
    }
    if entry.album:
        listen["track_metadata"]["release_name"] = entry.album

    return listen


def scrobble_listenbrainz(
    entries: list[ScrobbleEntry],
    token: str,
    *,
    listenbrainz_username: str = "",
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> ScrobbleResult:
    """Submit listens to ListenBrainz.

    Sends batches of up to ``BATCH_SIZE`` listens using the ``import``
    listen type.  Respects rate-limit headers and retries on 429.
    After a successful submission the ``latest-import`` timestamp is
    updated so that ListenBrainz knows how far we've imported.
    """
    result = ScrobbleResult()
    if not entries or not token:
        return result

    # Filter out entries with timestamps below the LB minimum.
    valid_entries = [e for e in entries if e.timestamp >= LISTEN_MINIMUM_TS]
    if len(valid_entries) < len(entries):
        skipped = len(entries) - len(valid_entries)
        logger.info("Skipped %d entries with timestamp below LISTEN_MINIMUM_TS", skipped)
        result.ignored += skipped

    if listenbrainz_username:
        try:
            latest_import = get_latest_import(
                listenbrainz_username,
                token,
                service=IMPORT_SERVICE,
                on_timeout=on_timeout,
                should_abort=should_abort,
            )
        except ScrobbleAborted:
            result.errors.append("User gave up while connecting to ListenBrainz")
            logger.info("ListenBrainz latest-import lookup aborted by user")
            return result
        if latest_import > 0:
            filtered_entries = [
                entry for entry in valid_entries if entry.timestamp > latest_import
            ]
            skipped = len(valid_entries) - len(filtered_entries)
            if skipped:
                logger.info(
                    "Skipped %d entries at or before latest-import %d",
                    skipped,
                    latest_import,
                )
                result.ignored += skipped
            valid_entries = filtered_entries

    if not valid_entries:
        return result

    max_ts = 0  # track the newest timestamp we submit

    for batch_start in range(0, len(valid_entries), BATCH_SIZE):
        batch = valid_entries[batch_start:batch_start + BATCH_SIZE]
        payload = [_build_listen_payload(e) for e in batch]

        body = json.dumps({
            "listen_type": "import",
            "payload": payload,
        }).encode("utf-8")

        result.submitted += len(batch)

        try:
            resp_data, rl = _make_request(
                "POST", "/1/submit-listens",
                token=token,
                body=body,
                timeout=12,
                on_timeout=on_timeout,
                should_abort=should_abort,
            )

            if resp_data.get("status") == "ok":
                result.accepted += len(batch)
                batch_max = max(e.timestamp for e in batch)
                max_ts = max(max_ts, batch_max)
            else:
                result.errors.append(
                    f"Unexpected response: {resp_data}"
                )

            # If we're getting close to the rate limit, proactively sleep.
            if rl.remaining is not None and rl.remaining <= 1 and rl.reset_in > 0:
                logger.debug("Proactive rate-limit sleep: %.1fs", rl.reset_in)
                _sleep_with_abort(rl.reset_in, should_abort)

        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            result.errors.append(f"HTTP {exc.code}: {body_text}")
            logger.error("ListenBrainz HTTP %d: %s", exc.code, body_text)
        except ScrobbleAborted:
            result.errors.append("User gave up while connecting to ListenBrainz")
            logger.info("ListenBrainz scrobble aborted by user")
            break
        except Exception as exc:
            result.errors.append(f"Batch at index {batch_start}: {exc}")
            logger.error("ListenBrainz batch error: %s", exc)

    # Update latest-import so LB knows how far we've gotten.
    if max_ts > 0:
        try:
            if not set_latest_import(
                max_ts,
                token,
                service=IMPORT_SERVICE,
                on_timeout=on_timeout,
                should_abort=should_abort,
            ):
                result.errors.append(
                    "Latest-import timestamp could not be updated; "
                    "future duplicate protection may be affected"
                )
        except ScrobbleAborted:
            result.errors.append(
                "Latest-import update aborted after submission; "
                "future duplicate protection may be affected"
            )
            logger.info("ListenBrainz latest-import update aborted by user")

    logger.info(
        "ListenBrainz: %d submitted, %d accepted, %d ignored, %d errors",
        result.submitted, result.accepted, result.ignored, len(result.errors),
    )
    return result


# ── Public API: get listen history ──────────────────────────────────────────

def get_listens(
    username: str,
    token: str = "",
    *,
    max_ts: int | None = None,
    min_ts: int | None = None,
    count: int = 25,
) -> list[dict]:
    """Fetch listen history for a user.

    Returns a list of listen dicts (newest first by default).
    Provide either `max_ts` or `min_ts` (not both) to paginate.
    `count` may be 1–1000 (server default is 25).
    """
    params: dict[str, str] = {"count": str(count)}
    if max_ts is not None:
        params["max_ts"] = str(max_ts)
    elif min_ts is not None:
        params["min_ts"] = str(min_ts)

    try:
        data, _rl = _make_request(
            "GET", f"/1/user/{urllib.parse.quote(username, safe='')}/listens",
            token=token,
            params=params,
        )
        return data.get("payload", {}).get("listens", [])
    except Exception as exc:
        logger.error("Failed to fetch listens for %s: %s", username, exc)
        return []


def get_listen_count(username: str, token: str = "") -> int:
    """Get the total listen count for a user."""
    try:
        data, _rl = _make_request(
            "GET", f"/1/user/{urllib.parse.quote(username, safe='')}/listen-count",
            token=token,
        )
        return int(data.get("payload", {}).get("count", 0))
    except Exception as exc:
        logger.error("Failed to fetch listen count for %s: %s", username, exc)
        return 0


# ── Orchestrator ────────────────────────────────────────────────────────────

def build_scrobble_entries(
    playcount_items: list,
) -> list[ScrobbleEntry]:
    """Build ScrobbleEntry list from sync plan playcount items.

    Each ``SyncItem`` carries a ``play_count_delta`` — the number of
    plays recorded in the iPod Play Counts file since the last sync.
    These are the plays that need to be scrobbled.

    For each play in the delta, a timestamp is generated by spacing
    backwards from ``lastPlayed`` by the track's duration, using the
    playback start time for ListenBrainz's ``listened_at`` field.

    Tracks shorter than 30 s or missing artist/title are skipped.

    Returns:
        Sorted list of ScrobbleEntry objects, oldest first.
    """
    entries: list[ScrobbleEntry] = []

    for item in playcount_items:
        delta = item.play_count_delta
        if delta <= 0:
            continue

        # Get track metadata — prefer pc_track (richer), fall back to ipod_track
        pc = item.pc_track
        ipod = item.ipod_track or {}

        artist = (pc.artist if pc else None) or ipod.get("Artist", "")
        track_name = (pc.title if pc else None) or ipod.get("Title", "")
        album = (pc.album if pc else None) or ipod.get("Album", "")
        album_artist = (pc.album_artist if pc else None) or ipod.get("Album Artist", "")
        track_number = (pc.track_number if pc else None) or ipod.get("track_number", 0) or 0
        disc_number = (pc.disc_number if pc else None) or ipod.get("disc_number", 0) or 0
        genre = (pc.genre if pc else None) or ipod.get("Genre", "") or ""

        # Duration in milliseconds
        duration_ms = (pc.duration_ms if pc else 0) or ipod.get("length", 0) or 0
        duration_secs = duration_ms // 1000

        # Skip very short tracks (< 30 seconds)
        if duration_ms < MIN_SCROBBLE_DURATION_MS:
            continue

        # Skip tracks with no artist or title
        if not artist or not track_name:
            continue

        # Get last_played timestamp (Unix epoch)
        last_played = ipod.get("last_played", 0)
        if last_played <= 0:
            last_played = int(time.time())

        # Generate timestamps for each play, spaced backwards by duration.
        # ListenBrainz expects listened_at to be the playback start time,
        # so shift each play back by one full play spacing from last_played.
        play_spacing_secs = max(duration_secs, 180)
        for play_idx in range(delta):
            ts = last_played - ((play_idx + 1) * play_spacing_secs)
            # Ensure timestamp is positive and >= LISTEN_MINIMUM_TS
            if ts < LISTEN_MINIMUM_TS:
                ts = int(time.time()) - ((play_idx + 1) * play_spacing_secs)

            entries.append(ScrobbleEntry(
                artist=artist,
                track=track_name,
                album=album,
                duration_secs=duration_secs,
                timestamp=ts,
                track_number=track_number,
                album_artist=album_artist,
                genre=genre,
                disc_number=disc_number,
            ))

    # Sort oldest first (ListenBrainz prefers chronological order)
    entries.sort(key=lambda e: e.timestamp)
    return entries


def scrobble_plays(
    playcount_items: list,
    listenbrainz_token: str = "",
    *,
    listenbrainz_username: str = "",
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> list[ScrobbleResult]:
    """Submit scrobbles to ListenBrainz.

    This is the main entry point called from the sync executor.

    Args:
        playcount_items: SyncItems with action=SYNC_PLAYCOUNT.
            Each item carries ``play_count_delta`` (the iPod Play Counts
            file delta for this sync session).
        listenbrainz_token: ListenBrainz user token (empty = skip)

    Returns:
        List of ScrobbleResult (one per service attempted).
    """
    entries = build_scrobble_entries(playcount_items)
    if not entries:
        logger.info("No scrobbles to submit (no qualifying plays)")
        return []

    logger.info("Built %d scrobble entries from iPod play counts", len(entries))
    results: list[ScrobbleResult] = []

    if listenbrainz_token:
        try:
            r = scrobble_listenbrainz(
                entries,
                listenbrainz_token,
                listenbrainz_username=listenbrainz_username,
                on_timeout=on_timeout,
                should_abort=should_abort,
            )
            results.append(r)
        except Exception as exc:
            logger.error("ListenBrainz scrobbling failed: %s", exc)
            results.append(ScrobbleResult(errors=[str(exc)]))

    return results
