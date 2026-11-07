"""Video container covers retain priority and their original image identity."""

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    HostMediaArtworkLoader,
    HostMediaLibrary,
    HostMediaScanner,
)
from iOpenPod.app.media.container_artwork import container_artwork
from iOpenPod.app.media.sync_artwork import capture_sync_artwork
from iOpenPod.app.models.artwork import ArtworkRequest
from storage import AtomicHostFile, HostPath
from storage.host_input import LocalHostFile


class _Fingerprinter:
    def fingerprint(self, source: HostPath, *, checkpoint: Callable[[], None]) -> str:
        del source
        checkpoint()
        return "1,2,3"


def _video(tmp_path: Path, extension: str | None) -> tuple[Path, bytes | None]:
    executable = shutil.which("ffmpeg")
    if executable is None or shutil.which("ffprobe") is None:
        pytest.skip("Container artwork tests require FFmpeg and FFprobe")
    folder = tmp_path / "Videos"
    folder.mkdir()
    video = folder / "episode.mkv"
    image = tmp_path / f"embedded{extension}"
    if extension:
        Image.new("RGB", (12, 8), "red").save(image)
    subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=64x32:r=10:d=0.2",
            "-c:v",
            "ffv1",
            *(
                [
                    "-attach",
                    str(image),
                    "-metadata:s:t:0",
                    f"mimetype=image/{'jpeg' if extension == '.jpg' else 'png'}",
                    "-metadata:s:t:0",
                    f"filename=cover{extension}",
                ]
                if extension
                else []
            ),
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    return video, image.read_bytes() if extension else None


def _scan(folder: Path, cache: AtomicHostFile | None = None) -> HostMediaLibrary:
    scanner = HostMediaScanner(cache, _Fingerprinter())
    pending = scanner.scan((create_host_media_folder(folder),), checkpoint=lambda: None)
    return scanner.complete(pending, frozenset(), checkpoint=lambda: None)


@pytest.mark.parametrize("extension", [".jpg", ".png"])
def test_matroska_embedded_cover_beats_folder_and_survives_preview_and_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    video, payload = _video(tmp_path, extension)
    assert payload is not None
    Image.new("RGB", (12, 8), "blue").save(video.parent / "cover.jpg")
    Image.new("RGB", (12, 8), "yellow").save(video.parent / "poster.jpg")
    cache = AtomicHostFile(tmp_path / "cache.json")

    def no_capture(*args: object, **kwargs: object) -> None:
        pytest.fail("Reading an embedded cover must not copy the entire video")

    monkeypatch.setattr(LocalHostFile, "capture", no_capture)
    host = _scan(video.parent, cache)
    source = host.artwork_sources[0]
    assert source.kind is HostArtworkKind.EMBEDDED
    assert source.path == HostPath(video)
    assert source.content_sha256 == hashlib.sha256(payload).hexdigest()
    assert not host.unavailable_artwork_paths
    loader = HostMediaArtworkLoader()
    loader.replace_library(host)
    preview = loader.load_artwork(ArtworkRequest(source.artwork_id, target_px=6))
    captured = capture_sync_artwork(source, 6, checkpoint=lambda: None)
    assert preview is not None
    assert preview.rgb888 == captured.rgb888
    assert captured.rgb888[0] > 240 and captured.rgb888[1] < 10
    reused = _scan(video.parent, cache)
    assert reused.cache.reused == 3
    assert reused.artwork_sources == host.artwork_sources


@pytest.mark.parametrize("folder_cover", [False, True])
def test_unavailable_container_cover_keeps_folder_fallback_or_unavailable_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folder_cover: bool
) -> None:
    video, _payload = _video(tmp_path, ".png")
    if folder_cover:
        Image.new("RGB", (12, 8), "blue").save(video.parent / "poster.jpg")

    def unavailable_tool(_name: str) -> None:
        return None

    monkeypatch.setattr(
        "iOpenPod.app.media.container_artwork.find_media_tool", unavailable_tool
    )

    host = _scan(video.parent)

    assert bool(host.unavailable_artwork_paths) is not folder_cover
    if folder_cover:
        assert host.artwork_sources[0].kind is HostArtworkKind.FOLDER
        assert host.artwork_sources[0].path.path.name == "poster.jpg"
    else:
        assert not host.artwork_sources


def test_video_without_embedded_cover_confirms_absence_and_reuses_cache(
    tmp_path: Path,
) -> None:
    video, _payload = _video(tmp_path, None)
    cache = AtomicHostFile(tmp_path / "cache.json")

    first = _scan(video.parent, cache)
    reused = _scan(video.parent, cache)

    assert not first.artwork_sources
    assert not first.unavailable_artwork_paths
    assert reused.cache.reused == 1


def test_cached_uninspected_video_cover_is_rechecked_without_file_changes(
    tmp_path: Path,
) -> None:
    video, _payload = _video(tmp_path, ".png")
    cache = AtomicHostFile(tmp_path / "cache.json")
    _scan(video.parent, cache)
    document = json.loads(cache.path.read_bytes())
    metadata = document["entries"][0]["metadata"]
    metadata.update(
        embedded_artwork_available=False,
        artwork_kind="",
        artwork_path="",
        artwork_size_bytes=0,
        artwork_modified_ns=0,
        artwork_content_sha256="",
    )
    catalog = json.dumps(
        document["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    document["catalog_sha256"] = hashlib.sha256(catalog).hexdigest()
    cache.path.write_text(json.dumps(document), encoding="utf-8")

    rescanned = _scan(video.parent, cache)

    assert rescanned.cache.inspected == 1
    assert rescanned.artwork_sources[0].kind is HostArtworkKind.EMBEDDED


def test_cover_extraction_preserves_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video, _payload = _video(tmp_path, ".png")

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise InterruptedError("cancelled")

    monkeypatch.setattr(
        "iOpenPod.app.media.container_artwork.run_media_tool", interrupted
    )
    with pytest.raises(InterruptedError, match="cancelled"):
        container_artwork(
            LocalHostFile.observe(HostPath(video)), checkpoint=lambda: None
        )
