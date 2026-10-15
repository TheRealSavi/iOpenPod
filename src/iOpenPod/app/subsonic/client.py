"""OpenSubsonic REST API client using standard library urllib and certifi."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import ssl
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener

import certifi

from .models import SubsonicPlaylist, SubsonicSong

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_API_VERSION = "1.16.1"
_CLIENT_NAME = "iOpenPod"
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class SubsonicConnectionError(RuntimeError):
    """Raised when a Subsonic server cannot be reached or rejects credentials."""

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
    """Compute OpenSubsonic authentication token: md5(password + salt)."""
    return hashlib.md5((password + salt).encode("utf-8")).hexdigest()


def _normalize_server_url(url: str) -> str:
    """Normalize base URL by stripping trailing slashes and whitespace."""
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


class SubsonicClient:
    """Minimal OpenSubsonic REST client for playlist synchronization."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        *,
        timeout: int = _DEFAULT_TIMEOUT,
        client_name: str = _CLIENT_NAME,
    ) -> None:
        self.base_url = _normalize_server_url(url)
        self.username = (username or "").strip()
        self.password = password or ""
        self.timeout = timeout
        self.client_name = client_name
        self._opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))
        )

    def _auth_params(self) -> dict[str, str]:
        salt = secrets.token_hex(8)
        return {
            "u": self.username,
            "t": _make_token(self.password, salt),
            "s": salt,
            "v": _API_VERSION,
            "c": self.client_name,
            "f": "json",
        }

    def _endpoint_url(
        self, endpoint: str, params: Mapping[str, Any] | None = None
    ) -> str:
        merged: dict[str, str] = self._auth_params()
        if params:
            for k, v in params.items():
                if v is not None:
                    merged[str(k)] = str(v)
        query = urlencode(merged)
        return f"{self.base_url}/rest/{endpoint}.view?{query}"

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        url = self._endpoint_url(endpoint, params)
        request = Request(
            url,
            headers={
                "User-Agent": f"{self.client_name} (Subsonic client)",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                content = response.read(_MAX_RESPONSE_BYTES)
        except HTTPError as exc:
            try:
                error_body = exc.read(_MAX_RESPONSE_BYTES).decode(
                    "utf-8", errors="replace"
                )
                parsed = json.loads(error_body)
                sub_response = parsed.get("subsonic-response", {})
                error_info = sub_response.get("error", {})
                code = error_info.get("code")
                msg = error_info.get("message") or f"HTTP {exc.code}"
                raise SubsonicConnectionError(
                    f"Subsonic error {code}: {msg}",
                    url=self.base_url,
                    error_code=code,
                    error_message=msg,
                ) from exc
            except (ValueError, KeyError):
                raise SubsonicConnectionError(
                    f"Subsonic server error HTTP {exc.code}: {exc.reason}",
                    url=self.base_url,
                    error_code=exc.code,
                ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SubsonicConnectionError(
                f"Could not connect to Subsonic server at {self.base_url}: {exc}",
                url=self.base_url,
            ) from exc

        try:
            payload = json.loads(content.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise SubsonicConnectionError(
                "Subsonic server returned an invalid non-JSON response",
                url=self.base_url,
            ) from exc

        if not isinstance(payload, dict):
            raise SubsonicConnectionError(
                "Unexpected Subsonic response format", url=self.base_url
            )

        sub_resp = payload.get("subsonic-response", payload)
        if not isinstance(sub_resp, dict):
            raise SubsonicConnectionError(
                "Malformed subsonic-response object", url=self.base_url
            )

        status = sub_resp.get("status")
        if status != "ok":
            error_data = sub_resp.get("error")
            err_code: int | None = None
            msg = "Unknown error"
            if isinstance(error_data, dict):
                err_code = error_data.get("code")
                msg = str(error_data.get("message") or msg)
            raise SubsonicConnectionError(
                f"Subsonic server rejected request: {msg}",
                url=self.base_url,
                error_code=err_code,
                error_message=msg,
            )

        return sub_resp

    def ping(self) -> None:
        """Validate server reachability and credentials."""
        self._get_json("ping")

    def get_playlists(self) -> tuple[SubsonicPlaylist, ...]:
        """Fetch all playlists visible to this user."""
        body = self._get_json("getPlaylists")
        playlists_container = body.get("playlists")
        if not isinstance(playlists_container, dict):
            return ()
        raw_list = playlists_container.get("playlist")
        if not isinstance(raw_list, list):
            return ()

        result: list[SubsonicPlaylist] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "").strip()
            name = str(item.get("name") or pid).strip()
            if not pid or not name:
                continue
            result.append(
                SubsonicPlaylist(
                    playlist_id=pid,
                    name=name,
                    comment=str(item.get("comment") or ""),
                    song_count=int(item.get("songCount") or 0),
                    duration=int(item.get("duration") or 0),
                    created=str(item.get("created") or ""),
                )
            )
        return tuple(result)

    def get_playlist(self, playlist_id: str) -> tuple[SubsonicSong, ...]:
        """Fetch entries for a specific playlist."""
        body = self._get_json("getPlaylist", {"id": playlist_id})
        playlist_obj = body.get("playlist")
        if not isinstance(playlist_obj, dict):
            return ()
        raw_entries = playlist_obj.get("entry")
        if not isinstance(raw_entries, list):
            return ()

        songs: list[SubsonicSong] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            if not sid:
                continue
            track_val: int | None = None
            if entry.get("track") is not None:
                try:
                    track_val = int(entry["track"])
                except (TypeError, ValueError):
                    track_val = None
            year_val: int | None = None
            if entry.get("year") is not None:
                try:
                    year_val = int(entry["year"])
                except (TypeError, ValueError):
                    year_val = None

            songs.append(
                SubsonicSong(
                    song_id=sid,
                    title=title or "Unknown Title",
                    artist=str(entry.get("artist") or "Unknown Artist"),
                    album=str(entry.get("album") or "Unknown Album"),
                    track=track_val,
                    year=year_val,
                    genre=str(entry.get("genre")) if entry.get("genre") else None,
                    duration=int(entry.get("duration") or 0),
                    cover_art=str(entry.get("coverArt"))
                    if entry.get("coverArt")
                    else None,
                )
            )
        return tuple(songs)

    def get_cover_art_bytes(self, cover_art_id: str) -> bytes:
        """Download cover art image bytes."""
        url = self._endpoint_url("getCoverArt", {"id": cover_art_id})
        request = Request(
            url,
            headers={
                "User-Agent": f"{self.client_name} (Subsonic client)",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return cast("bytes", response.read(_MAX_RESPONSE_BYTES))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SubsonicConnectionError(
                f"Could not fetch Subsonic cover art {cover_art_id}: {exc}",
                url=self.base_url,
            ) from exc

    def download_track(self, song_id: str, dest_path: str) -> None:
        """Stream audio track bytes directly to a local destination file."""
        url = self._endpoint_url("stream", {"id": song_id})
        request = Request(
            url,
            headers={
                "User-Agent": f"{self.client_name} (Subsonic client)",
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response, open(
                dest_path, "wb"
            ) as f:
                while chunk := response.read(64 * 1024):
                    f.write(chunk)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SubsonicConnectionError(
                f"Could not download Subsonic track {song_id}: {exc}",
                url=self.base_url,
            ) from exc
