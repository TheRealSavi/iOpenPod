"""Artwork provider contracts and bounded downloads use deterministic responses."""

import io
import json
from collections.abc import Callable
from http.client import HTTPMessage
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest
from PIL import Image

from iOpenPod.app import artwork_search as search
from iOpenPod.app.artwork_search import (
    ArtworkCandidate,
    ArtworkSearchClient,
    ArtworkSearchError,
    ArtworkSource,
    decode_artwork,
    request_bytes,
)

ITUNES_ROW = {
    "collectionName": "Album",
    "artistName": "Artist",
    "releaseDate": "2001-01-01T00:00:00Z",
    "collectionViewUrl": "https://music.apple.com/us/album/album/123",
    "artworkUrl100": "https://is1-ssl.mzstatic.com/image/cover/100x100bb.jpg",
}
DISCOGS_ROW = {
    "title": "Artist - Album",
    "year": "2001",
    "country": "Japan",
    "format": ["CD", "Album"],
    "uri": "/release/123-Artist-Album",
    "cover_image": "https://i.discogs.com/cover.jpg",
}


def image_bytes(size: tuple[int, int] = (3, 2)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize(
    "source,row",
    [(ArtworkSource.ITUNES, ITUNES_ROW), (ArtworkSource.DISCOGS, DISCOGS_ROW)],
)
def test_search_uses_provider_parameters_and_typed_results(
    monkeypatch: pytest.MonkeyPatch, source: ArtworkSource, row: dict[str, object]
) -> None:
    calls: list[tuple[str, str]] = []

    def fetch(
        url: str,
        *,
        hosts: tuple[str, ...],
        limit: int,
        checkpoint: Callable[[], None],
        token: str = "",
    ) -> bytes:
        checkpoint()
        calls.append((url, token))
        return json.dumps({"results": [row, row, None, {"title": "No cover"}]}).encode()

    monkeypatch.setattr(search, "request_bytes", fetch)
    found = ArtworkSearchClient().search(
        source,
        "Artist & Album 日本",
        country="jp",
        token="test-token",
        checkpoint=lambda: None,
    )
    assert len(found) == 1
    assert found[0].source is source
    params = parse_qs(urlsplit(calls[0][0]).query)
    if source is ArtworkSource.ITUNES:
        assert params["term"] == ["Artist & Album 日本"]
        assert params["entity"] == ["album"] and params["country"] == ["JP"]
        assert calls[0][1] == ""
        assert found[0].image_url.endswith("/1200x1200bb.jpg")
        assert found[0].fallback_url.endswith("/100x100bb.jpg")
        assert found[0].detail == "Artist · 2001"
    else:
        assert params["q"] == ["Artist & Album 日本"] and params["type"] == ["release"]
        assert calls[0][1] == "test-token"
        assert found[0].page_url == "https://www.discogs.com/release/123-Artist-Album"
        assert found[0].detail == "2001 · Japan · CD, Album"


@pytest.mark.parametrize("payload", [b"not-json", b"[]", b'{"results": {}}'])
def test_invalid_provider_data_is_reported(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    monkeypatch.setattr(search, "request_bytes", lambda *args, **kwargs: payload)
    with pytest.raises(ArtworkSearchError, match="invalid"):
        ArtworkSearchClient().search(
            ArtworkSource.ITUNES, "Album", checkpoint=lambda: None
        )


@pytest.mark.parametrize(
    "source,term,country,token",
    [
        (ArtworkSource.ITUNES, "", "US", ""),
        (ArtworkSource.ITUNES, "Album", "USA", ""),
        (ArtworkSource.DISCOGS, "Album", "US", ""),
    ],
)
def test_invalid_search_never_reaches_network(
    monkeypatch: pytest.MonkeyPatch,
    source: ArtworkSource,
    term: str,
    country: str,
    token: str,
) -> None:
    def unexpected(*args: object, **kwargs: object) -> bytes:
        pytest.fail("Invalid search reached the network")

    monkeypatch.setattr(search, "request_bytes", unexpected)
    with pytest.raises(ArtworkSearchError):
        ArtworkSearchClient().search(
            source, term, country=country, token=token, checkpoint=lambda: None
        )


def test_high_resolution_failure_falls_back_without_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    candidate = ArtworkCandidate(
        ArtworkSource.ITUNES,
        "Album",
        "Artist",
        "",
        "https://is1.mzstatic.com/1200x1200bb.jpg",
        "https://is1.mzstatic.com/100x100bb.jpg",
    )

    def fetch(
        url: str,
        *,
        hosts: tuple[str, ...],
        limit: int,
        checkpoint: Callable[[], None],
        token: str = "",
    ) -> bytes:
        assert not token
        calls.append(url)
        if len(calls) == 1:
            raise ArtworkSearchError("HTTP 404")
        return image_bytes()

    monkeypatch.setattr(search, "request_bytes", fetch)
    pixels = ArtworkSearchClient().load(candidate, checkpoint=lambda: None)
    assert calls == [candidate.image_url, candidate.fallback_url]
    assert (pixels.width, pixels.height) == (3, 2)


@pytest.mark.parametrize(
    "url",
    [
        "http://i.discogs.com/cover",
        "https://example.com/cover",
        "https://i.discogs.com.evil.test/cover",
        "https://secret@i.discogs.com/cover",
        "https://i.discogs.com:8080/cover",
    ],
)
def test_download_rejects_untrusted_urls_before_network(url: str) -> None:
    with pytest.raises(ArtworkSearchError, match="unsupported URL"):
        request_bytes(url, hosts=("i.discogs.com",), limit=100, checkpoint=lambda: None)


def test_redirect_cannot_send_token_to_another_origin() -> None:
    req = Request(
        "https://api.discogs.com/database/search",
        headers={"Authorization": "Discogs token=secret"},
    )
    with pytest.raises(ArtworkSearchError, match="redirected"):
        search._ProviderRedirects(("api.discogs.com",)).redirect_request(
            req,
            io.BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "https://sub.api.discogs.com/search",
        )


@pytest.mark.parametrize("payload", [b"not-an-image", image_bytes((8193, 1))])
def test_image_limits_and_decode_failures(payload: bytes) -> None:
    with pytest.raises(ArtworkSearchError):
        decode_artwork(payload, checkpoint=lambda: None)


def test_decode_applies_exif_orientation() -> None:
    stream = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (2, 3)).save(stream, format="JPEG", exif=exif)
    pixels = decode_artwork(stream.getvalue(), checkpoint=lambda: None)
    assert (pixels.width, pixels.height) == (3, 2)


def test_decode_cancellation_is_not_reported_as_an_image_error() -> None:
    def cancel() -> None:
        raise InterruptedError

    with pytest.raises(InterruptedError):
        decode_artwork(image_bytes(), checkpoint=cancel)


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, length: str = "") -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": length}


class _Opener:
    def __init__(self, response: _Response | HTTPError) -> None:
        self.response = response
        self.requests: list[Request] = []

    def open(self, req: Request, *, timeout: int) -> _Response:
        assert timeout == 10
        self.requests.append(req)
        if isinstance(self.response, HTTPError):
            raise self.response
        return self.response


@pytest.mark.parametrize("length", ["", "101"])
def test_stream_and_content_length_limits(
    monkeypatch: pytest.MonkeyPatch, length: str
) -> None:
    opener = _Opener(_Response(b"x" * 101, length))
    monkeypatch.setattr(search, "build_opener", lambda *args: opener)
    with pytest.raises(ArtworkSearchError, match="limit"):
        request_bytes(
            "https://i.discogs.com/cover",
            hosts=("i.discogs.com",),
            limit=100,
            checkpoint=lambda: None,
        )


def test_token_is_in_header_not_query_and_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://api.discogs.com/database/search?q=Album"
    opener = _Opener(HTTPError(url, 401, "secret-token", HTTPMessage(), None))
    monkeypatch.setattr(search, "build_opener", lambda *args: opener)
    with pytest.raises(ArtworkSearchError, match="rejected") as failure:
        request_bytes(
            url,
            hosts=("api.discogs.com",),
            limit=100,
            token="secret-token",
            checkpoint=lambda: None,
        )
    assert "secret-token" not in str(failure.value)
    assert "secret-token" not in opener.requests[0].full_url
    assert (
        opener.requests[0].get_header("Authorization") == "Discogs token=secret-token"
    )
