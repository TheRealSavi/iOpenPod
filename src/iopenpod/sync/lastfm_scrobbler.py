"""
Scrobbling support for Last.fm.

API reference:
  https://www.last.fm/api/show/track.scrobble

Key Last.fm constraints:
  MAX_LISTENS_PER_REQUEST = 50
  Authentication requires API Key, API Secret, and Session Key (sk).
  Requests must be signed via MD5.

Scrobbling rules:
  - Submit a listen when the user has listened to >4 min or >50% of the
    track, whichever is lower.
  - Tracks shorter than 30 s are not scrobbled.
  - For multiple plays of the same track, space timestamps backwards from
    `last_played` by `track_duration` per play.
"""

from __future__ import annotations

import hashlib
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

# ── Last.fm constants ───────────────────────────────────────────────────────

LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"

SUBMISSION_CLIENT = "iOpenPod"
SUBMISSION_CLIENT_VERSION = "1.0.0"

# The API allows up to 50 scrobbles per POST request.
BATCH_SIZE = 50

# Minimum track length to scrobble (widely adopted convention).
MIN_SCROBBLE_DURATION_MS = 30_000

# Maximum retries for network or rate-limit issues.
MAX_RETRIES = 5

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
    genre: str = ""             # Optional — (Last.fm ignores this on scrobble)
    disc_number: int = 0        # Optional
    isrc: str = ""              # Optional — (Last.fm ignores this on scrobble)
    recording_mbid: str = ""    # Optional — MusicBrainz Recording ID


@dataclass(slots=True)
class ScrobbleResult:
    """Summary of a scrobble submission batch."""

    service: str = "lastfm"
    submitted: int = 0
    accepted: int = 0
    ignored: int = 0
    errors: list[str] = field(default_factory=list)


class ScrobbleAborted(Exception):
    """Raised when the user chooses to stop retrying scrobbles."""


class LastFmApiError(RuntimeError):
    """Structured Last.fm API error returned in a JSON response body."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Last.fm API {code}: {message}")


def _lastfm_error_code(data: dict) -> int:
    try:
        return int(data.get("error", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _lastfm_error_message(data: dict) -> str:
    return str(data.get("message", "Unknown Last.fm API error"))


def _sleep_with_abort(
    seconds: float,
    should_abort: Callable[[], bool] | None = None,
) -> None:
    """Sleep in short increments so cancellation remains responsive."""
    deadline = time.monotonic() + max(seconds, 0.0)
    while True:
        if should_abort and should_abort():
            raise ScrobbleAborted("User gave up while connecting to Last.fm")
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


# ── Last.fm Auth & Signatures ───────────────────────────────────────────────

def _sign_request(params: dict[str, str], api_secret: str) -> str:
    """Generate an MD5 API signature for Last.fm write requests.
    
    Rule: Sort params alphabetically, concatenate keys and values,
    append the API secret, and MD5 hash the result.
    Ignore 'format' and 'callback' parameters.
    """
    keys = sorted([k for k in params.keys() if k not in ("format", "callback")])
    string_to_sign = "".join(f"{k}{params[k]}" for k in keys) + api_secret
    return hashlib.md5(string_to_sign.encode("utf-8")).hexdigest()


def _is_lastfm_api_key_valid(api_key: str, api_secret: str) -> bool:
    """Check if the Last.fm API Key and Secret are valid by making a simple request."""
    params = {
        "method": "chart.getTopArtists",
        "api_key": api_key,
    }
    try:
        _make_lastfm_request(params, api_secret=api_secret, method="GET", timeout=10)
        return True
    except LastFmApiError as exc:
        if exc.code in {4, 10, 13, 26}:
            logger.warning("Last.fm API Key/Secret validation failed: %s", exc)
            return False
        raise
    except RuntimeError as exc:
        if "Last.fm HTTP 403:" in str(exc):
            logger.warning("Last.fm API Key/Secret validation failed: %s", exc)
            return False
        raise
    except Exception as exc:
        logger.error("Last.fm API Key/Secret validation failed: %s", exc)
        return False


# ── Low-level HTTP helpers ──────────────────────────────────────────────────

def _make_lastfm_request(
    params: dict[str, str],
    api_secret: str = "",
    method: str = "POST",
    timeout: int = 30,
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> dict:
    """Send an HTTP request to the Last.fm API.

    Handles signing the request, parsing JSON, and network retries.
    """
    params["format"] = "json"
    
    # Sign the request if a secret is provided (required for write operations)
    if api_secret:
        params["api_sig"] = _sign_request(params, api_secret)

    payload = urllib.parse.urlencode(params).encode("utf-8") if method == "POST" else None
    url = LASTFM_API_ROOT
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)

    retry_attempt = 0
    timeout_start = time.monotonic()

    while True:
        if should_abort and should_abort():
            raise ScrobbleAborted("User gave up while connecting to Last.fm")

        req = urllib.request.Request(url, data=payload, method=method)
        req.add_header("User-Agent", f"{SUBMISSION_CLIENT}/{SUBMISSION_CLIENT_VERSION}")
        if method == "POST":
            req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and "error" in data:
                    code = _lastfm_error_code(data)
                    message = _lastfm_error_message(data)
                    if code in (11, 16, 29) and retry_attempt < MAX_RETRIES:
                        retry_attempt += 1
                        wait = 5.0 * retry_attempt
                        logger.warning(
                            "Last.fm temporary API error %s; sleeping %.1fs",
                            code,
                            wait,
                        )
                        _sleep_with_abort(wait, should_abort)
                        continue
                    raise LastFmApiError(code, str(message))
                return data

        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            
            try:
                err_data = json.loads(body_text)
                code = _lastfm_error_code(err_data) if isinstance(err_data, dict) else 0
                message = _lastfm_error_message(err_data) if isinstance(err_data, dict) else body_text
                # Error 11: Service Offline, Error 16: Temporarily Unavailable, Error 29: Rate Limit
                if code in (11, 16, 29) and retry_attempt < MAX_RETRIES:
                    retry_attempt += 1
                    wait = 5.0 * retry_attempt # Exponential-ish backoff
                    logger.warning("Last.fm temporary error/rate limit; sleeping %.1fs", wait)
                    _sleep_with_abort(wait, should_abort)
                    continue
                if code:
                    raise LastFmApiError(code, message) from exc
            except json.JSONDecodeError:
                pass

            raise RuntimeError(f"Last.fm HTTP {exc.code}: {body_text}") from exc

        except Exception as exc:
            if _is_timeout_error(exc):
                retry_attempt += 1
                elapsed = time.monotonic() - timeout_start
                if on_timeout:
                    on_timeout(elapsed, retry_attempt, timeout)
                logger.warning(
                    "Last.fm request timed out after %ds (attempt %d, %.1fs elapsed)",
                    timeout,
                    retry_attempt,
                    elapsed,
                )
                continue
            raise

    raise RuntimeError("Exhausted retries connecting to Last.fm")


# ── Public API: Session validation ──────────────────────────────────────────

def lastfm_validate_session(api_key: str, api_secret: str, session_key: str) -> str | None:
    """Validate a Last.fm session key by calling user.getInfo.

    Returns:
        The username if valid, `None` otherwise.
    """
    params = {
        "method": "user.getInfo",
        "api_key": api_key,
        "sk": session_key,
    }
    try:
        data = _make_lastfm_request(params, api_secret=api_secret, method="GET", timeout=15)
        return data.get("user", {}).get("name")
    except Exception as exc:
        logger.error("Last.fm session validation failed: %s", exc)
        return None


# ── Public API: submit listens ──────────────────────────────────────────────

def _build_scrobble_batch_params(batch: list[ScrobbleEntry], api_key: str, session_key: str) -> dict[str, str]:
    """Convert a batch of ScrobbleEntries into Last.fm indexed parameters."""
    params = {
        "method": "track.scrobble",
        "api_key": api_key,
        "sk": session_key,
    }

    for i, entry in enumerate(batch):
        params[f"artist[{i}]"] = entry.artist
        params[f"track[{i}]"] = entry.track
        params[f"timestamp[{i}]"] = str(entry.timestamp)
        
        if entry.album:
            params[f"album[{i}]"] = entry.album
        if entry.album_artist:
            params[f"albumArtist[{i}]"] = entry.album_artist
        if entry.duration_secs > 0:
            params[f"duration[{i}]"] = str(entry.duration_secs)
        if entry.track_number > 0:
            params[f"trackNumber[{i}]"] = str(entry.track_number)
        if entry.recording_mbid:
            params[f"mbid[{i}]"] = entry.recording_mbid

    return params


def scrobble_lastfm(
    entries: list[ScrobbleEntry],
    api_key: str,
    api_secret: str,
    session_key: str,
    *,
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> ScrobbleResult:
    """Submit listens to Last.fm.

    Sends batches of up to ``BATCH_SIZE`` listens.
    """
    result = ScrobbleResult()
    if not entries or not api_key or not session_key or not api_secret:
        return result

    valid_entries = entries  # All entries are presumed valid without a min_ts check like LB

    for batch_start in range(0, len(valid_entries), BATCH_SIZE):
        batch = valid_entries[batch_start:batch_start + BATCH_SIZE]
        
        params = _build_scrobble_batch_params(batch, api_key, session_key)
        result.submitted += len(batch)

        try:
            resp_data = _make_lastfm_request(
                params,
                api_secret=api_secret,
                method="POST",
                timeout=15,
                on_timeout=on_timeout,
                should_abort=should_abort,
            )

            # Last.fm returns a summary of accepted/ignored scrobbles
            scrobbles_resp = resp_data.get("scrobbles", {})
            attr = scrobbles_resp.get("@attr", {})
            
            result.accepted += int(attr.get("accepted", 0))
            result.ignored += int(attr.get("ignored", 0))

            # Optional: Sleep briefly between batches to be nice to Last.fm
            _sleep_with_abort(0.5, should_abort)

        except ScrobbleAborted:
            result.errors.append("User gave up while connecting to Last.fm")
            logger.info("Last.fm scrobble aborted by user")
            break
        except Exception as exc:
            result.errors.append(f"Batch at index {batch_start}: {exc}")
            logger.error("Last.fm batch error: %s", exc)

    logger.info(
        "Last.fm: %d submitted, %d accepted, %d ignored, %d errors",
        result.submitted, result.accepted, result.ignored, len(result.errors),
    )
    return result


# ── Orchestrator ────────────────────────────────────────────────────────────

def build_scrobble_entries(playcount_items: list) -> list[ScrobbleEntry]:
    """Build ScrobbleEntry list from sync plan playcount items."""
    entries: list[ScrobbleEntry] = []

    for item in playcount_items:
        delta = item.play_count_delta
        if delta <= 0:
            continue

        pc = item.pc_track
        ipod = item.ipod_track or {}

        artist = (pc.artist if pc else None) or ipod.get("Artist", "")
        track_name = (pc.title if pc else None) or ipod.get("Title", "")
        album = (pc.album if pc else None) or ipod.get("Album", "")
        album_artist = (pc.album_artist if pc else None) or ipod.get("Album Artist", "")
        track_number = (pc.track_number if pc else None) or ipod.get("track_number", 0) or 0
        disc_number = (pc.disc_number if pc else None) or ipod.get("disc_number", 0) or 0
        genre = (pc.genre if pc else None) or ipod.get("Genre", "") or ""

        duration_ms = (pc.duration_ms if pc else 0) or ipod.get("length", 0) or 0
        duration_secs = duration_ms // 1000

        if duration_ms < MIN_SCROBBLE_DURATION_MS:
            continue

        if not artist or not track_name:
            continue

        last_played = ipod.get("last_played", 0)
        if last_played <= 0:
            last_played = int(time.time())

        play_spacing_secs = max(duration_secs, 180)
        for play_idx in range(delta):
            ts = last_played - ((play_idx + 1) * play_spacing_secs)

            # Safeguard timestamp
            if ts <= 0:
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

    entries.sort(key=lambda e: e.timestamp)
    return entries


def scrobble_plays(
    playcount_items: list,
    api_key: str = "",
    api_secret: str = "",
    session_key: str = "",
    *,
    on_timeout: Callable[[float, int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> list[ScrobbleResult]:
    """Submit scrobbles to Last.fm.

    Args:
        playcount_items: SyncItems with action=SYNC_PLAYCOUNT.
        api_key: Last.fm API Key
        api_secret: Last.fm API Secret
        session_key: Last.fm user Session Key (sk)

    Returns:
        List of ScrobbleResult.
    """
    entries = build_scrobble_entries(playcount_items)
    if not entries:
        logger.info("No scrobbles to submit (no qualifying plays)")
        return []

    logger.info("Built %d scrobble entries from iPod play counts", len(entries))
    results: list[ScrobbleResult] = []

    if api_key and api_secret and session_key:
        try:
            r = scrobble_lastfm(
                entries,
                api_key,
                api_secret,
                session_key,
                on_timeout=on_timeout,
                should_abort=should_abort,
            )
            results.append(r)
        except Exception as exc:
            logger.error("Last.fm scrobbling failed: %s", exc)
            results.append(ScrobbleResult(errors=[str(exc)]))

    return results
