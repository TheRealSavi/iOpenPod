from __future__ import annotations

from datetime import UTC, datetime

from iopenpod.sync.transcode_cache import CachedFile, TranscodeCache


def test_cache_separates_same_fingerprint_by_source_hash(tmp_path):
    cache = TranscodeCache(cache_dir=tmp_path / "cache")
    fingerprint = "627964279,627964279,627964279"

    source_a = tmp_path / "source_a.wav"
    source_b = tmp_path / "source_b.wav"
    source_a.write_bytes(b"A" * 4096)
    source_b.write_bytes(b"B" * 4096)

    hash_a, mtime_a = cache.describe_source(source_a)
    hash_b, mtime_b = cache.describe_source(source_b)
    assert hash_a and hash_b and hash_a != hash_b

    reserved_a = cache.reserve(
        fingerprint,
        "alac",
        source_hash=hash_a,
    )
    reserved_a.write_bytes(b"transcoded-a")
    cache.commit(
        fingerprint=fingerprint,
        source_format="wav",
        target_format="alac",
        source_size=source_a.stat().st_size,
        source_path=source_a,
        source_hash=hash_a,
        source_mtime=mtime_a,
    )

    reserved_b = cache.reserve(
        fingerprint,
        "alac",
        source_hash=hash_b,
    )
    reserved_b.write_bytes(b"transcoded-b")
    cache.commit(
        fingerprint=fingerprint,
        source_format="wav",
        target_format="alac",
        source_size=source_b.stat().st_size,
        source_path=source_b,
        source_hash=hash_b,
        source_mtime=mtime_b,
    )

    assert reserved_a != reserved_b
    assert cache._index.count == 2

    cached_a = cache.get(
        fingerprint,
        "alac",
        source_size=source_a.stat().st_size,
        source_path=source_a,
        source_hash=hash_a,
        source_mtime=mtime_a,
    )
    cached_b = cache.get(
        fingerprint,
        "alac",
        source_size=source_b.stat().st_size,
        source_path=source_b,
        source_hash=hash_b,
        source_mtime=mtime_b,
    )

    assert cached_a is not None
    assert cached_b is not None
    assert cached_a.read_bytes() == b"transcoded-a"
    assert cached_b.read_bytes() == b"transcoded-b"


def test_cache_legacy_fallback_rejects_other_source_hash(tmp_path):
    cache = TranscodeCache(cache_dir=tmp_path / "cache")
    fingerprint = "91093363,91093363,91093363"

    source_a = tmp_path / "source_a.wav"
    source_b = tmp_path / "source_b.wav"
    source_a.write_bytes(b"A" * 2048)
    source_b.write_bytes(b"B" * 2048)

    hash_a, mtime_a = cache.describe_source(source_a)
    hash_b, mtime_b = cache.describe_source(source_b)
    assert hash_a and hash_b and hash_a != hash_b

    legacy_name = cache._cache_filename(fingerprint, "alac")
    legacy_path = cache.files_dir / legacy_name
    legacy_path.write_bytes(b"legacy-transcode")
    cache._index.files[cache._index._legacy_key(fingerprint, "alac")] = CachedFile(
        fingerprint=fingerprint,
        source_format="wav",
        target_format="alac",
        filename=legacy_name,
        size=legacy_path.stat().st_size,
        created=datetime.now(UTC).isoformat(),
        source_size=source_a.stat().st_size,
        source_hash=hash_a,
        source_mtime=mtime_a,
    )

    assert cache.get(
        fingerprint,
        "alac",
        source_size=source_b.stat().st_size,
        source_path=source_b,
        source_hash=hash_b,
        source_mtime=mtime_b,
    ) is None

    cached_a = cache.get(
        fingerprint,
        "alac",
        source_size=source_a.stat().st_size,
        source_path=source_a,
        source_hash=hash_a,
        source_mtime=mtime_a,
    )
    assert cached_a is not None
    assert cached_a.read_bytes() == b"legacy-transcode"
