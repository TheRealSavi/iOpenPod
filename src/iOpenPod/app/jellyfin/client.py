"""Jellyfin 10.9+ HTTP contract for play counts, without persistence or Qt."""

from __future__ import annotations

import json
import re
import ssl
from typing import TYPE_CHECKING, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

from iOpenPod.app.core.version import get_version

from ._json import (
    integer,
    is_array,
    is_object,
    optional_integer,
    optional_text,
    text,
)
from .models import MAX_PLAY_COUNT, JellyfinAccount, JellyfinError, JellyfinTrack

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

MIN_VERSION = (10, 9)
PAGE_SIZE = 500
MAX_RESPONSE = 16 * 1024 * 1024
_DEVICE_NAME = "iOpenPod"
_ITEM_ID = re.compile(r"[0-9A-Fa-f-]{32,36}")


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        body: dict[str, object] | None,
        headers: Mapping[str, str],
    ) -> object: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        # The access token must never follow a redirect to another origin.
        return None


class HttpTransport:
    def request(
        self,
        method: str,
        url: str,
        body: dict[str, object] | None,
        headers: Mapping[str, str],
    ) -> object:
        opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
            _NoRedirect(),
        )
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            url,
            data=data,
            method=method,
            headers={
                "User-Agent": f"iOpenPod/{get_version()}",
                "Accept": "application/json",
                **({} if data is None else {"Content-Type": "application/json"}),
                **headers,
            },
        )
        try:
            with opener.open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as error:
            if 300 <= error.code < 400:
                raise JellyfinError(
                    "The Jellyfin address redirects elsewhere. Enter the final address, including http:// or https://."
                ) from None
            if error.code in (401, 403):
                raise JellyfinError(
                    "Jellyfin refused the sign-in. Check the username and password, or reconnect in Settings → Sync."
                ) from None
            raise JellyfinError(f"Jellyfin returned HTTP {error.code}.") from None
        except (URLError, OSError, TimeoutError, ValueError):
            raise JellyfinError(
                "Could not reach the Jellyfin server. Check the address and that the server is running."
            ) from None
        if len(raw) > MAX_RESPONSE:
            raise JellyfinError("The Jellyfin response exceeded its size limit.")
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise JellyfinError("Jellyfin returned an invalid JSON response.") from None


def normalize_server_url(value: str) -> str:
    """Accept ``host:port`` or a full http(s) base URL, including a base path."""
    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    invalid = JellyfinError(
        "Enter the Jellyfin server address, for example http://192.168.1.20:8096."
    )
    try:
        parts = urlsplit(candidate)
        _ = parts.port
    except ValueError:
        raise invalid from None
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise invalid
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _version(value: str) -> tuple[int, ...]:
    numbers: list[int] = []
    for part in value.split("."):
        digits = re.match(r"\d+", part)
        if digits is None:
            break
        numbers.append(int(digits.group()))
    return tuple(numbers)


def _authorization(device_id: str, token: str = "") -> str:
    """Build the only scheme Jellyfin 12 accepts by default.

    Jellyfin 12 disabled the legacy ``X-Emby-*`` headers and ``api_key`` query
    parameter. The server URL-decodes each quoted value (a raw ``+`` becomes a
    space), so every value is percent-encoded.
    """
    values = {
        "Client": _DEVICE_NAME,
        "Device": _DEVICE_NAME,
        "DeviceId": device_id,
        "Version": get_version(),
    }
    if token:
        values["Token"] = token
    fields = [f'{name}="{quote(value, safe="")}"' for name, value in values.items()]
    return "MediaBrowser " + ", ".join(fields)


def _track(item: object) -> JellyfinTrack:
    if not is_object(item):
        raise ValueError
    artists = item.get("Artists")
    names = (
        tuple(text(name) for name in artists)
        if is_array(artists)
        else ()
        if artists is None
        else None
    )
    if names is None:
        raise ValueError
    user_data = item.get("UserData")
    play_count = (
        optional_integer(user_data.get("PlayCount")) if is_object(user_data) else 0
    )
    ticks = optional_integer(item.get("RunTimeTicks"))
    item_id = text(item["Id"])
    if not _ITEM_ID.fullmatch(item_id) or play_count < 0 or ticks < 0:
        raise ValueError
    return JellyfinTrack(
        item_id=item_id,
        title=optional_text(item.get("Name")),
        album=optional_text(item.get("Album")),
        artists=names,
        album_artist=optional_text(item.get("AlbumArtist")),
        track_number=optional_integer(item.get("IndexNumber")),
        disc_number=optional_integer(item.get("ParentIndexNumber")),
        length_ms=ticks // 10_000,
        play_count=play_count,
    )


class JellyfinClient:
    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport or HttpTransport()

    def _call(
        self,
        method: str,
        url: str,
        body: dict[str, object] | None,
        device_id: str,
        token: str = "",
    ) -> object:
        return self._transport.request(
            method,
            url,
            body,
            {"Authorization": _authorization(device_id, token)},
        )

    def connect(
        self, server_url: str, username: str, password: str, device_id: str
    ) -> JellyfinAccount:
        """Check the server version, then exchange the password for a token."""
        url = normalize_server_url(server_url)
        info = self._call("GET", f"{url}/System/Info/Public", None, device_id)
        try:
            if not is_object(info):
                raise ValueError
            version = text(info["Version"])
            server_id = text(info["Id"])
        except (ValueError, KeyError):
            raise JellyfinError(
                "This address did not answer like a Jellyfin server."
            ) from None
        if _version(version)[:2] < MIN_VERSION:
            raise JellyfinError(
                f"Jellyfin {version} is too old. Play count sync needs Jellyfin 10.9 or later."
            )
        result = self._call(
            "POST",
            f"{url}/Users/AuthenticateByName",
            {"Username": username, "Pw": password},
            device_id,
        )
        try:
            if not is_object(result):
                raise ValueError
            token = text(result["AccessToken"])
            user = result["User"]
            if not is_object(user):
                raise ValueError
            user_id = text(user["Id"])
            name = text(user["Name"])
            if not token or not _ITEM_ID.fullmatch(user_id):
                raise ValueError
        except (ValueError, KeyError):
            raise JellyfinError(
                "Jellyfin returned an unexpected sign-in response."
            ) from None
        return JellyfinAccount(url, server_id, user_id, name, device_id, token)

    def tracks(
        self, account: JellyfinAccount, checkpoint: Callable[[], None]
    ) -> tuple[JellyfinTrack, ...]:
        """Read every audio item with the account's play counts."""
        found: dict[str, JellyfinTrack] = {}
        start = 0
        while True:
            checkpoint()
            query = urlencode(
                {
                    "userId": account.user_id,
                    "includeItemTypes": "Audio",
                    "recursive": "true",
                    "enableUserData": "true",
                    "enableImages": "false",
                    "sortBy": "SortName",
                    "startIndex": start,
                    "limit": PAGE_SIZE,
                }
            )
            page = self._call(
                "GET",
                f"{account.server_url}/Items?{query}",
                None,
                account.device_id,
                account.token,
            )
            try:
                if not is_object(page):
                    raise ValueError
                items = page["Items"]
                total = integer(page["TotalRecordCount"])
                if not is_array(items):
                    raise ValueError
                tracks = [_track(item) for item in items]
            except (ValueError, KeyError):
                raise JellyfinError(
                    "Jellyfin returned an unexpected music library response."
                ) from None
            # Pages can shift while the server library changes; keep each item once.
            for track in tracks:
                found[track.item_id] = track
            start += len(items)
            if not items or start >= total:
                return tuple(found.values())

    def set_play_count(
        self, account: JellyfinAccount, item_id: str, play_count: int
    ) -> None:
        if not _ITEM_ID.fullmatch(item_id) or not 0 < play_count <= MAX_PLAY_COUNT:
            raise JellyfinError("A play count could not be sent to Jellyfin.")
        query = urlencode({"userId": account.user_id})
        result = self._call(
            "POST",
            f"{account.server_url}/UserItems/{quote(item_id, safe='')}/UserData?{query}",
            {"PlayCount": play_count, "Played": True},
            account.device_id,
            account.token,
        )
        if is_object(result) and result.get("PlayCount", play_count) != play_count:
            raise JellyfinError("Jellyfin did not store the play count.")
