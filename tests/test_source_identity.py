from pathlib import Path

from iopenpod.sync import source_identity
from iopenpod.sync.source_identity import source_content_hash
from iopenpod.sync.transcode_cache import TranscodeCache


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


def test_video_identity_survives_move_and_mp4_metadata_change(tmp_path: Path) -> None:
    before = tmp_path / "old-name.mp4"
    moved = tmp_path / "new-name.mp4"
    changed = tmp_path / "changed.mp4"
    before.write_bytes(_mp4_bytes(metadata=b"old-title", media=b"same-video"))
    moved.write_bytes(_mp4_bytes(metadata=b"new-title", media=b"same-video"))
    changed.write_bytes(_mp4_bytes(metadata=b"old-title", media=b"different-video"))

    before_identity = source_identity.video_content_identity(before)

    assert before_identity == source_identity.video_content_identity(moved)
    assert before_identity != source_identity.video_content_identity(changed)


def test_large_video_identity_reads_only_bounded_samples(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "large.mp4"
    payload_size = 64 * 1024 * 1024
    with video.open("wb") as stream:
        stream.write(_box(b"ftyp", b"mp42\0\0\0\0"))
        stream.write((8 + payload_size).to_bytes(4, "big") + b"mdat")
        stream.seek(payload_size - 1, 1)
        stream.write(b"\0")

    real_open = open
    bytes_read = 0

    class CountingReader:
        def __init__(self, stream):
            self._stream = stream

        def __enter__(self):
            self._stream.__enter__()
            return self

        def __exit__(self, *args):
            return self._stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self._stream, name)

        def read(self, size=-1):
            nonlocal bytes_read
            data = self._stream.read(size)
            bytes_read += len(data)
            return data

    def counting_open(path, mode="r", *args, **kwargs):
        return CountingReader(real_open(path, mode, *args, **kwargs))

    monkeypatch.setattr(source_identity, "open", counting_open, raising=False)

    identity = source_identity.video_content_identity(video)

    assert identity.startswith("video-sample-sha256-v1:")
    assert bytes_read < 3 * 1024 * 1024


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
