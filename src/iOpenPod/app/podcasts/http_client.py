"""HTTP policy shared by Podcast feeds, artwork and streamed media."""

from __future__ import annotations

import base64
import re
from http.client import HTTPException
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from iOpenPod.app.podcasts.errors import (
    PodcastAccessError,
    PodcastAccessFailure,
    PodcastFeedError,
)
from iOpenPod.app.podcasts.identity import normalize_feed_url

if TYPE_CHECKING:
    from http.client import HTTPMessage, HTTPResponse
    from typing import IO

    from iOpenPod.app.podcasts.credentials import PodcastAccess, PodcastCredentials


def _origin(url: str) -> tuple[str, str | None, int]:
    parsed = urlsplit(url)
    return (
        parsed.scheme,
        parsed.hostname,
        parsed.port
        if parsed.port is not None
        else (443 if parsed.scheme == "https" else 80),
    )


class _PodcastRedirects(HTTPRedirectHandler):
    def __init__(self, feed_url: str, authorization: str) -> None:
        self.feed_url = feed_url
        self.authorization = authorization

    def authorize(self, request: Request) -> None:
        if self.authorization and _origin(request.full_url) == _origin(self.feed_url):
            request.add_unredirected_header("Authorization", self.authorization)

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        normalized = normalize_feed_url(newurl)
        if not normalized:
            raise PodcastFeedError(
                "The Podcast request redirected to an unsupported URL."
            )
        if (
            urlsplit(req.full_url).scheme == "https"
            and urlsplit(normalized).scheme != "https"
        ):
            raise PodcastFeedError(
                "The Podcast server redirected from HTTPS to an insecure connection."
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, normalized)
        if redirected is not None:
            self.authorize(redirected)
        return redirected


def open_podcast_request(
    request: Request,
    *,
    timeout: int,
    feed_url: str = "",
    access: PodcastAccess | None = None,
    credentials: PodcastCredentials | None = None,
) -> HTTPResponse:
    """Open with at most one Basic retry, without global openers or shared headers.

    A credential belongs to one Subscription and its exact HTTPS origin. Public
    CDN redirects remain usable, but cannot receive or challenge for that login.
    Exceptions never include URLs, headers, server reason strings or response bodies.
    """
    url = normalize_feed_url(request.full_url)
    if not url:
        raise PodcastFeedError("Enter a valid HTTP or HTTPS podcast feed URL.")
    authority = normalize_feed_url(feed_url)
    login = credentials
    for attempt in range(2):
        authorization = ""
        if login is not None:
            if not authority or urlsplit(authority).scheme != "https":
                raise PodcastFeedError("Podcast logins require an HTTPS feed URL.")
            authorization = "Basic " + base64.b64encode(
                f"{login.username}:{login.password}".encode()
            ).decode("ascii")
        redirects = _PodcastRedirects(authority, authorization)
        outgoing = Request(url, headers=dict(request.header_items()))
        outgoing.remove_header("Authorization")
        redirects.authorize(outgoing)
        try:
            return cast(
                "HTTPResponse", build_opener(redirects).open(outgoing, timeout=timeout)
            )
        except HTTPError as error:
            status = error.code
            challenged_url = normalize_feed_url(error.url)
            challenge = error.headers.get("WWW-Authenticate", "")
            error.close()
            if status == 403:
                raise PodcastAccessError(PodcastAccessFailure.DENIED) from None
            if status != 401:
                raise PodcastFeedError(
                    "The Podcast server could not complete the request. Try again later."
                ) from None
            if (
                not authority
                or not challenged_url
                or _origin(challenged_url) != _origin(authority)
            ):
                raise PodcastAccessError(
                    PodcastAccessFailure.DIFFERENT_SERVER
                    if authority
                    else PodcastAccessFailure.REQUIRED
                ) from None
            if urlsplit(authority).scheme != "https":
                raise PodcastFeedError(
                    "Podcast logins require an HTTPS feed URL."
                ) from None
            if not re.search(r"(?:^|,)\s*Basic(?:\s|$)", challenge, re.IGNORECASE):
                raise PodcastAccessError(PodcastAccessFailure.UNSUPPORTED) from None
            if login is not None or attempt:
                raise PodcastAccessError(PodcastAccessFailure.REJECTED) from None
            login = access.load(authority) if access is not None else None
            if login is None:
                raise PodcastAccessError(PodcastAccessFailure.REQUIRED) from None
            url = challenged_url
        except (URLError, TimeoutError, OSError, HTTPException):
            raise PodcastFeedError(
                "The Podcast request failed. Check your connection and try again."
            ) from None
    raise AssertionError("Podcast authentication retry exhausted")
