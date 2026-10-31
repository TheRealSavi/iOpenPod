"""Small 7z fixtures cover download-once, extracted-folder reuse and HTTP resume."""

from __future__ import annotations

import hashlib
import io
import plistlib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from py7zr import SevenZipFile

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.services.game_content import inspect_contents
from iOpenPod.app.services.game_download import (
    GameDownloadService,
    GameRelease,
    HTTPSGameTransport,
    release_manifest,
    validate_url,
)
from iOpenPod.app.services.game_installation import (
    GameInstallationPhase,
    GameInstallationProgress,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from urllib.response import addinfourl

    from py7zr.py7zr import FileInfo

URL = "https://github.com/Olsro/ipodclickwheelgamespreservationproject/releases/download/version16/iPod.Games.Files.7z"


class Transport:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    def download(
        self,
        source: GameRelease,
        destination: Path,
        checkpoint: Callable[[], None],
        progress: Callable[[GameInstallationProgress], None],
    ) -> None:
        self.calls += 1
        checkpoint()
        destination.write_bytes(self.data)
        progress(
            GameInstallationProgress(
                GameInstallationPhase.DOWNLOADING, len(self.data), source.size
            )
        )


def fixture(tmp_path: Path) -> tuple[GameDownloadService, Transport]:
    root = tmp_path / "fixture/iPod Games Files"
    pins: dict[str, str] = {}
    for identifier, group in (
        ("1D000", "All iPods"),
        ("12345", "iPod Videos (5G and 5.5G only)"),
    ):
        game = root / group / "iPod_Control/Games_RO" / identifier
        (game / "empty").mkdir(parents=True)
        (game / "Manifest.plist").write_bytes(
            plistlib.dumps({"Name": "Fixture", "GUID": identifier, "Version": "1.0"})
        )
        (game / "game.bin").write_bytes(b"fixture executable")
        pins[identifier.casefold()] = inspect_contents(game, lambda: None).sha256
    path = tmp_path / "source.7z"
    with SevenZipFile(path, "w") as archive:
        archive.writeall(root, "iPod Games Files")
    data = path.read_bytes()
    source = GameRelease(URL, len(data), hashlib.sha256(data).hexdigest(), pins)
    transport = Transport(data)
    return GameDownloadService(
        cache=tmp_path / "cache", source=source, transport=transport
    ), transport


def test_download_extracts_entire_collection_once_then_reuses_folder_without_source_archive(
    tmp_path: Path,
) -> None:
    service, transport = fixture(tmp_path)
    progress: list[GameInstallationProgress] = []
    root = service.prepare(lambda: None, progress.append)
    assert transport.calls == 1
    assert (
        root / "All iPods/iPod_Control/Games_RO/1D000/game.bin"
    ).read_bytes() == b"fixture executable"
    assert (
        root / "iPod Videos (5G and 5.5G only)/iPod_Control/Games_RO/12345/empty"
    ).is_dir()
    assert (service.cache / "ready.json").is_file()
    assert not list(service.cache.glob("*.zip"))
    (service.cache / "iPod.Games.Files.7z").unlink()
    progress.clear()
    assert service.prepare(lambda: None, progress.append) == root
    assert transport.calls == 1 and not progress
    classic = next(
        profile
        for profile in DEFAULT_DEVICE_REGISTRY.profiles
        if profile.model_number == "MB565"
    )
    packages = service.packages(classic, ("1D000",))
    assert len(packages) == 1 and packages[0].directory.is_dir()
    for invalid in ((), ("12345",), ("unknown",), ("1D000", "1d000")):
        with pytest.raises(ValueError):
            service.packages(classic, invalid)


def test_existing_complete_folder_can_rebuild_receipt_without_a_download(
    tmp_path: Path,
) -> None:
    service, transport = fixture(tmp_path)
    service.prepare(lambda: None, lambda _: None)
    (service.cache / "ready.json").unlink()
    (service.cache / "iPod.Games.Files.7z").unlink()
    service.prepare(lambda: None, lambda _: None)
    assert transport.calls == 1


@pytest.mark.parametrize("failure", ["source", "content", "cancel"])
def test_failed_preparation_does_not_publish_ready_folder(
    tmp_path: Path, failure: str
) -> None:
    service, transport = fixture(tmp_path)
    if failure == "source":
        transport.data = b"wrong source"
    elif failure == "content":
        service.source = replace(service.source, games={"1d000": "0" * 64})
    cancelled = False

    def checkpoint() -> None:
        if cancelled:
            raise InterruptedError("cancelled")

    def report(value: GameInstallationProgress) -> None:
        nonlocal cancelled
        if (
            failure == "cancel"
            and value.phase is GameInstallationPhase.EXTRACTING
            and value.current
        ):
            cancelled = True

    with pytest.raises((ValueError, InterruptedError)):
        service.prepare(checkpoint, report)
    assert not service.root.exists() and not (service.cache / "ready.json").exists()
    assert not list(service.cache.glob(".extract-*"))


def test_invalid_archive_path_is_rejected_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _transport = fixture(tmp_path)
    original = SevenZipFile.list

    def listing(archive: SevenZipFile) -> list[FileInfo]:
        rows = original(archive)
        rows[0] = replace(rows[0], filename="../outside")
        return rows

    monkeypatch.setattr(SevenZipFile, "list", listing)
    with pytest.raises(ValueError):
        service.prepare(lambda: None, lambda _: None)
    assert not service.root.exists() and not (tmp_path / "outside").exists()


def test_shipped_manifest_has_small_content_pins_and_no_packaged_payloads() -> None:
    source = release_manifest()
    assert source.url == URL and source.size == 1800542124 and len(source.games) == 56
    root = Path("src/iOpenPod/assets/games")
    assert (root / "game-catalog.json").is_file()
    assert not list(root.rglob("*.zip")) and not list(root.rglob("*.7z"))


class Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200, content_range: str = "") -> None:
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Range": content_range}


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("ignore_range", [False, True])
def test_https_download_publishes_verified_complete_file_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool, ignore_range: bool
) -> None:
    data = b"complete archive fixture"
    source = GameRelease(URL, len(data), hashlib.sha256(data).hexdigest(), {})
    path = tmp_path / "source.7z"
    part = path.with_suffix(".7z.part")
    if resume:
        part.write_bytes(data[:4])
    offsets: list[int] = []

    def open_url(_url: str, offset: int) -> addinfourl:
        offsets.append(offset)
        response = (
            Response(data[4:], 206, f"bytes 4-{len(data) - 1}/{len(data)}")
            if resume and not ignore_range
            else Response(data)
        )
        return cast("addinfourl", response)

    transport = HTTPSGameTransport()
    monkeypatch.setattr(transport, "_open", open_url)
    transport.download(source, path, lambda: None, lambda _: None)
    assert path.read_bytes() == data and not part.exists()
    assert offsets == [4 if resume else 0]


@pytest.mark.parametrize("failure", ["short", "hash", "range", "oversize"])
def test_failed_http_download_never_becomes_a_ready_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    source = GameRelease(URL, 6, hashlib.sha256(b"123456").hexdigest(), {})
    path = tmp_path / "source.7z"
    part = path.with_suffix(".7z.part")
    if failure == "range":
        part.write_bytes(b"12")
    response = (
        Response(b"12")
        if failure == "short"
        else Response(b"abcdef")
        if failure == "hash"
        else Response(b"3456", 206, "bad range")
        if failure == "range"
        else Response(b"1234567")
    )

    def open_url(_url: str, _offset: int) -> addinfourl:
        return cast("addinfourl", response)

    transport = HTTPSGameTransport()
    monkeypatch.setattr(transport, "_open", open_url)
    with pytest.raises((ValueError, OSError)):
        transport.download(source, path, lambda: None, lambda _: None)
    assert not path.exists()
    if failure == "short":
        assert part.read_bytes() == b"12"  # Incomplete data is retained for retry.


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/file",
        "https://evil.example/file",
        "https://github.com@evil.example/file",
        "https://user:password@github.com/file",
    ],
)
def test_download_origin_is_restricted(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)
