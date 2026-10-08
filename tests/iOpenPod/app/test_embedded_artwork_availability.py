"""Failed embedded artwork observations cannot authorize removing device covers."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import cast

import mutagen
import pytest
from mutagen.id3 import APIC
from mutagen.wave import WAVE
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_host_media_library import (
    _MutableWave,  # pyright: ignore[reportPrivateUsage]
    _write_wav,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.host_media_library import HostMediaLibrary, HostMediaScanner
from storage import AtomicHostFile, HostPath


def _tagged_wave(path: Path, payload: bytes) -> None:
    _write_wav(path)
    tagged = cast("_MutableWave", WAVE(path))  # type: ignore[no-untyped-call]
    tagged.add_tags()
    assert tagged.tags is not None
    tagged.tags.add(
        APIC(encoding=3, mime="image/png", type=3, desc="front", data=payload)  # type: ignore[no-untyped-call]
    )
    tagged.save()


def _scan(scanner: HostMediaScanner, folder: Path) -> HostMediaLibrary:
    pending = scanner.scan((create_host_media_folder(folder),), checkpoint=lambda: None)
    return scanner.complete(pending, frozenset(), checkpoint=lambda: None)


class _Fingerprinter:
    def fingerprint(self, source: HostPath, *, checkpoint: Callable[[], None]) -> str:
        del source
        checkpoint()
        return "1,2,3"


@pytest.mark.parametrize("failure", ["invalid_image", "tag_reader"])
def test_failed_embedded_observation_preserves_existing_cover_during_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    _tagged_wave(host_dir / "song.wav", b"interrupted image bytes")
    if failure == "tag_reader":

        def unreadable(*_args: object, **_kwargs: object) -> None:
            raise mutagen.MutagenError("Embedded tags could not be read")

        monkeypatch.setattr(mutagen, "File", unreadable)
    host = _scan(HostMediaScanner(), host_dir)
    assert host.snapshot.tracks[0].artwork_id == 0
    assert host.unavailable_artwork_paths
    device = build_device(tmp_path)
    try:
        request = _request(device, host, update=True)
        assert not request.plan.items[0].artwork_changed
        if failure == "tag_reader":
            # Other metadata is also unavailable. The actual scan/planner must
            # not request artwork removal regardless of later media validation.
            device.assert_original()
            return
        original = request.source.library.tracks[0].artwork_id
        before = {
            path: path.read_bytes()
            for path in (device.root / "iPod_Control/Artwork").iterdir()
            if path.is_file()
        }

        result = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            request, lambda _: None, Event()
        )

        assert result.active is not None, result.issues
        assert result.active.library.tracks[0].artwork_id == original > 0
        assert {path: path.read_bytes() for path in before} == before
    finally:
        device.coordinator.close()


def test_invalid_embedded_image_keeps_valid_folder_fallback(tmp_path: Path) -> None:
    _tagged_wave(tmp_path / "song.wav", b"invalid APIC")
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "cover.png")

    host = _scan(HostMediaScanner(), tmp_path)

    assert host.snapshot.tracks[0].artwork_id > 0
    assert not host.unavailable_artwork_paths
    assert host.artwork_sources[0].path.path.name == "cover.png"


def test_absent_embedded_cover_still_allows_intentional_removal(tmp_path: Path) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    _write_wav(host_dir / "song.wav")
    host = _scan(HostMediaScanner(), host_dir)
    assert not host.unavailable_artwork_paths
    device = build_device(tmp_path)
    try:
        request = _request(device, host, update=True)
        assert request.plan.items[0].artwork_changed
    finally:
        device.coordinator.close()


def test_failed_embedded_observation_survives_cache_reload_and_retries(
    tmp_path: Path,
) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    song = host_dir / "song.wav"
    _tagged_wave(song, b"invalid APIC")
    cache = AtomicHostFile(tmp_path / "cache.json")
    assert _scan(
        HostMediaScanner(cache, fingerprinter=_Fingerprinter()), host_dir
    ).unavailable_artwork_paths
    reused = _scan(HostMediaScanner(cache, fingerprinter=_Fingerprinter()), host_dir)
    assert reused.cache.reused == 1
    assert reused.unavailable_artwork_paths
    # A complete observation of an absent cover is authoritative again.
    _write_wav(song)
    assert not _scan(HostMediaScanner(cache), host_dir).unavailable_artwork_paths


def test_legacy_cache_absence_is_rechecked_for_invalid_embedded_cover(
    tmp_path: Path,
) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    _tagged_wave(host_dir / "song.wav", b"invalid APIC")
    cache = AtomicHostFile(tmp_path / "cache.json")
    _scan(HostMediaScanner(cache), host_dir)
    document = json.loads(cache.path.read_bytes())
    document["version"] = 11
    for entry in document["entries"]:
        entry["metadata"].pop("embedded_artwork_available", None)
        entry["metadata"]["metadata_complete"] = True
        entry["warning"] = ""
    catalog = json.dumps(
        document["entries"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    document["catalog_sha256"] = hashlib.sha256(catalog).hexdigest()
    cache.path.write_text(json.dumps(document), encoding="utf-8")

    host = _scan(HostMediaScanner(cache), host_dir)

    assert host.cache.inspected == 1
    assert host.unavailable_artwork_paths
