"""Persist valid scan catalogs beyond the former aggregate byte ceilings."""

from functools import cache
from pathlib import Path
from random import Random

import pytest

from iOpenPod.app import host_media_library, ipod_analysis_cache, library_sync_helper
from iOpenPod.app.host_media_fingerprint import normalize_fpcalc_fingerprint
from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaScanner,
    PendingHostMediaScan,
    _CachedTrackRecord,
)
from iOpenPod.app.ipod_analysis_cache import IPodAnalysisCache, IPodAnalysisRecord
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodTrackFingerprint,
)
from iOpenPod.app.media.fingerprint_codec import decode_fingerprint, encode_fingerprint
from storage import AtomicHostFile, DevicePath, HostPath, Storage
from storage.testing import VirtualStoragePlatform


@pytest.fixture(params=["encoded", "decoded"])
def large_catalog(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, int]:
    if request.param == "encoded":
        random = Random(0)
        fingerprint = ",".join(str(random.getrandbits(32)) for _ in range(12_000))
        count = 1_050
        assert len(encode_fingerprint(fingerprint)) * count > 64 * 1024 * 1024
    else:
        fingerprint = ",".join(["4294967295"] * 12_000)
        count = 2_048
        assert len(fingerprint) * count > 256 * 1024 * 1024
    # Exercise real codecs once per distinct value, keeping these catalog-capacity
    # tests fast without allocating hundreds of MiB of identical decoded strings.
    encoder = cache(encode_fingerprint)
    decoder = cache(decode_fingerprint)
    for module in (host_media_library, ipod_analysis_cache, library_sync_helper):
        monkeypatch.setattr(module, "encode_fingerprint", encoder)
        monkeypatch.setattr(module, "decode_fingerprint", decoder)
    monkeypatch.setattr(
        library_sync_helper,
        "normalize_fpcalc_fingerprint",
        cache(normalize_fpcalc_fingerprint),
    )
    return fingerprint, count


def test_host_scan_persists_and_reloads_large_catalog(
    tmp_path: Path, large_catalog: tuple[str, int]
) -> None:
    fingerprint, count = large_catalog
    records = tuple(
        _CachedTrackRecord(
            HostPath(tmp_path / f"{index:06}.wav"),
            HostMediaFileKind.AUDIO,
            99,
            123,
            metadata_complete=True,
            acoustic_fingerprint=fingerprint,
        )
        for index in range(count)
    )
    file = AtomicHostFile(tmp_path / "cache.json")
    pending = PendingHostMediaScan(
        records=(),
        external_references=(),
        issues=(),
        cache=HostMediaCacheStats(),
        cached_records=records,
    )
    HostMediaScanner(file).complete(pending, frozenset(), checkpoint=lambda: None)
    assert file.exists()
    revision = file.revision()
    reloaded = HostMediaScanner(file).scan((), checkpoint=lambda: None)
    assert len(reloaded.cached_records) == count
    assert reloaded.cached_records == records
    assert file.revision() == revision


def test_ipod_analysis_persists_and_reloads_all_large_catalog_records(
    tmp_path: Path, large_catalog: tuple[str, int]
) -> None:
    fingerprint, count = large_catalog
    records = tuple(
        IPodAnalysisRecord(
            "database", index, DevicePath(f"Music/{index}.mp3"), 99, 123, fingerprint
        )
        for index in range(1, count + 1)
    )
    file = AtomicHostFile(tmp_path / "cache.json")
    analysis = IPodAnalysisCache(file, "a" * 64)
    for record in records:
        analysis.remember(record)
    analysis.save(force=True)
    loaded = IPodAnalysisCache(file, "a" * 64)
    loaded.load()
    for record in records:
        assert analysis.get(*record.key) is not None
        assert loaded.get(*record.key) is not None
        assert loaded.get(*record.key) == record


def test_sync_helper_persists_and_reloads_large_catalog(
    tmp_path: Path, large_catalog: tuple[str, int]
) -> None:
    fingerprint, count = large_catalog
    records = tuple(
        IPodTrackFingerprint(
            index, index, DevicePath(f"Music/{index}.mp3"), 99, 123, fingerprint
        )
        for index in range(1, count + 1)
    )
    payload = library_sync_helper._encode_helper(
        records, (), "a" * 64, updated_at="2026-10-14T15:00:00Z"
    )
    path = tmp_path / str(LIBRARY_SYNC_HELPER_PATH)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path, label="Test iPod")
    storage = Storage(platform)
    with storage.open_session(storage.discover().volumes[0]) as session:
        loaded, issue = library_sync_helper._load_helper(session)
    assert issue is None
    assert loaded.writable
    assert len(loaded.tracks) == count
    assert loaded.tracks == records
    assert loaded.library_sha256 == "a" * 64
