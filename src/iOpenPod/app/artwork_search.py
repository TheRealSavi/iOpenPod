"""User-directed album searches and bounded remote cover decoding."""

from __future__ import annotations

import io
import json
import re
import ssl
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi
from PIL import Image, ImageOps, UnidentifiedImageError

from iOpenPod.app.display_text import source_text
from iPodDB.library import ArtworkPixels

if TYPE_CHECKING:
    from collections.abc import Callable
    from http.client import HTTPMessage
    from typing import IO

_JSON_LIMIT = 2 * 1024 * 1024
_IMAGE_LIMIT = 32 * 1024 * 1024
_USER_AGENT = "iOpenPod/2 (https://github.com/TheRealSavi/iOpenPod)"


class ArtworkSource(StrEnum):
    ITUNES = "itunes"
    DISCOGS = "discogs"


class ArtworkSearchError(ValueError):
    """A provider could not supply usable search results or cover pixels."""


@dataclass(frozen=True, slots=True)
class ArtworkCandidate:
    source: ArtworkSource
    title: str
    detail: str
    page_url: str
    image_url: str
    fallback_url: str = ""


def _allowed_url(url: str, hosts: tuple[str, ...]) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        return (
            parts.scheme == "https"
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and any(host == name or host.endswith("." + name) for name in hosts)
        )
    except ValueError:
        return False


class _ProviderRedirects(HTTPRedirectHandler):
    def __init__(self, hosts: tuple[str, ...]) -> None:
        super().__init__()
        self.hosts = hosts

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        if not _allowed_url(newurl, self.hosts):
            raise ArtworkSearchError(
                "The artwork service redirected outside its provider."
            )
        # Authentication is tied to the exact Discogs API origin.
        if (
            req.has_header("Authorization")
            and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc
        ):
            raise ArtworkSearchError(
                "The authenticated request redirected to another host."
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_bytes(
    url: str,
    *,
    hosts: tuple[str, ...],
    limit: int,
    checkpoint: Callable[[], None],
    token: str = "",
) -> bytes:
    """Keep downloads on provider HTTPS origins, with size and time limits."""

    if not _allowed_url(url, hosts):
        raise ArtworkSearchError("The artwork service returned an unsupported URL.")
    headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"}
    if token:
        if urlsplit(url).hostname != "api.discogs.com" or not re.fullmatch(
            r"[A-Za-z0-9_-]+", token
        ):
            raise ArtworkSearchError("Enter a valid Discogs personal access token.")
        headers["Authorization"] = "Discogs token=" + token
    opener = build_opener(
        _ProviderRedirects(hosts),
        HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
    )
    deadline = monotonic() + 30

    def check() -> None:
        checkpoint()
        if monotonic() > deadline:
            raise ArtworkSearchError("The artwork request timed out. Try again.")

    try:
        check()
        with opener.open(Request(url, headers=headers), timeout=10) as response:
            check()
            length = response.headers.get("Content-Length", "")
            if length.isascii() and length.isdigit() and int(length) > limit:
                raise ArtworkSearchError(
                    "The artwork response exceeds the download limit."
                )
            read = cast(
                "Callable[[int], bytes]", getattr(response, "read1", response.read)
            )
            payload = bytearray()
            while len(payload) <= limit:
                check()
                chunk = read(min(64 * 1024, limit + 1 - len(payload)))
                check()
                if not chunk:
                    break
                payload.extend(chunk)
    except HTTPError as error:
        if error.code in (401, 403) and token:
            raise ArtworkSearchError(
                "Discogs rejected the token. Check your personal access token."
            ) from None
        if error.code == 429:
            raise ArtworkSearchError(
                "The service is rate limited. Wait before searching again."
            ) from None
        raise ArtworkSearchError(
            source_text(
                "The artwork service returned HTTP {status}.", status=str(error.code)
            )
        ) from None
    except InterruptedError:
        raise
    except (URLError, TimeoutError, OSError):
        raise ArtworkSearchError(
            "Could not reach the artwork service. Check your connection and try again."
        ) from None
    if not payload or len(payload) > limit:
        raise ArtworkSearchError(
            "The artwork response is empty or exceeds the download limit."
        )
    return bytes(payload)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


class ArtworkSearchClient:
    """Read provider metadata and images; never touch a Library or device."""

    def search(
        self,
        source: ArtworkSource,
        term: str,
        *,
        country: str = "US",
        token: str = "",
        checkpoint: Callable[[], None],
    ) -> tuple[ArtworkCandidate, ...]:
        term = term.strip()
        if not term or len(term) > 300:
            raise ArtworkSearchError(
                "Enter an artist and album name (up to 300 characters)."
            )
        if source is ArtworkSource.ITUNES:
            country = country.strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", country):
                raise ArtworkSearchError(
                    "Enter a two-letter iTunes Store region, such as US or JP."
                )
            url = "https://itunes.apple.com/search?" + urlencode(
                {
                    "term": term,
                    "country": country,
                    "media": "music",
                    "entity": "album",
                    "limit": 25,
                }
            )
            hosts = ("itunes.apple.com",)
            token = ""
        else:
            token = token.strip()
            if not token:
                raise ArtworkSearchError(
                    "Enter your Discogs personal access token to search."
                )
            url = "https://api.discogs.com/database/search?" + urlencode(
                {"q": term, "type": "release", "per_page": 25, "page": 1}
            )
            hosts = ("api.discogs.com",)
        payload = request_bytes(
            url, hosts=hosts, limit=_JSON_LIMIT, token=token, checkpoint=checkpoint
        )
        checkpoint()
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeError):
            raise ArtworkSearchError(
                "The artwork service returned invalid search data."
            ) from None
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ArtworkSearchError(
                "The artwork service returned invalid search results."
            )
        found: list[ArtworkCandidate] = []
        seen: set[str] = set()
        for row in data["results"][:25]:
            checkpoint()
            if not isinstance(row, dict):
                continue
            candidate = self._candidate(source, row)
            if candidate is not None and candidate.image_url not in seen:
                found.append(candidate)
                seen.add(candidate.image_url)
        return tuple(found)

    def _candidate(
        self, source: ArtworkSource, row: dict[str, object]
    ) -> ArtworkCandidate | None:
        image_hosts: tuple[str, ...]
        page_hosts: tuple[str, ...]
        if source is ArtworkSource.ITUNES:
            title = _text(row.get("collectionName"))
            original = _text(row.get("artworkUrl100"))
            image = re.sub(r"/\d+x\d+bb(?=\.)", "/1200x1200bb", original)
            page = _text(row.get("collectionViewUrl"))
            detail = " · ".join(
                value
                for value in (
                    _text(row.get("artistName")),
                    _text(row.get("releaseDate"))[:4],
                )
                if value
            )
            image_hosts = ("mzstatic.com",)
            page_hosts = ("music.apple.com", "itunes.apple.com")
        else:
            title = _text(row.get("title"))
            image = _text(row.get("cover_image"))
            original = ""
            uri = _text(row.get("uri"))
            page = "https://www.discogs.com" + uri if uri.startswith("/") else uri
            formats = row.get("format")
            format_text = (
                ", ".join(value for value in formats if isinstance(value, str))
                if isinstance(formats, list)
                else ""
            )
            detail = " · ".join(
                value
                for value in (
                    str(row["year"]) if isinstance(row.get("year"), (str, int)) else "",
                    _text(row.get("country")),
                    format_text,
                )
                if value
            )
            image_hosts = ("i.discogs.com", "img.discogs.com")
            page_hosts = ("discogs.com",)
        if not title or not _allowed_url(image, image_hosts):
            return None
        if not _allowed_url(page, page_hosts):
            page = ""
        return ArtworkCandidate(
            source, title, detail, page, image, original if original != image else ""
        )

    def load(
        self, candidate: ArtworkCandidate, *, checkpoint: Callable[[], None]
    ) -> ArtworkPixels:
        hosts = (
            ("mzstatic.com",)
            if candidate.source is ArtworkSource.ITUNES
            else ("i.discogs.com", "img.discogs.com")
        )
        try:
            payload = request_bytes(
                candidate.image_url,
                hosts=hosts,
                limit=_IMAGE_LIMIT,
                checkpoint=checkpoint,
            )
            return decode_artwork(payload, checkpoint=checkpoint)
        except ArtworkSearchError:
            if not candidate.fallback_url:
                raise
        checkpoint()
        payload = request_bytes(
            candidate.fallback_url,
            hosts=hosts,
            limit=_IMAGE_LIMIT,
            checkpoint=checkpoint,
        )
        return decode_artwork(payload, checkpoint=checkpoint)


def decode_artwork(payload: bytes, *, checkpoint: Callable[[], None]) -> ArtworkPixels:
    """Decode owned RGB pixels only after validating image dimensions."""

    if len(payload) > _IMAGE_LIMIT:
        raise ArtworkSearchError("The artwork exceeds the download limit.")
    try:
        checkpoint()
        with Image.open(io.BytesIO(payload)) as opened:
            width, height = opened.size
            if (
                width <= 0
                or height <= 0
                or max(width, height) > 8192
                or width * height > 32 * 1024 * 1024
            ):
                raise ArtworkSearchError(
                    "Artwork must be at most 8192 pixels per side and 32 megapixels."
                )
            checkpoint()
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
            checkpoint()
            return ArtworkPixels(rgb.width, rgb.height, rgb.tobytes())
    except InterruptedError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError):
        raise ArtworkSearchError(
            "The downloaded artwork could not be decoded."
        ) from None
