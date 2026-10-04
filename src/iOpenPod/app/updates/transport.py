"""Bounded HTTPS transport for a fixed public update origin and release assets."""

from __future__ import annotations

import hashlib
import ssl
from time import monotonic
from typing import TYPE_CHECKING, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

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


def validate_url(url: str, hosts: frozenset[str] = _HOSTS) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("Untrusted update URL")


class _Redirects(HTTPRedirectHandler):
    def __init__(self, hosts: frozenset[str] = _HOSTS) -> None:
        super().__init__()
        self._hosts = hosts

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        validate_url(newurl, self._hosts)
        # The stdlib implementation owns the redirect count and method handling.
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


class DownloadAsset(Protocol):
    @property
    def filename(self) -> str: ...

    @property
    def url(self) -> str: ...

    @property
    def size(self) -> int: ...

    @property
    def sha256(self) -> str: ...


class UpdateTransport:
    def __init__(
        self,
        *,
        hosts: frozenset[str] = _HOSTS,
        metadata_limit: int | None = None,
        accept: str = "application/json, application/octet-stream",
    ) -> None:
        if metadata_limit is None:
            # PyPI's independent helper must not load the standalone signature
            # runtime's native libraries while their package may be replaced.
            from .releases import MAX_METADATA

            metadata_limit = MAX_METADATA
        self._hosts = hosts
        self._metadata_limit = metadata_limit
        self._accept = accept

    def _open(self, url: str) -> addinfourl:
        validate_url(url, self._hosts)
        opener = build_opener(
            _Redirects(self._hosts),
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
                            "Accept": self._accept,
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
                    "The update metadata or release asset is not published yet"
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
                    "bytes",
                    response.read1(min(64 * 1024, self._metadata_limit - received + 1)),
                )
                if not chunk:
                    return b"".join(chunks)
                received += len(chunk)
                if received > self._metadata_limit:
                    raise ValueError("Update metadata exceeds its size limit")
                chunks.append(chunk)

    def download(
        self,
        asset: DownloadAsset,
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
                    raise ValueError("Update download exceeds its expected size")
                stream.write(chunk)
                digest.update(chunk)
                progress(received / asset.size)
            if received != asset.size or digest.hexdigest() != asset.sha256:
                raise ValueError(
                    "Update download does not match its expected size and SHA-256"
                )
            import os

            stream.flush()
            os.fsync(stream.fileno())
