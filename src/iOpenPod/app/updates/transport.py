"""Bounded HTTPS transport for a fixed public update origin and release assets."""

from __future__ import annotations

import hashlib
import ssl
from time import monotonic
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

from .releases import MAX_METADATA, ReleaseAsset

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from threading import Event
    from typing import IO
    from urllib.response import addinfourl


_HOSTS = frozenset(
    {
        "raw.githubusercontent.com",
        "api.github.com",
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("Untrusted update URL")


class _Redirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        validate_url(newurl)
        # The stdlib implementation owns the redirect count and method handling.
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


class UpdateTransport:
    def _open(self, url: str) -> addinfourl:
        validate_url(url)
        opener = build_opener(
            _Redirects(),
            HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
        )
        try:
            return cast(
                "addinfourl",
                opener.open(
                    Request(
                        url,
                        headers={
                            "User-Agent": "iOpenPod-Updater/1",
                            "Accept": "application/json, application/octet-stream",
                            "Accept-Encoding": "identity",
                        },
                    ),
                    timeout=20,
                ),
            )
        except HTTPError as error:
            if error.code in (403, 429):
                raise OSError(
                    "The update server is rate-limiting requests; try again later"
                ) from error
            if error.code == 404:
                raise OSError(
                    "The signed update feed or release asset is not published yet"
                ) from error
            raise

    def metadata(self, url: str, cancel: Event) -> bytes:
        chunks: list[bytes] = []
        received = 0
        deadline = monotonic() + 45
        with self._open(url) as response:
            while True:
                if cancel.is_set():
                    raise InterruptedError("Update canceled")
                if monotonic() > deadline:
                    raise TimeoutError("Update metadata request timed out")
                chunk = cast(
                    "bytes", response.read1(min(64 * 1024, MAX_METADATA - received + 1))
                )
                if not chunk:
                    return b"".join(chunks)
                received += len(chunk)
                if received > MAX_METADATA:
                    raise ValueError("Update metadata exceeds its size limit")
                chunks.append(chunk)

    def download(
        self,
        asset: ReleaseAsset,
        path: Path,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None:
        digest = hashlib.sha256()
        received = 0
        deadline = monotonic() + 30 * 60
        with self._open(asset.url) as response, path.open("xb") as stream:
            while True:
                if cancel.is_set():
                    raise InterruptedError("Update canceled")
                if monotonic() > deadline:
                    raise TimeoutError("Update download exceeded 30 minutes")
                chunk = response.read1(min(256 * 1024, asset.size - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                if received > asset.size:
                    raise ValueError("Update download exceeds its signed size")
                stream.write(chunk)
                digest.update(chunk)
                progress(received / asset.size)
            if received != asset.size or digest.hexdigest() != asset.sha256:
                raise ValueError(
                    "Update download does not match its signed size and SHA-256"
                )
            import os

            stream.flush()
            os.fsync(stream.fileno())
