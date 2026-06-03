from pathlib import Path

from SyncEngine.source_identity import source_content_hash
from SyncEngine.transcode_cache import TranscodeCache


def _box(box_type: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + box_type + payload


def _mp4_bytes(*, metadata: bytes, media: bytes) -> bytes:
    return (
        _box(b"ftyp", b"M4A \x00\x00\x00\x00")
        + _box(b"free", metadata)
        + _box(b"mdat", media)
        + _box(b"moov", metadata[::-1])
    )


def test_mp4_source_hash_ignores_metadata_atoms(tmp_path: Path) -> None:
    before = tmp_path / "before.m4a"
    after = tmp_path / "after.m4a"
    changed_audio = tmp_path / "changed.m4a"
    before.write_bytes(_mp4_bytes(metadata=b"title-before", media=b"same-audio"))
    after.write_bytes(_mp4_bytes(metadata=b"title-after-and-larger", media=b"same-audio"))
    changed_audio.write_bytes(_mp4_bytes(metadata=b"title-before", media=b"different-audio"))

    assert source_content_hash(before) == source_content_hash(after)
    assert source_content_hash(before) != source_content_hash(changed_audio)


def test_transcode_cache_reuses_entry_when_mp4_container_size_changes(
    tmp_path: Path,
) -> None:
    cache = TranscodeCache(cache_dir=tmp_path / "cache")
    fingerprint = "123,456,789"
    before = tmp_path / "before.m4a"
    after = tmp_path / "after.m4a"
    before.write_bytes(_mp4_bytes(metadata=b"old", media=b"same-audio"))
    after.write_bytes(_mp4_bytes(metadata=b"new-metadata-that-changes-size", media=b"same-audio"))

    source_hash, source_mtime = cache.describe_source(before)
    changed_hash, changed_mtime = cache.describe_source(after)
    assert source_hash == changed_hash
    assert before.stat().st_size != after.stat().st_size

    reserved = cache.reserve(
        fingerprint,
        "aac",
        bitrate=192,
        source_hash=source_hash,
    )
    reserved.write_bytes(b"cached-aac")
    cache.commit(
        fingerprint=fingerprint,
        source_format="m4a",
        target_format="aac",
        source_size=before.stat().st_size,
        bitrate=192,
        source_path=before,
        source_hash=source_hash,
        source_mtime=source_mtime,
    )

    cached = cache.get(
        fingerprint,
        "aac",
        source_size=after.stat().st_size,
        bitrate=192,
        source_path=after,
        source_hash=changed_hash,
        source_mtime=changed_mtime,
    )

    assert cached is not None
    assert cached.read_bytes() == b"cached-aac"
