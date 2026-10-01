"""Current Last.fm and ListenBrainz HTTP contracts, without persistence or Qt."""

from __future__ import annotations

import hashlib
import json
import ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

from ._json import is_array, is_object
from .models import (
    Credentials,
    Listen,
    RejectedListen,
    ScrobbleError,
    Service,
    Submission,
)
from .reporting import single_line

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from threading import Event

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
LISTENBRAINZ_URL = "https://api.listenbrainz.org/1/"
MAX_RESPONSE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Response:
    data: dict[str, object]
    retry_after: float = 0


class Transport(Protocol):
    def request(
        self, url: str, data: bytes | None, headers: Mapping[str, str]
    ) -> Response: ...


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
        # Credentials must never follow a redirect to another origin.
        return None


class HttpTransport:
    def request(
        self, url: str, data: bytes | None, headers: Mapping[str, str]
    ) -> Response:
        opener = build_opener(
            HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
            _NoRedirect(),
        )
        request = Request(
            url,
            data=data,
            headers={
                "User-Agent": "iOpenPod/2.0 Scrobbler",
                **headers,
            },
        )
        try:
            with opener.open(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ScrobbleError("The service response exceeded its size limit.")
                delay = 0.0
                if response.headers.get("X-RateLimit-Remaining") == "0":
                    try:
                        delay = max(
                            1.0,
                            float(response.headers.get("X-RateLimit-Reset-In", "1")),
                        )
                    except ValueError:
                        delay = 1.0
        except HTTPError as error:
            if error.code == 429:
                raise ScrobbleError(
                    "Rate limit reached. Pending listens are saved; retry later."
                ) from None
            if error.code in (401, 403):
                raise ScrobbleError(
                    "Authorization was refused. Reconnect this service in Settings → Sync."
                ) from None
            raise ScrobbleError(
                f"Service returned HTTP {error.code}. Pending listens are saved."
            ) from None
        except (URLError, OSError, TimeoutError):
            raise ScrobbleError(
                "Could not reach the service. Check your connection and retry."
            ) from None
        try:
            result: object = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ScrobbleError(
                "The service returned an invalid JSON response."
            ) from None
        if not is_object(result):
            raise ScrobbleError("The service returned an unexpected response.")
        return Response(result, delay)


def _text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScrobbleError("The service response is missing required information.")
    return value


def _rejection_message(value: object, credentials: Credentials) -> str:
    if not isinstance(value, str):
        return ""
    # Retain the service's explanation without exposing reflected credentials.
    for secret in sorted(
        (credentials.token, credentials.api_key, credentials.api_secret),
        key=len,
        reverse=True,
    ):
        if secret:
            value = value.replace(secret, "[redacted]")
    return single_line(value)


def _match_scrobble(
    item: dict[str, object], entries: tuple[Listen, ...], remaining: set[int]
) -> int:
    """Match echoed identity; batch response positions are not request indices."""
    timestamp = str(item.get("timestamp"))
    if not timestamp.isdecimal() or len(timestamp) > 20:
        raise ScrobbleError(
            "Last.fm returned an acknowledgement without a valid playback timestamp."
        )
    candidates = {
        index for index in remaining if entries[index].timestamp == int(timestamp)
    }
    for field in ("artist", "track"):
        metadata = item.get(field)
        if not is_object(metadata) or not isinstance(metadata.get("#text"), str):
            raise ScrobbleError(
                "Last.fm returned an acknowledgement without Track identity."
            )
        corrected = str(metadata.get("corrected"))
        if corrected not in {"0", "1"}:
            raise ScrobbleError("Last.fm returned an invalid metadata correction flag.")
        if corrected == "0":
            candidates = {
                index
                for index in candidates
                if (
                    entries[index].artist if field == "artist" else entries[index].title
                )
                == metadata["#text"]
            }
    if not candidates or len({entries[index] for index in candidates}) != 1:
        raise ScrobbleError(
            "Last.fm acknowledgements could not be matched unambiguously to the submitted listens. Pending listens were retained."
        )
    return min(candidates)


class LastFmClient:
    batch_size = 50

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or HttpTransport()

    def _call(
        self, values: dict[str, str], secret: str, *, post: bool = False
    ) -> dict[str, object]:
        signature = "".join(key + values[key] for key in sorted(values)) + secret
        params = {
            **values,
            "api_sig": hashlib.md5(signature.encode("utf-8")).hexdigest(),
            "format": "json",
        }
        encoded = urlencode(params).encode("utf-8")
        result = self.transport.request(
            LASTFM_URL if post else LASTFM_URL + "?" + encoded.decode("ascii"),
            encoded if post else None,
            {"Content-Type": "application/x-www-form-urlencoded"},
        ).data
        if "error" in result:
            code = result["error"]
            remedies = {
                9: "Reconnect Last.fm in Settings → Sync.",
                14: "Authorize iOpenPod in your browser, then finish signing in.",
                15: "The authorization token expired. Start signing in again.",
                26: "This API key is suspended. Check your Last.fm application account.",
                29: "Rate limit reached. Retry later.",
                10: "Check your Last.fm API key.",
                13: "Check your Last.fm API shared secret.",
            }
            safe_code = code if isinstance(code, int) else 0
            raise ScrobbleError(
                f"Last.fm error {safe_code}. {remedies.get(safe_code, 'Pending listens are saved; retry later.')}"
            )
        return result

    def begin_auth(self, api_key: str, secret: str) -> tuple[str, str]:
        token = _text(
            self._call({"method": "auth.getToken", "api_key": api_key}, secret), "token"
        )
        return token, "https://www.last.fm/api/auth/?" + urlencode(
            {"api_key": api_key, "token": token}
        )

    def finish_auth(self, api_key: str, secret: str, token: str) -> Credentials:
        response = self._call(
            {"method": "auth.getSession", "api_key": api_key, "token": token}, secret
        )
        session = response.get("session")
        if not is_object(session):
            raise ScrobbleError("Last.fm did not return an authorized session.")
        return Credentials(
            _text(session, "name"), _text(session, "key"), api_key, secret
        )

    def submit(
        self, entries: tuple[Listen, ...], credentials: Credentials
    ) -> Submission:
        values = {
            "method": "track.scrobble",
            "api_key": credentials.api_key,
            "sk": credentials.token,
        }
        for index, entry in enumerate(entries):
            for name, value in {
                "artist": entry.artist,
                "track": entry.title,
                "album": entry.album,
                "timestamp": str(entry.timestamp),
                "duration": str(entry.duration),
                "albumArtist": entry.album_artist,
                "trackNumber": str(entry.track_number),
            }.items():
                if value:
                    values[f"{name}[{index}]"] = value
        response = self._call(values, credentials.api_secret, post=True)
        scrobbles = response.get("scrobbles")
        if not is_object(scrobbles):
            raise ScrobbleError("Last.fm did not acknowledge the submitted listens.")
        items = scrobbles.get("scrobble")
        if is_object(items):
            items = [items]
        if not is_array(items) or len(items) != len(entries):
            raise ScrobbleError(
                "Last.fm returned incomplete acknowledgements; listens remain pending."
            )
        accepted = [False] * len(entries)
        rejections: dict[int, RejectedListen] = {}
        remaining = set(range(len(entries)))
        for item in items:
            if not is_object(item):
                raise ScrobbleError("Last.fm returned an invalid acknowledgement.")
            ignored = item.get("ignoredMessage")
            if not is_object(ignored):
                raise ScrobbleError("Last.fm returned an invalid acknowledgement.")
            code = ignored.get("code")
            if str(code) not in {"0", "1", "2", "3", "4", "5"}:
                raise ScrobbleError("Last.fm returned an invalid acknowledgement.")
            index = _match_scrobble(item, entries, remaining)
            remaining.remove(index)
            accepted[index] = str(code) == "0"
            if str(code) != "0":
                rejections[index] = RejectedListen(
                    entries[index],
                    int(str(code)),
                    _rejection_message(ignored.get("#text"), credentials),
                )
        return Submission(
            tuple(accepted), tuple(rejections[index] for index in sorted(rejections))
        )


class ListenBrainzClient:
    batch_size = 100

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport or HttpTransport()
        self.retry_after = 0.0

    def validate_token(self, token: str) -> Credentials:
        result = self.transport.request(
            LISTENBRAINZ_URL + "validate-token",
            None,
            {"Authorization": f"Token {token}"},
        ).data
        if result.get("valid") is not True:
            raise ScrobbleError("ListenBrainz rejected this user token.")
        return Credentials(_text(result, "user_name"), token)

    def submit(
        self, entries: tuple[Listen, ...], credentials: Credentials
    ) -> Submission:
        payload: list[dict[str, object]] = []
        for entry in entries:
            item: dict[str, object] = {
                "listened_at": entry.timestamp,
                "track_metadata": {
                    "artist_name": entry.artist,
                    "track_name": entry.title,
                    "release_name": entry.album,
                    "additional_info": {
                        "duration": entry.duration,
                        "submission_client": "iOpenPod",
                        "submission_client_version": "2.0.0",
                    },
                },
            }
            if len(json.dumps(item).encode("utf-8")) > 10240:
                raise ScrobbleError(
                    "Track metadata exceeds ListenBrainz's listen size limit."
                )
            payload.append(item)
        response = self.transport.request(
            LISTENBRAINZ_URL + "submit-listens",
            json.dumps({"listen_type": "import", "payload": payload}).encode("utf-8"),
            {
                "Authorization": f"Token {credentials.token}",
                "Content-Type": "application/json",
            },
        )
        self.retry_after = response.retry_after
        if response.data.get("status") != "ok":
            raise ScrobbleError(
                "ListenBrainz did not acknowledge the submitted listens."
            )
        return Submission((True,) * len(entries))


class Submitter(Protocol):
    batch_size: int

    def submit(
        self, entries: tuple[Listen, ...], credentials: Credentials
    ) -> Submission: ...


def client_for(service: Service) -> Submitter:
    return LastFmClient() if service is Service.LASTFM else ListenBrainzClient()


def wait_between_batches(
    client: Submitter, cancelled: Event, checkpoint: Callable[[], None]
) -> bool:
    delay = client.retry_after if isinstance(client, ListenBrainzClient) else 1.0
    if delay > 60:
        raise ScrobbleError(
            "The service requested a longer pause. Retry pending listens later."
        )
    while delay > 0:
        checkpoint()
        step = min(delay, 0.25)
        if cancelled.wait(step):
            return False
        delay -= step
    return not cancelled.is_set()
