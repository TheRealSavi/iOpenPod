"""Download and extract the complete preservation collection once on the Host."""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Protocol, cast
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

import certifi
from py7zr import Py7zIO, SevenZipFile, WriterFactory

from iOpenPod.app.core.settings.paths import default_games_cache_path
from iOpenPod.app.services.game_catalog import catalog_games
from iOpenPod.app.services.game_content import inspect_contents
from iOpenPod.app.services.game_installation import (
    GameInstallationPhase,
    GameInstallationProgress,
    GamePackage,
)
from storage import DevicePath
from storage.host_files import lock_host_file
from storage.host_installation import require_plain_path

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import IO, BinaryIO
    from urllib.response import addinfourl

    from device_registry import DeviceProfile

_HOSTS = frozenset(
    {
        "github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
_BLOCK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class GameRelease:
    url: str
    size: int
    sha256: str
    games: dict[str, str]


def release_manifest() -> GameRelease:
    raw: object = json.loads(
        files("iOpenPod").joinpath("assets/games/game-downloads.json").read_bytes()
    )
    if not isinstance(raw, dict):
        raise ValueError("Invalid game download manifest.")
    data = cast("dict[str, object]", raw)
    url, size, digest, rows = (
        data.get("url"),
        data.get("size"),
        data.get("sha256"),
        data.get("games"),
    )
    if (
        not isinstance(url, str)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 < size <= 3 * 1024**3
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(rows, list)
        or data.get("version") != 1
    ):
        raise ValueError("Invalid game download manifest.")
    validate_url(url)
    games: dict[str, str] = {}
    for item in cast("list[object]", rows):
        if not isinstance(item, dict):
            raise ValueError("Invalid game content record.")
        row = cast("dict[str, object]", item)
        identifier, fingerprint = row.get("identifier"), row.get("content_sha256")
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[0-9a-fA-F]{1,16}", identifier) is None
            or not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
            or identifier.casefold() in games
        ):
            raise ValueError("Invalid game content record.")
        games[identifier.casefold()] = fingerprint
    return GameRelease(url, size, digest, games)


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
        raise ValueError("Untrusted game download URL.")


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
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


class GameTransport(Protocol):
    def download(
        self,
        source: GameRelease,
        destination: Path,
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
    ) -> None: ...


class HTTPSGameTransport:
    """Resume a bounded partial file and verify it before atomic publication."""

    def _open(self, url: str, offset: int) -> addinfourl:
        validate_url(url)
        headers = {"User-Agent": "iOpenPod-Games/1", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        opener = build_opener(
            _Redirects(),
            HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
        )
        return cast(
            "addinfourl", opener.open(Request(url, headers=headers), timeout=30)
        )

    def download(
        self,
        source: GameRelease,
        destination: Path,
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
    ) -> None:
        part = destination.with_suffix(".7z.part")
        require_plain_path(part)
        offset = part.stat().st_size if part.exists() else 0
        if offset > source.size:
            part.unlink()
            offset = 0
        checkpoint()
        if offset != source.size:
            try:
                response = self._open(source.url, offset)
            except HTTPError as error:
                raise OSError(
                    f"Game archive download failed (HTTP {error.code})."
                ) from error
            with response:
                status = response.status
                if offset and status == 206:
                    expected = f"bytes {offset}-{source.size - 1}/{source.size}"
                    if response.headers.get("Content-Range") != expected:
                        raise ValueError(
                            "The game download returned an invalid resume range."
                        )
                elif status == 200:
                    offset = 0
                else:
                    raise ValueError(
                        "The game download returned an unexpected response."
                    )
                with part.open("ab" if offset else "wb") as output:
                    while block := response.read1(
                        min(_BLOCK, source.size - offset + 1)
                    ):
                        checkpoint()
                        offset += len(block)
                        if offset > source.size:
                            raise ValueError(
                                "Game archive exceeds its expected download size."
                            )
                        output.write(block)
                        progress(
                            GameInstallationProgress(
                                GameInstallationPhase.DOWNLOADING, offset, source.size
                            )
                        )
                    output.flush()
                    os.fsync(output.fileno())
            if offset != source.size:
                raise OSError(
                    "The game archive download was interrupted; retry to resume it."
                )
        if not _verified_asset(part, source, checkpoint):
            part.unlink(missing_ok=True)
            raise ValueError(
                "The game download failed its size or SHA-256 verification."
            )
        part.replace(destination)


def _sha256(path: Path, checkpoint: Callable[[], None]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_BLOCK):
            checkpoint()
            digest.update(block)
    return digest.hexdigest()


def _verified_asset(
    path: Path, source: GameRelease, checkpoint: Callable[[], None]
) -> bool:
    require_plain_path(path)
    return (
        path.is_file()
        and path.stat().st_size == source.size
        and _sha256(path, checkpoint) == source.sha256
    )


class _FileSink(Py7zIO):
    def __init__(
        self,
        stream: BinaryIO,
        limit: int,
        checkpoint: Callable[[], None],
        update: Callable[[int], None],
    ) -> None:
        self.stream, self.limit, self.checkpoint, self.update = (
            stream,
            limit,
            checkpoint,
            update,
        )
        self.written = 0

    def write(self, s: bytes | bytearray) -> int:
        self.checkpoint()
        if self.stream.tell() + len(s) > self.limit:
            raise ValueError("A game file exceeds its declared extraction size.")
        count = self.stream.write(s)
        self.written += count
        self.update(count)
        return count

    def read(self, size: int | None = None) -> bytes:
        return self.stream.read(-1 if size is None else size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    def flush(self) -> None:
        self.stream.flush()

    def size(self) -> int:
        return self.written

    def close(self) -> None:
        if self.written != self.limit:
            raise ValueError("A game file was not completely extracted.")
        self.stream.close()


class _Factory(WriterFactory):
    def __init__(
        self,
        workspace: Path,
        limits: dict[str, int],
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
        stack: ExitStack,
    ) -> None:
        self.workspace, self.limits, self.checkpoint, self.progress, self.stack = (
            workspace,
            limits,
            checkpoint,
            progress,
            stack,
        )
        self.paths: dict[str, Path] = {}
        self.total = sum(limits.values())
        self.done = 0

    def _update(self, count: int) -> None:
        self.done += count
        self.progress(
            GameInstallationProgress(
                GameInstallationPhase.EXTRACTING, self.done, self.total
            )
        )

    def create(self, filename: str) -> Py7zIO:
        if filename not in self.limits or filename in self.paths:
            raise ValueError("Unexpected game extraction target.")
        path = self.workspace.joinpath(*DevicePath(filename).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        require_plain_path(path)
        self.paths[filename] = path
        stream = self.stack.enter_context(path.open("xb+"))
        return _FileSink(stream, self.limits[filename], self.checkpoint, self._update)


class GameDownloadService:
    """One download and one persistent extracted Host collection."""

    def __init__(
        self,
        *,
        cache: Path | None = None,
        source: GameRelease | None = None,
        transport: GameTransport | None = None,
    ) -> None:
        self.cache = cache if cache is not None else default_games_cache_path()
        self.source = source if source is not None else release_manifest()
        self.transport = transport if transport is not None else HTTPSGameTransport()
        self.root = self.cache / "files"

    def _receipt(self) -> dict[str, str]:
        pin = hashlib.sha256(
            json.dumps(self.source.games, sort_keys=True).encode()
        ).hexdigest()
        return {"source_sha256": self.source.sha256, "index_sha256": pin}

    def _folder(self, identifier: str, *, root: Path | None = None) -> Path:
        base = self.root if root is None else root
        matches: list[Path] = []
        for group in ("All iPods", "iPod Videos (5G and 5.5G only)"):
            parent = base / group / "iPod_Control/Games_RO"
            if parent.exists():
                require_plain_path(parent)
                matches.extend(
                    path
                    for path in parent.iterdir()
                    if path.name.casefold() == identifier.casefold()
                )
        if len(matches) != 1:
            raise ValueError("A cached game folder is missing or ambiguous.")
        require_plain_path(matches[0])
        return matches[0]

    def _ready(self) -> bool:
        marker = self.cache / "ready.json"
        if not marker.is_file() or not self.root.is_dir():
            return False
        require_plain_path(marker)
        require_plain_path(self.root)
        try:
            if (
                marker.stat().st_size > 4096
                or json.loads(marker.read_bytes()) != self._receipt()
            ):
                return False
            return all(
                (self._folder(key) / "Manifest.plist").is_file()
                for key in self.source.games
            )
        except (ValueError, FileNotFoundError):
            return False

    def _write_receipt(self) -> None:
        target = self.cache / "ready.json"
        require_plain_path(target)
        temporary = self.cache / f"{uuid4().hex}.receipt"
        try:
            with temporary.open("xb") as stream:
                stream.write(json.dumps(self._receipt()).encode())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def _validate_tree(
        self,
        root: Path,
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
    ) -> None:
        for index, (identifier, expected) in enumerate(self.source.games.items()):
            checkpoint()
            progress(
                GameInstallationProgress(
                    GameInstallationPhase.VERIFYING, index, len(self.source.games)
                )
            )
            if (
                inspect_contents(self._folder(identifier, root=root), checkpoint).sha256
                != expected
            ):
                raise ValueError(
                    f"The extracted game files failed verification: {identifier}."
                )
        progress(
            GameInstallationProgress(
                GameInstallationPhase.VERIFYING,
                len(self.source.games),
                len(self.source.games),
            )
        )

    def prepare(
        self,
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
    ) -> Path:
        checkpoint()
        ancestor = self.cache
        while not ancestor.exists():
            ancestor = ancestor.parent
        require_plain_path(ancestor)
        self.cache.mkdir(parents=True, exist_ok=True)
        require_plain_path(self.cache)
        with lock_host_file(self.cache / ".cache-lock"):
            if self._ready():
                return self.root
            if self.root.exists():
                require_plain_path(self.root)
                try:
                    self._validate_tree(self.root, checkpoint, progress)
                except ValueError:
                    pass
                else:
                    self._write_receipt()
                    return self.root
            asset = self.cache / "iPod.Games.Files.7z"
            progress(GameInstallationProgress(GameInstallationPhase.PREPARING))
            if not _verified_asset(asset, self.source, checkpoint):
                self.transport.download(self.source, asset, checkpoint, progress)
                if not _verified_asset(asset, self.source, checkpoint):
                    raise ValueError("The game source archive failed verification.")
            with TemporaryDirectory(prefix=".extract-", dir=self.cache) as temporary:
                workspace = Path(temporary)
                if not workspace.resolve().is_relative_to(self.cache.resolve()):
                    raise ValueError("Invalid game extraction workspace.")
                self._extract(asset, workspace, checkpoint, progress)
                prepared = workspace / "iPod Games Files"
                self._validate_tree(prepared, checkpoint, progress)
                checkpoint()
                progress(GameInstallationProgress(GameInstallationPhase.FINALIZING))
                if self.root.exists():
                    self.root.rename(self.cache / f"incomplete-{uuid4().hex}")
                prepared.rename(self.root)
                self._write_receipt()
            return self.root

    def packages(
        self, profile: DeviceProfile, identifiers: tuple[str, ...]
    ) -> tuple[GamePackage, ...]:
        requested = {value.casefold() for value in identifiers}
        offered = {game.directory.casefold(): game for game in catalog_games(profile)}
        if (
            not requested
            or len(requested) != len(identifiers)
            or not requested <= offered.keys()
            or not requested <= self.source.games.keys()
        ):
            raise ValueError("Select compatible, available games without duplicates.")
        if not self._ready():
            raise ValueError("Prepare the game files with Gimme Games first.")
        return tuple(
            GamePackage(
                offered[value.casefold()].directory,
                offered[value.casefold()].version,
                self._folder(value),
                self.source.games[value.casefold()],
                offered[value.casefold()].title,
            )
            for value in identifiers
        )

    def _extract(
        self,
        asset: Path,
        workspace: Path,
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
    ) -> None:
        progress(GameInstallationProgress(GameInstallationPhase.EXTRACTING))
        with (
            ExitStack() as stack,
            asset.open("rb") as raw,
            SevenZipFile(raw, "r", max_extract_size=4 * 1024**3) as archive,
        ):
            rows = archive.list()
            if (
                archive.needs_password()
                or len(rows) > 30_000
                or sum(row.uncompressed for row in rows) > 4 * 1024**3
            ):
                raise ValueError(
                    "The game release exceeds its supported extraction bounds."
                )
            limits: dict[str, int] = {}
            directories: list[str] = []
            seen: set[str] = set()
            for row in rows:
                checkpoint()
                path = DevicePath(row.filename)
                if (
                    path.parts[0] != "iPod Games Files"
                    or chr(92) in row.filename
                    or row.filename.casefold() in seen
                    or row.is_symlink
                    or not (row.is_file or row.is_directory)
                ):
                    raise ValueError("Unsafe or duplicate path in the game release.")
                seen.add(row.filename.casefold())
                if row.is_file:
                    limits[row.filename] = row.uncompressed
                else:
                    directories.append(row.filename)
            for name in directories:
                target = workspace.joinpath(*DevicePath(name).parts)
                target.mkdir(parents=True, exist_ok=True)
                require_plain_path(target)
            factory = _Factory(workspace, limits, checkpoint, progress, stack)
            archive.extract(targets=list(limits), factory=factory)


def resolve_packages(
    profile: DeviceProfile, identifiers: tuple[str, ...]
) -> tuple[GamePackage, ...]:
    return GameDownloadService().packages(profile, identifiers)
