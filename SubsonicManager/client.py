"""Subsonic / OpenSubsonic REST API client.

Implements the standard OpenSubsonic authentication scheme (per-request
random salt + ``token = md5(password + salt)``) and the small set of
endpoints iOpenPod needs: ``ping``, ``getStarred2``, ``getPlaylists``,
``getPlaylist``, ``getAlbum``, ``getCoverArt`` and ``download``.

Reference: https://opensubsonic.netlify.app/docs/api-reference/

The streaming download path mirrors ``PodcastManager.downloader.download_episode``:
``requests`` streaming, ``.part`` temp file + atomic rename, chunk-level
cancellation and progress callbacks.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import tempfile
from collections.abc import Callable
from typing import Protocol

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds (connect timeout; read is streaming)
_CHUNK_SIZE = 64 * 1024  # 64 KB
_API_VERSION = "1.16.1"  # Subsonic API version; widely supported
_CLIENT_NAME = "iOpenPod"


class CancelToken(Protocol):
    """Protocol for cancellation tokens (mirrors PodcastManager.downloader)."""

    def is_cancelled(self) -> bool: ...


class SubsonicConnectionError(RuntimeError):
    """Raised when a Subsonic server cannot be reached or rejects credentials.

    Carries the server URL and the OpenSubsonic error code/message (when the
    server responds with ``status="failed"``) so the GUI can show a useful
    diagnostic.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        error_code: int | None = None,
        error_message: str = "",
    ) -> None:
        super().__init__(message)
        self.url = url
        self.error_code = error_code
        self.error_message = error_message


def _make_token(password: str, salt: str) -> str:
    """Compute the OpenSubsonic ``token`` = hex(md5(password + salt))."""
    return hashlib.md5((password + salt).encode("utf-8")).hexdigest()


def _normalize_server_url(url: str) -> str:
    """Strip trailing slashes from the server base URL."""
    return (url or "").rstrip("/")


class SubsonicClient:
    """Minimal OpenSubsonic REST client for iOpenPod's sync source."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        *,
        timeout: int = _TIMEOUT,
        client_name: str = _CLIENT_NAME,
    ) -> None:
        self.base_url = _normalize_server_url(url)
        self.username = username or ""
        self.password = password or ""
        self.timeout = timeout
        self.client_name = client_name
        # Cached hash of a Navidrome-style placeholder cover (set by
        # detect_placeholder_cover); when non-None, a cover whose MD5 matches
        # is treated as "no real artwork".  See artwork.py.
        self.placeholder_cover_hash: str | None = None

    # -- internals ---------------------------------------------------------

    def _auth_params(self) -> dict[str, str]:
        """Per-request auth params (token+salt scheme)."""
        salt = secrets.token_hex(8)
        return {
            "u": self.username,
            "t": _make_token(self.password, salt),
            "s": salt,
            "v": _API_VERSION,
            "c": self.client_name,
            "f": "json",
        }

    def _endpoint_url(self, endpoint: str, params: dict | None = None) -> str:
        """Build the full REST URL for an endpoint with auth + extra params."""
        merged = self._auth_params()
        if params:
            merged.update(params)
        query = "&".join(f"{k}={v}" for k, v in merged.items() if v is not None)
        return f"{self.base_url}/rest/{endpoint}.view?{query}"

    def _get_json(self, endpoint: str, params: dict | None = None) -> dict:
        """GET an endpoint and return the inner ``subsonic-response`` dict.

        Raises ``SubsonicConnectionError`` on network failure or when the
        server reports ``status="failed"``.
        """
        url = self._endpoint_url(endpoint, params)
        try:
            resp = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SubsonicConnectionError(
                f"Could not reach Subsonic server: {exc}", url=self.base_url
            ) from exc

        # Non-JSON responses (e.g. a reverse proxy login page) must not crash us.
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SubsonicConnectionError(
                f"Subsonic server returned a non-JSON response (HTTP {resp.status_code})",
                url=self.base_url,
            ) from exc

        body = payload.get("subsonic-response", payload)
        status = body.get("status")
        if status != "ok":
            error = body.get("error") or {}
            code = error.get("code")
            msg = error.get("message") or status or "unknown error"
            raise SubsonicConnectionError(
                f"Subsonic server rejected the request: {msg}",
                url=self.base_url,
                error_code=code,
                error_message=msg,
            )
        return body

    # -- public API --------------------------------------------------------

    def ping(self) -> None:
        """Validate credentials / connectivity.

        Raises ``SubsonicConnectionError`` on failure; returns None on success.
        """
        self._get_json("ping")

    def get_starred2(self) -> dict:
        """Return the user's starred songs/albums/artists.

        Uses the ID3-typed ``getStarred2`` (modern) endpoint.  The response
        contains ``starred2.song`` and ``starred2.album`` arrays.
        """
        body = self._get_json("getStarred2")
        return body.get("starred2") or {}

    def get_playlists(self) -> list[dict]:
        """Return the user's playlists (without entries)."""
        body = self._get_json("getPlaylists")
        playlists = body.get("playlists") or {}
        return playlists.get("playlist") or []

    def get_playlist(self, playlist_id: str) -> dict:
        """Return a single playlist with its entries.

        The response contains ``playlist.entry`` (list of songs).
        """
        body = self._get_json("getPlaylist", {"id": playlist_id})
        return body.get("playlist") or {}

    def get_album(self, album_id: str) -> dict:
        """Return an album with its songs (AlbumWithSongsID3).

        The response contains ``album.song`` (list of songs).
        """
        body = self._get_json("getAlbum", {"id": album_id})
        return body.get("album") or {}

    def get_cover_art_bytes(self, cover_art_id: str) -> bytes:
        """Download cover-art bytes for the given ``coverArt`` id.

        Returns the raw image bytes.  Raises ``SubsonicConnectionError`` on
        network failure.  Some servers (Navidrome) serve a placeholder image
        for missing covers rather than erroring; callers compare the MD5
        against ``placeholder_cover_hash`` to detect this.
        """
        url = self._endpoint_url("getCoverArt", {"id": cover_art_id})
        try:
            resp = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SubsonicConnectionError(
                f"Could not fetch cover art: {exc}", url=self.base_url
            ) from exc
        resp.raise_for_status()
        return resp.content

    def download_track(
        self,
        track_id: str,
        dest_path: str,
        *,
        progress_cb: Callable[[int, int], None] | None = None,
        cancel_token: CancelToken | None = None,
    ) -> str:
        """Stream a track's original audio bytes to ``dest_path``.

        Uses the ``download`` endpoint (full-quality original file, not the
        transcoding-capable ``stream`` endpoint).  Mirrors the podcast
        downloader: idempotent if the destination already exists, writes to a
        ``.part`` temp file, atomically renames on completion, and checks the
        cancel token per chunk.

        Args:
            track_id: Subsonic track id.
            dest_path: Absolute destination path (extension already decided).
            progress_cb: Called with (bytes_downloaded, total_bytes);
                total_bytes is 0 when the server omits Content-Length.
            cancel_token: Optional token; download aborts if cancelled.

        Returns:
            The destination path (== ``dest_path``).
        """
        # Idempotent: skip if already fully downloaded.
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            return dest_path

        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        url = self._endpoint_url("download", {"id": track_id})

        try:
            resp = requests.get(
                url,
                stream=True,
                timeout=self.timeout,
                headers={"User-Agent": f"{self.client_name} (Subsonic sync)"},
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SubsonicConnectionError(
                f"Could not download track {track_id}: {exc}", url=self.base_url
            ) from exc

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0

        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(dest_path), suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                    if cancel_token and cancel_token.is_cancelled():
                        raise RuntimeError("Subsonic download cancelled")
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
            os.replace(tmp_path, dest_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

        log.debug("Downloaded Subsonic track %s -> %s (%d bytes)", track_id, dest_path, downloaded)
        return dest_path
