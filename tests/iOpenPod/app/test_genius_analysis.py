"""Cached acoustic evidence remains optional, bounded, and source checked."""

from __future__ import annotations

import json
import shutil
import wave
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app import genius_analysis_cache
from iOpenPod.app.genius_analysis import (
    FFmpegGeniusPCMDecoder,
    GeniusAnalysisService,
    GeniusAudioDecodeError,
)
from iOpenPod.app.genius_analysis_cache import GeniusProfileCache
from iOpenPod.app.genius_audio import GeniusAudioProfile
from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.media.importing import LibraryMediaSource
from iPodDB.library import (
    AudioEncoding,
    FileDependency,
    IPodTrackDetails,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
    prepared_audio,
)
from storage import (
    AccessMode,
    AtomicHostFile,
    ConcurrentModificationError,
    DevicePath,
    FilesystemSession,
    FilesystemSessionError,
    HostPath,
    Storage,
    StorageOperationError,
    capture_host_file,
)
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Callable


def _checkpoint() -> None:
    pass


def _profile(
    pcm: bytes, *, sample_rate_hz: int, checkpoint: Callable[[], None]
) -> GeniusAudioProfile:
    assert sample_rate_hz == 22_050
    checkpoint()
    return GeniusAudioProfile(2.0, None, (float(pcm[0]),) * 29, None)


class _Decoder:
    def __init__(self, action: Callable[[], None] | None = None) -> None:
        self.sources: list[HostPath | DevicePath] = []
        self.action = action

    def decode(
        self,
        source: HostPath | DevicePath,
        *,
        input_suffix: str,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
    ) -> bytes:
        assert input_suffix == ".mp3"
        assert session.is_active
        checkpoint()
        self.sources.append(source)
        if self.action is not None:
            self.action()
        return b"\x01\x00\x00\x00"


def _device(
    tmp_path: Path,
) -> tuple[Path, VirtualStoragePlatform, FilesystemSession, LibrarySnapshot]:
    root = tmp_path / "device"
    root.mkdir(parents=True)
    (root / "song.mp3").write_bytes(b"original")
    platform = VirtualStoragePlatform()
    platform.add_volume(root, writable=False)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    session = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    )
    track = Track(
        1,
        "Song",
        "Artist",
        "Album",
        2_000,
        metadata=TrackMetadata(location="song.mp3"),
        ipod=IPodTrackDetails(db_track_id=100),
    )
    return root, platform, session, LibrarySnapshot((track,))


def test_device_cache_survives_reloads_and_preserves_source_checks(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    decoder = _Decoder()
    cache = AtomicHostFile(tmp_path / "profiles.json")
    service = GeniusAnalysisService(cache, decoder, profiler=_profile)
    first = service.analyze(snapshot, session, checkpoint=_checkpoint)
    revision = cache.revision()
    second = GeniusAnalysisService(cache, decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert first == second
    assert first.issues == ()
    assert tuple(first.profiles) == (1,)
    assert len(first.dependencies) == 1
    assert decoder.sources == [DevicePath("song.mp3")]
    assert cache.revision() == revision
    (root / "song.mp3").write_bytes(b"changed after review")
    with pytest.raises(ConcurrentModificationError):
        second.validate_sources(session, checkpoint=_checkpoint)
    service.analyze(snapshot, session, checkpoint=_checkpoint)
    assert len(decoder.sources) == 2


def test_cache_reuse_never_crosses_device_identity(tmp_path: Path) -> None:
    root, platform, session, snapshot = _device(tmp_path)
    cache = AtomicHostFile(tmp_path / "profiles.json")
    decoder = _Decoder()
    service = GeniusAnalysisService(cache, decoder, profiler=_profile)
    service.analyze(snapshot, session, checkpoint=_checkpoint)
    session.close()
    platform.add_volume(root, device_id="different-device", writable=False)
    storage = Storage(platform)
    replacement = storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    )
    service.analyze(snapshot, replacement, checkpoint=_checkpoint)
    assert len(decoder.sources) == 2


def test_new_and_replaced_tracks_use_prepared_host_sources(tmp_path: Path) -> None:
    root, _, session, snapshot = _device(tmp_path)
    host = tmp_path / "replacement.mp3"
    host.write_bytes(b"replacement")
    with capture_host_file(HostPath(host), checkpoint=_checkpoint) as captured:
        fingerprint = captured.fingerprint
    source = LibraryMediaSource(
        HostPath(host),
        fingerprint,
        prepared_audio(
            1,
            FileDependency("song.mp3", fingerprint.size, fingerprint.sha256),
            AudioEncoding.MP3,
        ),
    )
    decoder = _Decoder()
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        snapshot, session, media=(source,), checkpoint=_checkpoint
    )
    assert decoder.sources == [HostPath(host)]
    assert result.dependencies == ()
    assert result.issues == ()
    assert (root / "song.mp3").read_bytes() == b"original"
    host.write_bytes(b"changed prepared file")
    with pytest.raises(ConcurrentModificationError):
        GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
            snapshot, session, media=(source,), checkpoint=_checkpoint
        )


def test_prepared_capture_accepts_original_fingerprint_but_rejects_content_change(
    tmp_path: Path,
) -> None:
    _, _, session, snapshot = _device(tmp_path)
    host = tmp_path / "original.mp3"
    host.write_bytes(b"original prepared media")
    decoder = _Decoder()
    with capture_host_file(HostPath(host), checkpoint=_checkpoint) as captured:
        fingerprint = captured.fingerprint
        source = LibraryMediaSource(
            captured.snapshot,
            fingerprint,
            prepared_audio(
                1,
                FileDependency("song.mp3", fingerprint.size, fingerprint.sha256),
                AudioEncoding.MP3,
            ),
        )
        service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
        result = service.analyze(
            snapshot, session, media=(source,), checkpoint=_checkpoint
        )
        assert result.issues == ()
        assert tuple(result.profiles) == (1,)
        assert decoder.sources == [captured.snapshot]
        Path(captured.snapshot).write_bytes(b"changed prepared media!")
        assert Path(captured.snapshot).stat().st_size == fingerprint.size
        with pytest.raises(ConcurrentModificationError, match="content"):
            service.analyze(snapshot, session, media=(source,), checkpoint=_checkpoint)


@pytest.mark.parametrize("failure", ["decode", "cancel", "disconnect", "mutate"])
def test_only_optional_decode_failure_can_be_downgraded(
    tmp_path: Path, failure: str
) -> None:
    root, _, session, snapshot = _device(tmp_path)

    def action() -> None:
        if failure == "decode":
            raise GeniusAudioDecodeError("Bad audio")
        if failure == "cancel":
            raise PreparationCancelledError
        if failure == "disconnect":
            session.invalidate("Disconnected while analyzing")
        else:
            (root / "song.mp3").write_bytes(b"unexpected replacement")

    decoder = _Decoder(action)
    service = GeniusAnalysisService(decoder=decoder, profiler=_profile)
    if failure == "decode":
        for _ in range(2):
            result = service.analyze(snapshot, session, checkpoint=_checkpoint)
            assert not result.profiles
            assert result.issues[0].code == "genius.audio_unavailable"
        assert len(decoder.sources) == 2
    else:
        error = {
            "cancel": PreparationCancelledError,
            "disconnect": FilesystemSessionError,
            "mutate": ConcurrentModificationError,
        }[failure]
        with pytest.raises(error):
            service.analyze(snapshot, session, checkpoint=_checkpoint)


def test_corrupt_cache_is_a_miss_and_successful_profiles_repair_it(
    tmp_path: Path,
) -> None:
    _, _, session, snapshot = _device(tmp_path)
    file = AtomicHostFile(tmp_path / "cache.json")
    file.replace_bytes(b"broken cache")
    decoder = _Decoder()
    service = GeniusAnalysisService(file, decoder, profiler=_profile)
    result = service.analyze(snapshot, session, checkpoint=_checkpoint)
    assert result.profiles
    assert result.issues[0].code == "genius.cache_read"
    repeated = GeniusAnalysisService(file, decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert not repeated.issues
    assert len(decoder.sources) == 1


def test_only_final_eligible_music_is_analyzed(tmp_path: Path) -> None:
    root, _, session, snapshot = _device(tmp_path)
    (root / "long.mp3").write_bytes(b"long song")
    track = snapshot.tracks[0]
    snapshot = replace(
        snapshot,
        tracks=(
            track,
            replace(track, track_id=2, media_types=(MediaType.AUDIOBOOK,)),
            replace(track, track_id=3, media_types=(MediaType.VIDEO,)),
            replace(track, track_id=4, metadata=replace(track.metadata, podcast=True)),
            replace(
                track,
                track_id=5,
                length_ms=901_000,
                metadata=TrackMetadata(location="long.mp3"),
            ),
        ),
    )
    decoder = _Decoder()
    result = GeniusAnalysisService(decoder=decoder, profiler=_profile).analyze(
        snapshot, session, checkpoint=_checkpoint
    )
    assert tuple(result.profiles) == (1,)
    assert len(decoder.sources) == 1
    assert result.issues[0].track_id == 5


@pytest.mark.parametrize(
    "mutation", ["checksum", "version", "shape", "nan", "duplicate"]
)
def test_cache_rejects_invalid_profiles(tmp_path: Path, mutation: str) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = GeniusProfileCache(file)
    cache.remember("a" * 64, GeniusAudioProfile(2, None, (0.0,) * 29, None))
    cache.save(_checkpoint, force=True)
    payload = file.read_bytes()
    assert payload is not None
    document = json.loads(payload)
    if mutation == "checksum":
        document["sha256"] = "0" * 64
    elif mutation == "version":
        document["analysis_version"] += 1
    else:
        if mutation == "shape":
            document["records"][0][3].pop()
        elif mutation == "nan":
            document["records"][0][3][0] = float("nan")
        else:
            document["records"] *= 2
        import hashlib

        document["sha256"] = hashlib.sha256(
            json.dumps(
                document["records"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    file.replace_bytes(json.dumps(document).encode())
    with pytest.raises(ValueError):
        GeniusProfileCache(file).load(_checkpoint)


def test_cache_bounds_records_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = AtomicHostFile(tmp_path / "cache.json")
    monkeypatch.setattr(genius_analysis_cache, "_MAX_RECORDS", 2)
    cache = GeniusProfileCache(file)
    profile = GeniusAudioProfile(2, None, (0.0,) * 29, None)
    for character in "abc":
        cache.remember(character * 64, profile)
    cache.save(_checkpoint, force=True)
    restored = GeniusProfileCache(file)
    restored.load(_checkpoint)
    assert restored.get("a" * 64) is None
    assert restored.get("b" * 64) == profile
    monkeypatch.setattr(genius_analysis_cache, "_MAX_BYTES", 128)
    with pytest.raises(StorageOperationError, match="read size limit"):
        GeniusProfileCache(file).load(_checkpoint)


def test_cache_byte_budget_evicts_old_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(genius_analysis_cache, "_MAX_BYTES", 1500)
    file = AtomicHostFile(tmp_path / "cache.json")
    cache = GeniusProfileCache(file)
    profile = GeniusAudioProfile(2, None, (0.0,) * 29, None)
    for character in "abc":
        cache.remember(character * 64, profile)
    cache.save(_checkpoint, force=True)
    payload = file.read_bytes()
    assert payload is not None and len(payload) <= 1500
    restored = GeniusProfileCache(file)
    restored.load(_checkpoint)
    assert restored.get("a" * 64) is None
    assert restored.get("c" * 64) == profile


def test_missing_ffmpeg_is_looked_up_once_per_run_and_retried_later(
    tmp_path: Path,
) -> None:
    root, _, session, snapshot = _device(tmp_path)
    (root / "second.mp3").write_bytes(b"second")
    snapshot = replace(
        snapshot,
        tracks=(
            *snapshot.tracks,
            replace(
                snapshot.tracks[0],
                track_id=2,
                metadata=TrackMetadata(location="second.mp3"),
            ),
        ),
    )
    lookups: list[str] = []

    def missing(name: str) -> None:
        lookups.append(name)

    service = GeniusAnalysisService(decoder=FFmpegGeniusPCMDecoder(find_tool=missing))
    for count in (1, 2):
        result = service.analyze(snapshot, session, checkpoint=_checkpoint)
        assert not result.profiles
        assert len(result.issues) == 2
        assert lookups == ["ffmpeg"] * count


def test_noop_cache_lookup_still_checks_cancellation(tmp_path: Path) -> None:
    _, _, session, snapshot = _device(tmp_path)
    service = GeniusAnalysisService(decoder=_Decoder(), profiler=_profile)
    service.analyze(snapshot, session, checkpoint=_checkpoint)

    def cancelled() -> None:
        raise PreparationCancelledError

    with pytest.raises(PreparationCancelledError):
        service.analyze(snapshot, session, checkpoint=cancelled)


def test_ffmpeg_decodes_pinned_device_audio_with_bounded_output(tmp_path: Path) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is not installed")
    root, _, session, _ = _device(tmp_path)
    with wave.open(str(root / "source.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22_050)
        output.writeframes(b"\x00\x00" * 22_050)
    decoder = FFmpegGeniusPCMDecoder(find_tool=lambda _: HostPath(Path(executable)))
    pcm = decoder.decode(
        DevicePath("source.wav"),
        input_suffix=".wav",
        session=session,
        checkpoint=_checkpoint,
    )
    assert len(pcm) == 22_050 * 4
    assert not any(pcm)
