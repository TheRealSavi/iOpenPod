"""Behavioral tests for Host Media Library scanning and caching."""

import base64
import hashlib
import json
import logging
import os
import threading
import wave
from collections import Counter
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, NoReturn, Protocol, cast

import mutagen
import pytest
from mutagen.id3 import APIC, TIT2, TPE1, PictureType
from mutagen.wave import WAVE
from PIL import Image

from iOpenPod.app.display_text import SourceText
from iOpenPod.app.host_media_fingerprint import (
    FpcalcError,
    FpcalcFingerprinter,
    FpcalcUnavailableError,
)
from iOpenPod.app.host_media_folders import (
    HostMediaFolder,
    HostMediaType,
    create_host_media_folder,
)
from iOpenPod.app.host_media_library import (
    HostMediaArtworkLoader,
    HostMediaCacheStats,
    HostMediaPhotoLoader,
    HostMediaScanCancelledError,
    HostMediaScanner,
    HostMediaScanProgress,
    HostMediaScanStage,
    HostMediaTreeChangedError,
)
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.models.photos import PhotoRequest
from iPodDB.library import LibrarySnapshot, MediaKind, MediaType
from storage import AtomicHostFile, HostPath, StorageError
from storage.host_directory import HostDirectoryEntry, LocalHostDirectory
from storage.host_input import LocalHostFile


def test_one_unreadable_subfolder_does_not_hide_later_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a-denied", "b-readable"):
        directory = tmp_path / name
        directory.mkdir()
        _write_wav(directory / "song.wav")
    native = LocalHostDirectory.list_entries

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        if self.path.path.name == "a-denied":
            raise PermissionError("folder unavailable")
        return native(
            self,
            checkpoint=checkpoint,
            on_issue=on_issue,
            include_file=include_file,
            include_directories=include_directories,
            on_entry=on_entry,
        )

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(library.snapshot.tracks) == 1
    assert "b-readable" in library.snapshot.tracks[0].metadata.location
    assert any("folder unavailable" in issue.detail for issue in library.issues)
    diagnostic = next(
        issue.detail for issue in library.issues if "folder unavailable" in issue.detail
    )
    assert isinstance(diagnostic, SourceText)
    assert diagnostic.source.endswith("scanning continued: {error}")
    assert dict(diagnostic.parameters)["error"] == "folder unavailable"


@pytest.mark.parametrize(
    "payload",
    [b"not-json", b"{}", b'{"version": 10}', b"[" * 2000 + b"0" + b"]" * 2000],
)
def test_malformed_cache_falls_back_to_scanning(tmp_path: Path, payload: bytes) -> None:
    _write_wav(tmp_path / "song.wav")
    cache_path = tmp_path / "cache.json"
    cache_path.write_bytes(payload)
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(result.snapshot.tracks) == 1
    assert result.cache.reused == 0
    assert json.loads(cache_path.read_text(encoding="utf-8"))["version"] == 11


def test_changed_tracks_use_existing_acoustic_analysis_without_full_stream_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "song.wav"
    _write_wav(path)
    acoustic = "1,2,3"
    calls = 0

    def fingerprint(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return acoustic

    def unexpected_media_tool(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Scan launched an extra media-tool pass")

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    monkeypatch.setattr(
        "storage.media_processing._run_media_tool",
        unexpected_media_tool,
    )
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    folder = create_host_media_folder(tmp_path)
    scanner.scan((folder,), checkpoint=lambda: None)
    assert calls == 1
    tagged = cast("_MutableWave", WAVE(path))  # type: ignore[no-untyped-call]
    tagged.add_tags()
    assert tagged.tags is not None
    tagged.tags.add(TIT2(encoding=3, text=["Changed"]))  # type: ignore[no-untyped-call]
    tagged.save()
    pending = scanner.scan((folder,), checkpoint=lambda: None)
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert calls == 2
    assert result.snapshot.tracks[0].title == "Changed"
    assert result.sources[0].acoustic_fingerprint == "1,2,3"

    # A different payload must calculate a new correlation fingerprint.
    acoustic = "4,5,6"
    _write_wav(path)
    pending = scanner.scan((folder,), checkpoint=lambda: None)
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert calls == 3
    assert result.sources[0].acoustic_fingerprint == "4,5,6"


def test_missing_fingerprinting_tool_keeps_readable_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")

    def unavailable(*args: object, **kwargs: object) -> str:
        raise FpcalcUnavailableError("Install Chromaprint")

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", unavailable)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(result.snapshot.tracks) == 1
    assert result.sources[0].acoustic_fingerprint is None


def test_cached_scans_reuse_decoded_records_and_never_rewrite_unchanged_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")
    cache = AtomicHostFile(tmp_path / "cache.json")
    folder = create_host_media_folder(tmp_path)
    reads = 0
    writes = 0
    native_read = AtomicHostFile.read_bytes
    native_write = AtomicHostFile.replace_bytes

    def read(self: AtomicHostFile, *, max_bytes: int | None = None) -> bytes | None:
        nonlocal reads
        reads += 1
        return native_read(self, max_bytes=max_bytes)

    def write(self: AtomicHostFile, data: bytes) -> None:
        nonlocal writes
        writes += 1
        native_write(self, data)

    monkeypatch.setattr(AtomicHostFile, "read_bytes", read)
    monkeypatch.setattr(AtomicHostFile, "replace_bytes", write)
    scanner = HostMediaScanner(cache)
    first = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(first, frozenset(), checkpoint=lambda: None)
    assert (reads, writes) == (1, 1)

    second = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(second, frozenset(), checkpoint=lambda: None)
    assert second.cache == HostMediaCacheStats(reused=1)
    assert (reads, writes) == (1, 1)

    restarted = HostMediaScanner(cache)
    third = restarted.scan((folder,), checkpoint=lambda: None)
    restarted.complete(third, frozenset(), checkpoint=lambda: None)
    assert third.cache == HostMediaCacheStats(reused=1)
    assert (reads, writes) == (2, 1)


@pytest.mark.parametrize("change", ["delete", "replace", "edit"])
def test_in_memory_cache_notices_external_invalidation(
    tmp_path: Path, change: str
) -> None:
    _write_wav(tmp_path / "song.wav")
    cache = AtomicHostFile(tmp_path / "cache.json")
    scanner = HostMediaScanner(cache)
    folder = create_host_media_folder(tmp_path)
    scanner.scan((folder,), checkpoint=lambda: None)
    if change == "delete":
        cache.path.unlink()
    elif change == "replace":
        cache.replace_bytes(b"invalid")
    else:
        cache.path.write_bytes(b"invalid")
    changed = scanner.scan((folder,), checkpoint=lambda: None)
    assert changed.cache == HostMediaCacheStats(inspected=1)
    assert json.loads(cache.path.read_bytes())["version"] == 11


def test_cache_save_failure_retains_work_in_memory_and_retries_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")
    cache = AtomicHostFile(tmp_path / "cache.json")
    scanner = HostMediaScanner(cache)
    folder = create_host_media_folder(tmp_path)
    native_write = AtomicHostFile.replace_bytes
    attempts = 0

    def fail_once(self: AtomicHostFile, data: bytes) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("cache temporarily unavailable")
        native_write(self, data)

    monkeypatch.setattr(AtomicHostFile, "replace_bytes", fail_once)
    scanner.scan((folder,), checkpoint=lambda: None)
    assert not cache.path.exists()
    retried = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(retried, frozenset(), checkpoint=lambda: None)
    assert retried.cache == HostMediaCacheStats(reused=1)
    assert cache.path.exists()
    assert attempts == 2


def test_failed_acoustic_analysis_reuses_metadata_and_recovers_without_stale_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")
    cache = AtomicHostFile(tmp_path / "cache.json")
    folder = create_host_media_folder(tmp_path)
    calls = 0

    class Fingerprinter:
        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise FpcalcUnavailableError("Install Chromaprint")
            return "1,2,3"

    fingerprinter = Fingerprinter()
    scanner = HostMediaScanner(cache, fingerprinter)
    scanner.scan((folder,), checkpoint=lambda: None)

    def reject_metadata(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Unchanged readable metadata was inspected again")

    monkeypatch.setattr(mutagen, "File", reject_metadata)
    restarted = HostMediaScanner(cache, fingerprinter)
    second = restarted.scan((folder,), checkpoint=lambda: None)
    assert len(second.issues) == 1
    recovered = restarted.scan((folder,), checkpoint=lambda: None)
    library = restarted.complete(recovered, frozenset(), checkpoint=lambda: None)
    assert calls == 3
    assert not library.issues
    assert library.sources[0].acoustic_fingerprint == "1,2,3"
    assert restarted.scan((folder,), checkpoint=lambda: None).cache.reused == 1
    assert calls == 3


def test_cached_reading_progress_is_throttled_with_exact_final_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(30):
        _write_wav(tmp_path / f"{index}.wav")
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    folder = create_host_media_folder(tmp_path)
    scanner.scan((folder,), checkpoint=lambda: None)
    monkeypatch.setattr("iOpenPod.app.host_media_library.perf_counter", lambda: 0.0)
    events: list[HostMediaScanProgress] = []
    scanner.scan((folder,), checkpoint=lambda: None, progress=events.append)
    reading = [event for event in events if event.stage is HostMediaScanStage.READING]
    assert [event.completed for event in reading] == [0, 1, 30]
    assert reading[-1].total == 30
    assert reading[-1].cache_hits == 30


def test_failed_metadata_retries_without_repeating_successful_acoustic_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")
    cache = AtomicHostFile(tmp_path / "cache.json")
    native_parse = cast("_MutagenReader", mutagen).File
    fingerprint_calls = 0
    metadata_unavailable = True

    def parse(source: BinaryIO, *, easy: bool = False) -> object:
        if metadata_unavailable:
            raise mutagen.MutagenError("Temporarily unreadable tags")
        return native_parse(source, easy=easy)

    def fingerprint(*args: object, **kwargs: object) -> str:
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        return "1,2,3"

    monkeypatch.setattr(mutagen, "File", parse)
    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    folder = create_host_media_folder(tmp_path)
    first = HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)
    assert first.issues
    stored = json.loads(cache.path.read_bytes())
    assert stored["entries"][0]["metadata"]["metadata_complete"] is False
    metadata_unavailable = False
    recovered = HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)
    assert not recovered.issues
    assert recovered.cache == HostMediaCacheStats(inspected=1)
    assert fingerprint_calls == 1
    stored = json.loads(cache.path.read_bytes())
    assert stored["entries"][0]["metadata"]["metadata_complete"] is True


def test_cache_limits_combined_decoded_fingerprints_on_both_read_and_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("first.wav", "second.wav"):
        _write_wav(tmp_path / name)
    cache = AtomicHostFile(tmp_path / "cache.json")
    folder = create_host_media_folder(tmp_path)
    scanner = HostMediaScanner(cache)
    with monkeypatch.context() as bounded:
        bounded.setattr(
            "iOpenPod.app.host_media_library._MAX_DECODED_FINGERPRINT_BYTES", 8
        )
        scanner.scan((folder,), checkpoint=lambda: None)
        assert not cache.path.exists()
    # Failed persistence retains inspected records and retries after recovery.
    assert scanner.scan((folder,), checkpoint=lambda: None).cache.reused == 2
    with monkeypatch.context() as bounded:
        bounded.setattr(
            "iOpenPod.app.host_media_library._MAX_DECODED_FINGERPRINT_BYTES", 8
        )
        rejected = HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)
        assert rejected.cache == HostMediaCacheStats(inspected=2)


def test_long_acoustic_fingerprints_are_packed_losslessly_in_the_scan_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")
    fingerprint = ",".join(str(3_000_000_000 + value) for value in range(948))

    def calculate_fingerprint(*args: object, **kwargs: object) -> str:
        return fingerprint

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", calculate_fingerprint)
    cache = AtomicHostFile(tmp_path / "cache.json")
    folder = create_host_media_folder(tmp_path)
    HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)
    encoded = cache.path.read_bytes()
    stored = json.loads(encoded)["entries"][0]["metadata"]["acoustic_fingerprint"]
    assert stored.startswith("u32z:")
    assert len(encoded) < len(fingerprint)
    scanner = HostMediaScanner(cache)
    pending = scanner.scan((folder,), checkpoint=lambda: None)
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert pending.cache == HostMediaCacheStats(reused=1)
    assert library.sources[0].acoustic_fingerprint == fingerprint


def test_external_cache_reuse_does_not_retain_previously_selected_folder_artwork(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "Outside"
    outside.mkdir()
    song = outside / "song.wav"
    _write_wav(song)
    Image.new("RGB", (8, 8), "blue").save(outside / "cover.png")
    selected = tmp_path / "Selected"
    selected.mkdir()
    (selected / "external.m3u8").write_text(f"{song}\n", encoding="utf-8")
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    original = scanner.scan(
        (create_host_media_folder(outside),), checkpoint=lambda: None
    )
    assert scanner.complete(
        original, frozenset(), checkpoint=lambda: None
    ).artwork_sources
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    assert pending.external_references[0].target == HostPath(song)
    library = scanner.complete(
        pending, frozenset({HostPath(song)}), checkpoint=lambda: None
    )
    assert library.cache.reused == 1
    assert len(library.snapshot.tracks) == 1
    assert not library.artwork_sources


def test_wave_id3_text_is_used_instead_of_the_filename(tmp_path: Path) -> None:
    path = tmp_path / "filename.wav"
    _write_wav(path)
    tagged = cast("_MutableWave", WAVE(path))  # type: ignore[no-untyped-call]
    tagged.add_tags()
    assert tagged.tags is not None
    tagged.tags.add(TIT2(encoding=3, text=["Real title"]))  # type: ignore[no-untyped-call]
    tagged.tags.add(TPE1(encoding=3, text=["Real artist"]))  # type: ignore[no-untyped-call]
    tagged.save()
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert result.snapshot.tracks[0].title == "Real title"
    assert result.snapshot.tracks[0].artist == "Real artist"


def test_fast_file_progress_is_published_while_earlier_file_is_still_reading(
    tmp_path: Path,
) -> None:
    for name in ("a-slow.wav", "b-fast.wav"):
        _write_wav(tmp_path / name)
    published = threading.Event()
    events: list[HostMediaScanProgress] = []

    class Fingerprinter:
        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            if source.path.name == "a-slow.wav":
                assert published.wait(5), (
                    "Finished files were hidden behind the slow file"
                )
            return "1,2,3"

    def progress(event: HostMediaScanProgress) -> None:
        events.append(event)
        if (
            event.completed == 1
            and event.path is not None
            and event.path.path.name == "b-fast.wav"
        ):
            published.set()

    HostMediaScanner(fingerprinter=Fingerprinter(), max_workers=2).scan(
        (create_host_media_folder(tmp_path),),
        checkpoint=lambda: None,
        progress=progress,
    )
    assert published.is_set()
    finished = next(event for event in events if event.completed == 1)
    assert isinstance(finished.message, SourceText)
    assert finished.message.source == "Read file {index} of {total}…"
    assert dict(finished.message.parameters) == {"index": "1", "total": "2"}


def test_inspection_refills_workers_before_the_first_batch_finishes(
    tmp_path: Path,
) -> None:
    for index in range(12):
        _write_wav(tmp_path / f"{index:02d}.wav")
    later_published = threading.Event()

    class Fingerprinter:
        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            if source.path.name == "00.wav":
                assert later_published.wait(5), "A slow file blocked later batches"
            checkpoint()
            return "1,2,3"

    def progress(event: HostMediaScanProgress) -> None:
        if (
            event.stage is HostMediaScanStage.READING
            and event.completed
            and event.path == HostPath(tmp_path / "08.wav")
        ):
            later_published.set()

    pending = HostMediaScanner(fingerprinter=Fingerprinter(), max_workers=2).scan(
        (create_host_media_folder(tmp_path),),
        checkpoint=lambda: None,
        progress=progress,
    )
    assert later_published.is_set()
    assert pending.cache == HostMediaCacheStats(inspected=12)
    assert [record.path.path.name for record in pending.records] == [
        f"{index:02d}.wav" for index in range(12)
    ]


def test_inspection_cancellation_stops_queued_work(tmp_path: Path) -> None:
    for index in range(40):
        _write_wav(tmp_path / f"{index:02d}.wav")
    cancelled = threading.Event()
    called: list[HostPath] = []

    def checkpoint() -> None:
        if cancelled.is_set():
            raise HostMediaScanCancelledError()

    class Fingerprinter:
        def fingerprint(
            self, source: HostPath, *, checkpoint: Callable[[], None]
        ) -> str:
            called.append(source)
            if source.path.name != "00.wav":
                assert cancelled.wait(5), "Cancellation was not published"
            checkpoint()
            return "1,2,3"

    def progress(event: HostMediaScanProgress) -> None:
        if event.stage is HostMediaScanStage.READING and event.completed:
            cancelled.set()

    with pytest.raises(HostMediaScanCancelledError):
        HostMediaScanner(fingerprinter=Fingerprinter(), max_workers=2).scan(
            (create_host_media_folder(tmp_path),),
            checkpoint=checkpoint,
            progress=progress,
        )
    assert 1 <= len(called) <= 3


class _MutagenReader(Protocol):
    def File(self, source: BinaryIO, *, easy: bool = False) -> object: ...


class _FrameTags(Protocol):
    def add(self, frame: object) -> None: ...


class _MutableWave(Protocol):
    tags: _FrameTags | None

    def add_tags(self) -> None: ...

    def save(self) -> None: ...


class _DictionaryLikeTags:
    """Match Mutagen's get-capable tag containers without claiming Mapping."""

    def __init__(self) -> None:
        self._values: dict[str, object] = {
            "album": ["The Album"],
            "albumartist": ["The Album Artist"],
            "artist": ["The Artist"],
            "date": ["2024-05-17"],
            "discnumber": ["2/3"],
            "genre": ["Rock"],
            "title": ["The Title"],
            "tracknumber": ["4/12"],
        }

    def get(self, key: str) -> object:
        return self._values.get(key)

    def set(self, key: str, value: object) -> None:
        self._values[key] = value


class _TaggedMediaInfo:
    length = 123.456
    bitrate = 256_000
    sample_rate = 48_000


class _TaggedMedia:
    tags = _DictionaryLikeTags()
    info = _TaggedMediaInfo()


@pytest.mark.parametrize(
    ("tag", "value", "expected"),
    [
        ("stik", [2], MediaKind.AUDIOBOOK),
        ("stik", [21], MediaKind.PODCAST),
        ("pcst", True, MediaKind.PODCAST),
        ("media_type", ["audiobook"], MediaKind.AUDIOBOOK),
    ],
)
def test_explicit_spoken_word_classification_survives_scan_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tag: str,
    value: object,
    expected: MediaKind,
) -> None:
    selected = tmp_path / "spoken"
    selected.mkdir()
    _write_wav(selected / "episode.wav")
    tags = _DictionaryLikeTags()
    tags.set(tag, value)

    class Media:
        info = _TaggedMediaInfo()

        def __init__(self) -> None:
            self.tags = tags

    def open_media(*_args: object, **_kwargs: object) -> Media:
        return Media()

    monkeypatch.setattr(mutagen, "File", open_media)
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    first = scanner.scan((create_host_media_folder(selected),), checkpoint=lambda: None)
    second = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    first_library = scanner.complete(first, frozenset(), checkpoint=lambda: None)
    second_library = scanner.complete(second, frozenset(), checkpoint=lambda: None)
    assert first_library.snapshot.tracks[0].media_kind is expected
    assert second_library.snapshot.tracks[0].media_kind is expected
    assert first_library.audio_count == second_library.audio_count == 1
    assert second.cache.reused == 1


def test_m4b_is_scanned_as_an_audiobook_without_explicit_kind_tags(
    tmp_path: Path,
) -> None:
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "media"
    (tmp_path / "book.m4b").write_bytes(
        base64.decodebytes((fixtures / "tone.m4a.b64").read_bytes())
    )
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(result.snapshot.tracks) == 1
    assert result.snapshot.tracks[0].media_kind is MediaKind.AUDIOBOOK


@pytest.fixture(autouse=True)
def _stub_fpcalc(monkeypatch: pytest.MonkeyPatch) -> None:
    def fingerprint(
        _self: FpcalcFingerprinter,
        _source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        checkpoint()
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)


def _write_wav(path: Path) -> None:
    with wave.open(os.fspath(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8_000)
        stream.writeframes(b"\0\0" * 80)


def test_explicit_files_do_not_scan_sibling_media(tmp_path: Path) -> None:
    selected = tmp_path / "selected.wav"
    _write_wav(selected)
    _write_wav(tmp_path / "unrelated.wav")
    photo = tmp_path / "selected.png"
    Image.new("RGB", (8, 8)).save(photo)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (), files=(HostPath(selected), HostPath(photo)), checkpoint=lambda: None
    )
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(result.snapshot.tracks) == 1
    assert result.snapshot.tracks[0].title == "selected"
    assert result.snapshot.photos is not None
    assert len(result.snapshot.photos.photos) == 1


def test_explicit_playlist_keeps_reference_review_and_revalidates_scope(
    tmp_path: Path,
) -> None:
    song = tmp_path / "song.wav"
    _write_wav(song)
    playlist = tmp_path / "favorites.m3u"
    playlist.write_text("song.wav\nsong.wav\n", encoding="utf-8")
    scanner = HostMediaScanner()
    pending = scanner.scan((), files=(HostPath(playlist),), checkpoint=lambda: None)
    assert len(pending.external_references) == 1
    denied = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert not denied.snapshot.tracks
    accepted = scanner.complete(
        pending, frozenset((HostPath(song),)), checkpoint=lambda: None
    )
    assert len(accepted.snapshot.tracks) == 1
    assert len(accepted.snapshot.playlists[0].entries) == 2
    assert not any(
        "changed during Playlist review" in issue.detail for issue in accepted.issues
    )
    playlist.write_text("#changed\nsong.wav\n", encoding="utf-8")
    changed = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert any(
        "changed during Playlist review" in issue.detail
        and issue.path == HostPath(playlist)
        for issue in changed.issues
    )


@pytest.mark.parametrize("recurse", [False, True])
def test_folder_drop_scope_respects_recursion_and_deduplicates_files(
    tmp_path: Path, recurse: bool
) -> None:
    song = tmp_path / "song.wav"
    _write_wav(song)
    child = tmp_path / "child"
    child.mkdir()
    _write_wav(child / "nested.wav")
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (HostMediaFolder(HostPath(tmp_path), recurse=recurse),),
        files=(HostPath(song),),
        checkpoint=lambda: None,
    )
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert len(result.snapshot.tracks) == (2 if recurse else 1)


@pytest.mark.parametrize("external", [False, True])
def test_overlapping_sources_share_one_track_and_preserve_playlist_occurrences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, external: bool
) -> None:
    selected = tmp_path / "Selected"
    album = selected / "Album"
    album.mkdir(parents=True)
    song = (tmp_path if external else album) / "Song.wav"
    _write_wav(song)
    first_playlist = selected / "First.m3u8"
    second_playlist = album / "Second.m3u8"
    first_playlist.write_text(f"{song}\n{song}\n", encoding="utf-8")
    second_playlist.write_text(f"{song}\n", encoding="utf-8")
    fingerprinted: list[HostPath] = []

    def fingerprint(
        _self: FpcalcFingerprinter,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        checkpoint()
        fingerprinted.append(source)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected), create_host_media_folder(album)),
        files=(HostPath(first_playlist),)
        if external
        else (HostPath(first_playlist), HostPath(song)),
        checkpoint=lambda: None,
    )
    if external:
        assert len(pending.external_references) == 1
        assert set(pending.external_references[0].playlists) == {
            HostPath(first_playlist),
            HostPath(second_playlist),
        }
    else:
        assert pending.external_references == ()
    library = scanner.complete(
        pending,
        frozenset({HostPath(song)}) if external else frozenset(),
        checkpoint=lambda: None,
    )

    assert len(library.snapshot.tracks) == 1
    track = library.snapshot.tracks[0]
    assert sum(source.path == HostPath(song) for source in library.sources) == 1
    assert len(fingerprinted) == 1
    playlists = {playlist.name: playlist for playlist in library.snapshot.playlists}
    assert len(playlists["First"].entries) == 2
    assert len(playlists["Second"].entries) == 1
    entries = (*playlists["First"].entries, *playlists["Second"].entries)
    assert {entry.track_id for entry in entries} == {track.track_id}
    assert len({entry.entry_id for entry in entries}) == 3
    assert library.incomplete_playlist_ids == ()


@pytest.mark.parametrize("parent_recursive", [False, True])
@pytest.mark.parametrize("child_recursive", [False, True])
@pytest.mark.parametrize("child_first", [False, True])
def test_overlapping_folders_are_listed_once_with_each_selection_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_recursive: bool,
    child_recursive: bool,
    child_first: bool,
) -> None:
    root = tmp_path / "Selected"
    child = root / "Album"
    nested = child / "Nested"
    nested.mkdir(parents=True)
    for directory in (root, child, nested):
        _write_wav(directory / "Track.wav")
        Image.new("RGB", (8, 8), "red").save(directory / "Photo.png")
    parent_selection = HostMediaFolder(
        HostPath(root), parent_recursive, frozenset({HostMediaType.AUDIO})
    )
    child_selection = HostMediaFolder(
        HostPath(child), child_recursive, frozenset({HostMediaType.PHOTOS})
    )
    folders: tuple[HostMediaFolder, ...] = (parent_selection, child_selection)
    if child_first:
        folders = tuple(reversed(folders))
    native = LocalHostDirectory.list_entries
    listings: list[HostPath] = []

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        listings.append(self.path)
        return native(
            self,
            checkpoint=checkpoint,
            on_issue=on_issue,
            include_file=include_file,
            include_directories=include_directories,
            on_entry=on_entry,
        )

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    pending = HostMediaScanner().scan(folders, checkpoint=lambda: None)
    expected = {HostPath(root / "Track.wav"), HostPath(child / "Photo.png")}
    if parent_recursive:
        expected.update((HostPath(child / "Track.wav"), HostPath(nested / "Track.wav")))
    if child_recursive:
        expected.add(HostPath(nested / "Photo.png"))
    assert {record.path for record in pending.records} == expected
    expected_directories = {HostPath(root): 2, HostPath(child): 2}
    if parent_recursive or child_recursive:
        expected_directories[HostPath(nested)] = 2
    assert Counter(listings) == expected_directories


def test_explicit_files_reuse_folder_observations_even_when_their_type_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    track = HostPath(tmp_path / "Track.wav")
    _write_wav(Path(track.path))
    _write_wav(tmp_path / "Excluded.wav")
    folder = HostMediaFolder(
        HostPath(tmp_path), media_types=frozenset({HostMediaType.PHOTOS})
    )
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    scanner.scan((folder,), files=(track,), checkpoint=lambda: None)

    def unexpected_observation(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("An explicitly selected file already listed must not be restatted")

    monkeypatch.setattr(LocalHostFile, "observe", unexpected_observation)
    pending = scanner.scan((folder,), files=(track, track), checkpoint=lambda: None)
    assert [record.path for record in pending.records] == [track]
    assert pending.cache == HostMediaCacheStats(reused=1)


def test_discovery_progress_is_live_throttled_and_finishes_with_exact_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(20):
        _write_wav(tmp_path / f"{index:02d}.wav")
    native = LocalHostDirectory.list_entries
    clock = 0.0
    listing_active = False
    events: list[tuple[HostMediaScanProgress, bool]] = []
    monkeypatch.setattr("iOpenPod.app.host_media_library.perf_counter", lambda: clock)

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        nonlocal clock, listing_active

        def discovered(entry: HostDirectoryEntry) -> None:
            nonlocal clock
            clock += 0.02
            if on_entry is not None:
                on_entry(entry)

        listing_active = True
        try:
            return native(
                self,
                checkpoint=checkpoint,
                on_issue=on_issue,
                include_file=include_file,
                include_directories=include_directories,
                on_entry=discovered,
            )
        finally:
            listing_active = False

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    HostMediaScanner(max_directory_workers=1).scan(
        (create_host_media_folder(tmp_path),),
        checkpoint=lambda: None,
        progress=lambda event: events.append((event, listing_active)),
    )
    discovery = [
        (event, active)
        for event, active in events
        if event.stage is HostMediaScanStage.DISCOVERING
        and isinstance(event.message, SourceText)
    ]
    assert any(active for _event, active in discovery)
    assert 3 <= len(discovery) <= 6
    assert all(event.total == event.completed == 0 for event, _active in discovery)
    final = discovery[-1][0]
    assert isinstance(final.message, SourceText)
    assert dict(final.message.parameters) == {"folders": "1", "files": "20"}
    assert final.path is not None
    assert not discovery[-1][1]


def test_directory_listings_overlap_with_bounded_workers_and_owner_thread_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a", "b", "c", "d", "e"):
        directory = tmp_path / name
        directory.mkdir()
        _write_wav(directory / "song.wav")
    native = LocalHostDirectory.list_entries
    both_running = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum = 0
    owner = threading.get_ident()
    listings: list[HostPath] = []
    events: list[HostMediaScanProgress] = []

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        nonlocal active, maximum
        with lock:
            listings.append(self.path)
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both_running.set()
        try:
            if self.path.path != tmp_path:
                assert both_running.wait(5), "Directory listings did not overlap"
            return native(
                self,
                checkpoint=checkpoint,
                on_issue=on_issue,
                include_file=include_file,
                include_directories=include_directories,
                on_entry=on_entry,
            )
        finally:
            with lock:
                active -= 1

    def progress(event: HostMediaScanProgress) -> None:
        assert threading.get_ident() == owner
        events.append(event)

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    pending = HostMediaScanner(max_directory_workers=2).scan(
        (
            create_host_media_folder(tmp_path),
            create_host_media_folder(tmp_path / "a"),
        ),
        checkpoint=lambda: None,
        progress=progress,
    )
    assert maximum == 2
    assert len(pending.records) == 5
    assert Counter(listings) == {
        HostPath(path): 2 for path in [tmp_path, *(tmp_path / name for name in "abcde")]
    }
    discovery = [
        event
        for event in events
        if event.stage is HostMediaScanStage.DISCOVERING
        and isinstance(event.message, SourceText)
    ]
    assert isinstance(discovery[-1].message, SourceText)
    assert dict(discovery[-1].message.parameters) == {"folders": "6", "files": "5"}


def test_parallel_discovery_publishes_live_progress_and_cancels_blocked_listings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "song.wav")
    entered = threading.Event()
    cancelled = threading.Event()
    owner = threading.get_ident()
    native = LocalHostDirectory.list_entries
    calls = 0

    def checkpoint() -> None:
        if cancelled.is_set():
            raise HostMediaScanCancelledError()

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        nonlocal calls
        calls += 1
        entered.set()
        assert cancelled.wait(5), "No live directory progress was published"
        return native(
            self,
            checkpoint=checkpoint,
            on_issue=on_issue,
            include_file=include_file,
            include_directories=include_directories,
            on_entry=on_entry,
        )

    def progress(event: HostMediaScanProgress) -> None:
        assert threading.get_ident() == owner
        if event.stage is HostMediaScanStage.DISCOVERING and entered.is_set():
            cancelled.set()

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    with pytest.raises(HostMediaScanCancelledError):
        HostMediaScanner(max_directory_workers=2).scan(
            (create_host_media_folder(tmp_path),),
            checkpoint=checkpoint,
            progress=progress,
        )
    assert cancelled.is_set()
    assert calls == 1


def test_unavailable_explicit_file_is_reported_without_scanning_parent(
    tmp_path: Path,
) -> None:
    _write_wav(tmp_path / "other.wav")
    missing = HostPath(tmp_path / "missing.wav")
    scanner = HostMediaScanner()
    pending = scanner.scan((), files=(missing,), checkpoint=lambda: None)
    assert not pending.records
    assert any(issue.path == missing for issue in pending.issues)


def test_metadata_parsers_receive_read_only_storage_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "Song.wav")
    streams: list[BinaryIO] = []

    def read_tags(source: BinaryIO, *, easy: bool = False) -> _TaggedMedia:
        del easy
        assert source.readable() and source.seekable() and not source.writable()
        assert source.read(4) == b"RIFF"
        streams.append(source)
        return _TaggedMedia()

    monkeypatch.setattr(mutagen, "File", read_tags)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.snapshot.tracks[0].title == "The Title"
    assert len(streams) == 1  # Native tags and artwork share one parse.
    assert all(stream.closed for stream in streams)
    assert not library.issues


def test_cancellation_inside_metadata_read_closes_the_storage_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_wav(tmp_path / "Song.wav")
    cancelled = False
    streams: list[BinaryIO] = []

    def checkpoint() -> None:
        if cancelled:
            raise RuntimeError("Cancelled during metadata read")

    def read_tags(source: BinaryIO, *, easy: bool = False) -> _TaggedMedia:
        del easy
        nonlocal cancelled
        streams.append(source)
        cancelled = True
        source.read(1)
        pytest.fail("A cancelled Storage read must not reach the media parser")

    monkeypatch.setattr(mutagen, "File", read_tags)
    with pytest.raises(RuntimeError, match="Cancelled during metadata read"):
        HostMediaScanner().scan(
            (create_host_media_folder(tmp_path),), checkpoint=checkpoint
        )
    assert len(streams) == 1 and streams[0].closed


def _image_bytes(color: str) -> bytes:
    payload = BytesIO()
    Image.new("RGB", (12, 8), color).save(payload, format="PNG")
    return payload.getvalue()


def _embed_front_cover(path: Path, color: str) -> None:
    media = cast("_MutableWave", WAVE(path))  # type: ignore[no-untyped-call]
    media.add_tags()
    assert media.tags is not None
    media.tags.add(
        APIC(
            mime="image/png",
            type=PictureType.COVER_FRONT,
            desc="Front cover",
            data=_image_bytes(color),
        )  # type: ignore[no-untyped-call]
    )
    media.save()


def _fixture_library(tmp_path: Path) -> tuple[Path, Path]:
    selected = tmp_path / "Selected"
    selected.mkdir()
    external = tmp_path / "External.wav"
    internal = selected / "Internal.wav"
    _write_wav(internal)
    _write_wav(external)
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "media"
    (selected / "Movie.mp4").write_bytes(
        base64.decodebytes((fixtures / "tone.m4a.b64").read_bytes())
    )
    Image.new("RGB", (12, 8), "#31547a").save(selected / "Cover.png")
    (selected / "Road Trip.m3u8").write_text(
        f"#EXTM3U\n{internal.name}\n{external}\n",
        encoding="utf-8",
    )
    return selected, external


def test_scan_builds_the_common_library_and_reviews_external_playlist_files(
    tmp_path: Path,
) -> None:
    selected, external = _fixture_library(tmp_path)
    scanner = HostMediaScanner()

    pending = scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    assert len(pending.external_references) == 1
    offender = pending.external_references[0]
    assert offender.target == HostPath(external)
    assert offender.playlists == (HostPath(selected / "Road Trip.m3u8"),)
    assert offender.available is True

    denied = scanner.complete(
        pending,
        frozenset(),
        checkpoint=lambda: None,
    )
    assert isinstance(denied.snapshot, LibrarySnapshot)
    assert denied.audio_count == 1
    assert denied.video_count == 1
    assert denied.photo_count == 1
    assert denied.playlist_count == 1
    assert len(denied.snapshot.playlists[0].entries) == 1
    assert denied.snapshot.photos is not None
    representation = denied.snapshot.photos.photos[0].representations[0]
    assert (representation.width, representation.height) == (12, 8)

    accepted = scanner.complete(
        pending,
        frozenset({HostPath(external)}),
        checkpoint=lambda: None,
    )
    assert accepted.audio_count == 2
    assert accepted.video_count == 1
    assert len(accepted.snapshot.playlists[0].entries) == 2
    assert {
        media_type
        for track in accepted.snapshot.tracks
        for media_type in track.media_types
    } == {MediaType.AUDIO, MediaType.VIDEO}
    track_sources = [
        source for source in accepted.sources if source.kind.value in {"audio", "video"}
    ]
    assert track_sources
    assert all(source.acoustic_fingerprint == "1,2,3" for source in track_sources)
    photo_sources = [
        source for source in accepted.sources if source.kind.value == "photo"
    ]
    assert len(photo_sources) == 1
    assert photo_sources[0].content_sha256 is not None


def test_completed_scan_lazily_loads_bounded_host_photo_pixels(
    tmp_path: Path,
) -> None:
    selected, _external = _fixture_library(tmp_path)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.snapshot.photos is not None
    photo = library.snapshot.photos.photos[0]
    loader = HostMediaPhotoLoader()
    loader.replace_library(library)

    image = loader.load_photo(PhotoRequest(photo.photo_id, target_px=6))

    assert image is not None
    assert image.photo_id == photo.photo_id
    assert image.format_id == 0
    assert (image.width, image.height) == (6, 4)
    assert len(image.rgb888) == 6 * 4 * 3


def test_host_track_artwork_prefers_embedded_front_cover_over_folder_art(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    track_path = selected / "Track.wav"
    _write_wav(track_path)
    _embed_front_cover(track_path, "#c83232")
    Image.new("RGB", (12, 8), "#3250c8").save(selected / "cover.png")
    scanner = HostMediaScanner()

    pending = scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    track = library.snapshot.tracks[0]
    loader = HostMediaArtworkLoader()
    loader.replace_library(library)

    assert track.artwork_id > 0
    image = loader.load_artwork(ArtworkRequest(track.artwork_id, target_px=6))
    assert image is not None
    assert (image.width, image.height) == (6, 4)
    assert image.rgb888[:3] == bytes((200, 50, 50))


def test_host_track_artwork_falls_back_to_common_folder_cover_names(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    track_path = selected / "Track.wav"
    _write_wav(track_path)
    Image.new("RGB", (12, 8), "#32c850").save(selected / "cover.png")
    Image.new("RGB", (12, 8), "#c83232").save(selected / "front.png")
    scanner = HostMediaScanner()

    pending = scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    track = library.snapshot.tracks[0]
    loader = HostMediaArtworkLoader()
    loader.replace_library(library)

    assert track.artwork_id > 0
    image = loader.load_artwork(ArtworkRequest(track.artwork_id, target_px=6))
    assert image is not None
    assert image.rgb888[:3] == bytes((50, 200, 80))


def test_new_folder_cover_invalidates_an_unchanged_cached_track(tmp_path: Path) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    track_path = selected / "Track.wav"
    _write_wav(track_path)
    cache_path = tmp_path / "cache" / "host-media-library-v7.json"
    folder = HostMediaFolder(
        create_host_media_folder(selected).path,
        media_types=frozenset({HostMediaType.AUDIO}),
    )
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    first_pending = scanner.scan((folder,), checkpoint=lambda: None)
    first = scanner.complete(first_pending, frozenset(), checkpoint=lambda: None)
    assert first.snapshot.tracks[0].artwork_id == 0

    Image.new("RGB", (12, 8), "#32c850").save(selected / "cover.png")
    second_scanner = HostMediaScanner(AtomicHostFile(cache_path))
    second_pending = second_scanner.scan((folder,), checkpoint=lambda: None)
    second = second_scanner.complete(
        second_pending,
        frozenset(),
        checkpoint=lambda: None,
    )

    assert second.cache.inspected == 0
    assert second.cache.reused == 1
    assert second.snapshot.tracks[0].artwork_id > 0


def test_folder_cover_bytes_are_not_reread_until_file_facts_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "Track.wav")
    cover = selected / "cover.bmp"
    Image.new("RGB", (12, 8), "#32c850").save(cover)
    cache_path = tmp_path / "cache" / "host-media-library.json"
    folder = HostMediaFolder(
        HostPath(selected), media_types=frozenset({HostMediaType.AUDIO})
    )
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    first_pending = scanner.scan((folder,), checkpoint=lambda: None)
    first = scanner.complete(first_pending, frozenset(), checkpoint=lambda: None)

    native_open_read = LocalHostFile.open_read
    cover_reads = 0

    def counted_open_read(
        self: LocalHostFile,
        *,
        checkpoint: Callable[[], None] | None = None,
        max_bytes: int | None = None,
    ) -> object:
        nonlocal cover_reads
        if self.path == HostPath(cover):
            cover_reads += 1
        return native_open_read(self, checkpoint=checkpoint, max_bytes=max_bytes)

    monkeypatch.setattr(LocalHostFile, "open_read", counted_open_read)
    original_mtime = cover.stat().st_mtime_ns
    Image.new("RGB", (12, 8), "#c83232").save(cover)
    os.utime(cover, ns=(original_mtime, original_mtime))

    unchanged_pending = HostMediaScanner(AtomicHostFile(cache_path)).scan(
        (folder,), checkpoint=lambda: None
    )
    unchanged = scanner.complete(
        unchanged_pending, frozenset(), checkpoint=lambda: None
    )
    assert cover_reads == 0
    assert unchanged.cache.reused == 1
    assert (
        unchanged.snapshot.tracks[0].artwork_id == first.snapshot.tracks[0].artwork_id
    )

    os.utime(
        cover,
        ns=(original_mtime + 1_000_000_000, original_mtime + 1_000_000_000),
    )
    changed_pending = HostMediaScanner(AtomicHostFile(cache_path)).scan(
        (folder,), checkpoint=lambda: None
    )
    changed = scanner.complete(changed_pending, frozenset(), checkpoint=lambda: None)
    assert cover_reads == 1
    assert changed.cache.inspected == 0
    assert changed.cache.reused == 1
    assert changed.snapshot.tracks[0].artwork_id != first.snapshot.tracks[0].artwork_id


@pytest.mark.parametrize("version", [9, 10])
def test_prior_host_cache_reuses_unchanged_media_and_cover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "Track.wav")
    cover = selected / "cover.bmp"
    Image.new("RGB", (12, 8), "#32c850").save(cover)
    cache_path = tmp_path / "cache" / "host-media-library.json"
    folder = HostMediaFolder(
        HostPath(selected), media_types=frozenset({HostMediaType.AUDIO})
    )
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    first = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(first, frozenset(), checkpoint=lambda: None)

    document = json.loads(cache_path.read_text(encoding="utf-8"))
    document["version"] = version
    document["entries"][0]["metadata"].pop("metadata_complete")
    if version == 10:
        document["entries"][0]["metadata"]["payload_sha256"] = "a" * 64
    document["catalog_sha256"] = hashlib.sha256(
        json.dumps(
            document["entries"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if version == 9:
        document.pop("folder_artwork")
        document.pop("folder_artwork_sha256")
    cache_path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    native_open_read = LocalHostFile.open_read

    def reject_cover_read(
        self: LocalHostFile,
        *,
        checkpoint: Callable[[], None] | None = None,
        max_bytes: int | None = None,
    ) -> object:
        if self.path in (HostPath(cover), HostPath(selected / "Track.wav")):
            pytest.fail("Cache migration reread unchanged media or artwork")
        return native_open_read(self, checkpoint=checkpoint, max_bytes=max_bytes)

    monkeypatch.setattr(LocalHostFile, "open_read", reject_cover_read)
    upgraded = HostMediaScanner(AtomicHostFile(cache_path)).scan(
        (folder,), checkpoint=lambda: None
    )

    assert upgraded.cache == HostMediaCacheStats(reused=1)
    assert (
        scanner.complete(upgraded, frozenset(), checkpoint=lambda: None)
        .sources[0]
        .acoustic_fingerprint
        == "1,2,3"
    )
    stored = json.loads(cache_path.read_text(encoding="utf-8"))
    assert stored["version"] == 11
    assert "payload_sha256" not in stored["entries"][0]["metadata"]


def test_folder_cover_cache_is_independent_of_embedded_artwork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    track_path = selected / "Track.wav"
    _write_wav(track_path)
    _embed_front_cover(track_path, "#c83232")
    cover = selected / "cover.bmp"
    Image.new("RGB", (12, 8), "#32c850").save(cover)
    cache_path = tmp_path / "cache" / "host-media-library.json"
    folder = HostMediaFolder(
        HostPath(selected), media_types=frozenset({HostMediaType.AUDIO})
    )
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    first_pending = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(first_pending, frozenset(), checkpoint=lambda: None)

    native_open_read = LocalHostFile.open_read

    def reject_cover_read(
        self: LocalHostFile,
        *,
        checkpoint: Callable[[], None] | None = None,
        max_bytes: int | None = None,
    ) -> object:
        if self.path == HostPath(cover):
            pytest.fail("Unchanged folder cover must not be read again")
        return native_open_read(self, checkpoint=checkpoint, max_bytes=max_bytes)

    monkeypatch.setattr(LocalHostFile, "open_read", reject_cover_read)
    second = HostMediaScanner(AtomicHostFile(cache_path)).scan(
        (folder,), checkpoint=lambda: None
    )
    assert second.cache.reused == 1


def test_partial_scan_preserves_other_folder_cover_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders: list[HostMediaFolder] = []
    for name in ("Left", "Right"):
        selected = tmp_path / name
        selected.mkdir()
        _write_wav(selected / "Track.wav")
        Image.new("RGB", (12, 8), "#32c850").save(selected / "cover.bmp")
        folders.append(
            HostMediaFolder(
                HostPath(selected), media_types=frozenset({HostMediaType.AUDIO})
            )
        )
    cache_path = tmp_path / "cache" / "host-media-library.json"
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    scanner.scan(tuple(folders), checkpoint=lambda: None)
    scanner.scan((folders[0],), checkpoint=lambda: None)

    native_open_read = LocalHostFile.open_read

    def reject_right_cover_read(
        self: LocalHostFile,
        *,
        checkpoint: Callable[[], None] | None = None,
        max_bytes: int | None = None,
    ) -> object:
        if self.path == HostPath(tmp_path / "Right" / "cover.bmp"):
            pytest.fail("Partial scan discarded unchanged folder cover facts")
        return native_open_read(self, checkpoint=checkpoint, max_bytes=max_bytes)

    monkeypatch.setattr(LocalHostFile, "open_read", reject_right_cover_read)
    right = scanner.scan((folders[1],), checkpoint=lambda: None)
    assert right.cache.reused == 1


@pytest.mark.parametrize("has_cover", [False, True])
def test_folder_scan_lists_each_directory_once_per_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    has_cover: bool,
) -> None:
    selected = tmp_path / "Selected"
    album = selected / "Album"
    album.mkdir(parents=True)
    for name in ("First.wav", "Second.wav"):
        _write_wav(album / name)
    (album / "notes.txt").write_text("Not media", encoding="utf-8")
    if has_cover:
        Image.new("RGB", (12, 8), "red").save(album / "COVER.PNG")
    folder = HostMediaFolder(
        HostPath(selected), media_types=frozenset({HostMediaType.AUDIO})
    )
    native = LocalHostDirectory.list_entries
    listings: list[HostPath] = []
    entry_counts: list[int] = []

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        listings.append(self.path)
        entries = native(
            self,
            checkpoint=checkpoint,
            on_issue=on_issue,
            include_file=include_file,
            include_directories=include_directories,
            on_entry=on_entry,
        )
        entry_counts.append(len(entries))
        return entries

    def unexpected_read(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("A warm scan must not reread unchanged media or artwork")

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    caplog.set_level(logging.INFO, logger="iOpenPod.app.host_media_library")
    cache = AtomicHostFile(tmp_path / "cache.json")
    for warm in (False, True):
        listings.clear()
        entry_counts.clear()
        caplog.clear()
        if warm:
            monkeypatch.setattr(LocalHostFile, "open_read", unexpected_read)
        scanner = HostMediaScanner(cache)
        pending = scanner.scan((folder,), checkpoint=lambda: None)
        library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
        assert library.audio_count == 2
        assert library.photo_count == 0
        assert all(
            bool(track.artwork_id) == has_cover for track in library.snapshot.tracks
        )
        assert library.cache == (
            HostMediaCacheStats(reused=2) if warm else HostMediaCacheStats(inspected=2)
        )
        assert listings == [HostPath(selected), HostPath(album)] * 2
        assert sum(entry_counts) == 2 * (3 + has_cover)
        assert caplog.text.count("directory_listings=2") == 2
        assert caplog.text.count("reused_listings=1, fallback_listings=0") == 2
        assert "tracks_without_fingerprint=0" in caplog.text


@pytest.mark.parametrize("change", ["add", "replace", "remove", "prefer"])
def test_final_pass_refreshes_shared_folder_artwork_observations(
    tmp_path: Path, change: str
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "Track.wav")
    cover = selected / "cover.png"
    old_cover = selected / "front.png" if change == "prefer" else cover
    if change != "add":
        Image.new("RGB", (12, 8), "red").save(old_cover)
    folder = HostMediaFolder(
        HostPath(selected), media_types=frozenset({HostMediaType.AUDIO})
    )
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    initial = scanner.scan((folder,), checkpoint=lambda: None)
    original = scanner.complete(initial, frozenset(), checkpoint=lambda: None)
    changed = False

    def change_cover(progress: HostMediaScanProgress) -> None:
        nonlocal changed
        if progress.stage is HostMediaScanStage.FINALIZING and not changed:
            changed = True
            if change == "remove":
                cover.unlink()
            else:
                Image.new("RGB", (16, 10), "blue").save(cover)

    pending = scanner.scan((folder,), checkpoint=lambda: None, progress=change_cover)
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.cache == HostMediaCacheStats(reused=1)
    assert (
        library.snapshot.tracks[0].artwork_id != original.snapshot.tracks[0].artwork_id
    )
    if change == "remove":
        assert library.snapshot.tracks[0].artwork_id == 0
        assert not library.artwork_sources
    else:
        assert library.artwork_sources[0].path == HostPath(cover)
        assert (
            library.artwork_sources[0].content_sha256
            == hashlib.sha256(cover.read_bytes()).hexdigest()
        )


def test_explicit_track_retains_folder_artwork_without_scanning_sibling_media(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    track = tmp_path / "Selected.wav"
    _write_wav(track)
    _write_wav(tmp_path / "Sibling.wav")
    Image.new("RGB", (12, 8), "red").save(tmp_path / "cover.png")
    native = LocalHostFile._from_stat  # pyright: ignore[reportPrivateUsage]

    def observe(
        cls: type[LocalHostFile], path: HostPath, value: os.stat_result
    ) -> LocalHostFile:
        assert path.path.name != "Sibling.wav", "Artwork lookup inspected sibling media"
        return native(path, value)

    monkeypatch.setattr(LocalHostFile, "_from_stat", classmethod(observe))
    caplog.set_level(logging.INFO, logger="iOpenPod.app.host_media_library")
    scanner = HostMediaScanner()
    pending = scanner.scan((), files=(HostPath(track),), checkpoint=lambda: None)
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.audio_count == 1
    assert library.snapshot.tracks[0].title == "Selected"
    assert library.snapshot.tracks[0].artwork_id > 0
    assert caplog.text.count("reused_listings=0, fallback_listings=1") == 2


def test_shared_folder_artwork_observations_do_not_follow_links(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "Track.wav")
    external_cover = tmp_path / "private.png"
    Image.new("RGB", (12, 8), "red").save(external_cover)
    try:
        (selected / "cover.png").symlink_to(external_cover)
    except OSError as error:
        pytest.skip(f"Host does not permit symlink creation: {error}")
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.audio_count == 1
    assert library.snapshot.tracks[0].artwork_id == 0


def test_unavailable_folder_artwork_does_not_abort_a_host_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "Track.wav")
    Image.new("RGB", (12, 8), "#32c850").save(selected / "cover.png")
    folder = HostMediaFolder(
        HostPath(selected),
        media_types=frozenset({HostMediaType.AUDIO}),
    )

    def unavailable(*_args: object, **_kwargs: object) -> object:
        from storage import StorageError

        raise StorageError("iCloud placeholder is unavailable")

    monkeypatch.setattr(
        "iOpenPod.app.host_media_library._folder_artwork_for", unavailable
    )

    pending = HostMediaScanner().scan((folder,), checkpoint=lambda: None)
    result = HostMediaScanner().complete(pending, frozenset(), checkpoint=lambda: None)

    assert result.audio_count == 1
    assert result.snapshot.tracks[0].artwork_id == 0


def test_scan_keeps_available_media_when_the_host_tree_changes(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "Track.wav")

    class MutatingFingerprinter:
        def fingerprint(
            self,
            source: HostPath,
            *,
            checkpoint: Callable[[], None],
        ) -> str:
            checkpoint()
            _write_wav(selected / "Added.wav")
            return "1,2,3"

    pending = HostMediaScanner(fingerprinter=MutatingFingerprinter()).scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    assert len(pending.records) == 1
    assert any(
        "changed while it was scanned" in issue.detail for issue in pending.issues
    )


def test_host_photo_loader_rejects_files_changed_after_the_scan(
    tmp_path: Path,
) -> None:
    selected, _external = _fixture_library(tmp_path)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.snapshot.photos is not None
    photo = library.snapshot.photos.photos[0]
    loader = HostMediaPhotoLoader()
    loader.replace_library(library)
    changed = selected / "Cover.png"
    previous = changed.stat().st_mtime_ns
    Image.new("RGB", (20, 20), "#000000").save(changed)
    os.utime(changed, ns=(previous + 1_000_000_000, previous + 1_000_000_000))

    with pytest.raises(HostMediaTreeChangedError, match="changed after"):
        loader.load_photo(PhotoRequest(photo.photo_id, target_px=6))


def test_unchanged_files_are_reused_from_the_persistent_scan_cache(
    tmp_path: Path,
) -> None:
    selected, external = _fixture_library(tmp_path)
    cache_path = tmp_path / "cache" / "host-media-library-v7.json"
    folder = create_host_media_folder(selected)
    first_scanner = HostMediaScanner(AtomicHostFile(cache_path))

    first_pending = first_scanner.scan((folder,), checkpoint=lambda: None)
    first = first_scanner.complete(
        first_pending,
        frozenset({HostPath(external)}),
        checkpoint=lambda: None,
    )

    assert first.cache.inspected == 5
    assert first.cache.reused == 0
    assert cache_path.is_file()

    second_scanner = HostMediaScanner(AtomicHostFile(cache_path))
    second_pending = second_scanner.scan((folder,), checkpoint=lambda: None)
    second = second_scanner.complete(
        second_pending,
        frozenset({HostPath(external)}),
        checkpoint=lambda: None,
    )

    assert second.cache.inspected == 0
    assert second.cache.reused == 5
    assert second.snapshot == first.snapshot
    assert second.sources == first.sources


def test_ipod_tag_drift_rereads_the_host_track_and_refreshes_cached_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    track_path = selected / "Track.wav"
    _write_wav(track_path)
    tags = _DictionaryLikeTags()
    tags.set("title", ["Original title"])

    class Media:
        info = _TaggedMediaInfo()

        def __init__(self) -> None:
            self.tags = tags

    reads = 0

    def read_media(*_args: object, **_kwargs: object) -> Media:
        nonlocal reads
        reads += 1
        return Media()

    monkeypatch.setattr(mutagen, "File", read_media)
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    folder = create_host_media_folder(selected)
    first = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(first, frozenset(), checkpoint=lambda: None)
    tags.set("title", ["Current Host title"])
    cached = scanner.scan((folder,), checkpoint=lambda: None)
    library = scanner.complete(cached, frozenset(), checkpoint=lambda: None)
    assert library.snapshot.tracks[0].title == "Original title"
    assert reads == 1

    refreshed = scanner.refresh_tracks(
        library, frozenset({HostPath(track_path)}), checkpoint=lambda: None
    )
    assert reads == 2
    assert refreshed.snapshot.tracks[0].title == "Current Host title"
    assert (
        refreshed.sources[0].acoustic_fingerprint
        == library.sources[0].acoustic_fingerprint
    )

    repeated = scanner.scan((folder,), checkpoint=lambda: None)
    repeated_library = scanner.complete(repeated, frozenset(), checkpoint=lambda: None)
    assert reads == 2
    assert repeated_library.snapshot.tracks[0].title == "Current Host title"


def test_tag_drift_refresh_rejects_changed_host_file_facts(tmp_path: Path) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    track_path = selected / "Track.wav"
    _write_wav(track_path)
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    with track_path.open("ab") as stream:
        stream.write(b"changed")

    with pytest.raises(HostMediaTreeChangedError, match="changed before inspection"):
        scanner.refresh_tracks(
            library, frozenset({HostPath(track_path)}), checkpoint=lambda: None
        )


def test_cache_uses_kind_specific_metadata_documents(tmp_path: Path) -> None:
    selected, _external = _fixture_library(tmp_path)
    cache_path = tmp_path / "cache" / "host-media-library-v7.json"
    scanner = HostMediaScanner(AtomicHostFile(cache_path))

    scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    document = json.loads(cache_path.read_text(encoding="utf-8"))
    assert document["version"] == 11
    entries = {entry["kind"]: entry for entry in document["entries"]}
    assert set(entries) == {"audio", "video", "photo", "playlist"}
    common = {
        "kind",
        "metadata",
        "modified_ns",
        "path",
        "size_bytes",
        "warning",
    }
    assert all(set(entry) == common for entry in entries.values())
    assert set(entries["audio"]["metadata"]) == {
        "album",
        "album_artist",
        "artist",
        "bitrate_kbps",
        "disc_number",
        "genre",
        "length_ms",
        "sample_rate_hz",
        "title",
        "total_discs",
        "total_tracks",
        "track_number",
        "year",
        "media_type",
        "tag_values",
        "acoustic_fingerprint",
        "metadata_complete",
        "artwork_content_sha256",
        "artwork_kind",
        "artwork_modified_ns",
        "artwork_path",
        "artwork_size_bytes",
    }
    assert entries["audio"]["metadata"]["acoustic_fingerprint"] == "1,2,3"
    assert entries["video"]["metadata"]["acoustic_fingerprint"] == "1,2,3"
    assert set(entries["video"]["metadata"]) == set(entries["audio"]["metadata"])
    assert set(entries["photo"]["metadata"]) == {
        "content_sha256",
        "height",
        "width",
    }
    assert set(entries["playlist"]["metadata"]) == {"references", "title"}

    entries["audio"]["metadata"]["acoustic_fingerprint"] = "not-raw"
    catalog = json.dumps(
        document["entries"],
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    document["catalog_sha256"] = hashlib.sha256(catalog).hexdigest()
    cache_path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    rebuilt = HostMediaScanner(AtomicHostFile(cache_path)).scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    assert rebuilt.cache == HostMediaCacheStats(inspected=4)


def test_failed_fingerprints_are_reported_and_retried_on_the_next_scan(
    tmp_path: Path,
) -> None:
    selected, _external = _fixture_library(tmp_path)
    cache_path = tmp_path / "cache" / "host-media-library-v7.json"

    class FailingFingerprinter:
        def __init__(self) -> None:
            self.calls = 0

        def fingerprint(
            self,
            source: HostPath,
            *,
            checkpoint: Callable[[], None],
        ) -> str:
            del source
            checkpoint()
            self.calls += 1
            raise FpcalcError("no usable audio stream")

    fingerprinter = FailingFingerprinter()
    scanner = HostMediaScanner(AtomicHostFile(cache_path), fingerprinter)
    pending = scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    assert fingerprinter.calls == 2
    assert sum("Acoustic fingerprint" in issue.detail for issue in library.issues) == 2
    assert all(
        source.acoustic_fingerprint is None
        for source in library.sources
        if source.kind.value in {"audio", "video"}
    )

    HostMediaScanner(AtomicHostFile(cache_path), fingerprinter).scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    assert fingerprinter.calls == 4


def test_scan_fingerprints_host_tracks_concurrently(tmp_path: Path) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_wav(selected / "First.wav")
    _write_wav(selected / "Second.wav")
    rendezvous = threading.Barrier(2)
    lock = threading.Lock()

    class ConcurrentFingerprinter:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0

        def fingerprint(
            self,
            source: HostPath,
            *,
            checkpoint: Callable[[], None],
        ) -> str:
            del source
            checkpoint()
            with lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
            try:
                rendezvous.wait(timeout=0.5)
            except threading.BrokenBarrierError:
                pass
            finally:
                with lock:
                    self.active -= 1
            return "1,2,3"

    fingerprinter = ConcurrentFingerprinter()
    HostMediaScanner(fingerprinter=fingerprinter, max_workers=2).scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    assert fingerprinter.maximum_active >= 2


def test_dictionary_like_track_tags_survive_the_cache_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    (selected / "Track.flac").write_bytes(b"fixture")
    cache_path = tmp_path / "cache" / "host-media-library-v7.json"
    folder = create_host_media_folder(selected)

    def read_tagged_media(
        _path: str,
        options: object = None,
        easy: bool = False,
    ) -> _TaggedMedia:
        assert options is None
        assert isinstance(easy, bool)
        return _TaggedMedia()

    monkeypatch.setattr(
        mutagen,
        "File",
        read_tagged_media,
    )
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    pending = scanner.scan((folder,), checkpoint=lambda: None)
    first = scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    def unexpected_read(
        _path: str,
        options: object = None,
        easy: bool = False,
    ) -> object:
        raise AssertionError("unchanged tagged media should be loaded from cache")

    monkeypatch.setattr(
        mutagen,
        "File",
        unexpected_read,
    )
    cached_scanner = HostMediaScanner(AtomicHostFile(cache_path))
    cached_pending = cached_scanner.scan((folder,), checkpoint=lambda: None)
    cached = cached_scanner.complete(
        cached_pending,
        frozenset(),
        checkpoint=lambda: None,
    )

    assert cached.cache.inspected == 0
    assert cached.cache.reused == 1
    assert cached.snapshot == first.snapshot
    track = cached.snapshot.tracks[0]
    assert track.title == "The Title"
    assert track.artist == "The Artist"
    assert track.album == "The Album"
    assert track.album_artist == "The Album Artist"
    assert track.genre == "Rock"
    assert track.year == 2024
    assert track.track_number == 4
    assert track.metadata.total_tracks == 12
    assert track.metadata.disc_number == 2
    assert track.metadata.total_discs == 3
    assert track.length_ms == 123_456
    assert track.bitrate_kbps == 256
    assert track.metadata.sample_rate_hz == 48_000


def test_changed_file_is_reinspected_while_unchanged_files_stay_cached(
    tmp_path: Path,
) -> None:
    selected, _external = _fixture_library(tmp_path)
    cache_path = tmp_path / "host-media-library-v7.json"
    folder = create_host_media_folder(selected)
    scanner = HostMediaScanner(AtomicHostFile(cache_path))
    first_pending = scanner.scan((folder,), checkpoint=lambda: None)
    scanner.complete(first_pending, frozenset(), checkpoint=lambda: None)
    movie = selected / "Movie.mp4"
    previous = movie.stat().st_mtime_ns
    movie.write_bytes(b"a changed MP4 payload")
    os.utime(movie, ns=(previous + 1_000_000_000, previous + 1_000_000_000))

    second_pending = HostMediaScanner(AtomicHostFile(cache_path)).scan(
        (folder,),
        checkpoint=lambda: None,
    )

    assert second_pending.cache.inspected == 1
    assert second_pending.cache.reused == 3


def test_external_playlist_review_has_one_decision_per_target_file(
    tmp_path: Path,
) -> None:
    selected, external = _fixture_library(tmp_path)
    second_playlist = selected / "Favorites.m3u"
    second_playlist.write_text(os.fspath(external), encoding="utf-8")

    pending = HostMediaScanner().scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    assert len(pending.external_references) == 1
    assert pending.external_references[0].playlists == (
        HostPath(second_playlist),
        HostPath(selected / "Road Trip.m3u8"),
    )


@pytest.mark.parametrize("scope", ["outside", "excluded_type", "nonrecursive"])
def test_playlist_targets_need_approval_for_the_actual_selected_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    target = (
        tmp_path / "Song.wav"
        if scope == "outside"
        else selected / "Song.wav"
        if scope == "excluded_type"
        else selected / "Nested" / "Song.wav"
    )
    target.parent.mkdir(exist_ok=True)
    _write_wav(target)
    (selected / "Mix.m3u8").write_text(f"{target}\n{target}\n", encoding="utf-8")
    inspected: list[HostPath] = []

    def fingerprint(
        _self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        checkpoint()
        inspected.append(source)
        assert Path(source).read_bytes() == target.read_bytes()
        assert source != HostPath(target)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    folder = HostMediaFolder(
        HostPath(selected),
        recurse=False,
        media_types=frozenset({HostMediaType.PLAYLISTS})
        if scope == "excluded_type"
        else frozenset(HostMediaType),
    )
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
    pending = scanner.scan((folder,), checkpoint=lambda: None)
    assert len(pending.external_references) == 1
    assert inspected == []
    denied = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert not denied.snapshot.tracks
    assert not denied.snapshot.playlists[0].entries
    assert inspected == []
    accepted = scanner.complete(
        pending, frozenset({HostPath(target)}), checkpoint=lambda: None
    )
    assert len(accepted.snapshot.tracks) == 1
    entries = accepted.snapshot.playlists[0].entries
    assert len(entries) == 2
    assert entries[0].entry_id != entries[1].entry_id
    assert entries[0].track_id == entries[1].track_id
    assert len(inspected) == 1 and not Path(inspected[0]).exists()
    # Prior approval/cache entries never authorize a later scan automatically.
    rescanned = scanner.scan((folder,), checkpoint=lambda: None)
    assert len(rescanned.external_references) == 1
    assert not scanner.complete(
        rescanned, frozenset(), checkpoint=lambda: None
    ).snapshot.tracks


def test_playlist_review_disables_unsupported_missing_and_nested_targets(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    nested = tmp_path / "Nested.m3u8"
    nested.write_text("Hidden.wav", encoding="utf-8")
    (tmp_path / "Private.txt").write_text("private", encoding="utf-8")
    (selected / "Mix.m3u8").write_text(
        "../Nested.m3u8\n../Missing.wav\n../Private.txt", encoding="utf-8"
    )
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    assert len(pending.external_references) == 3
    assert all(
        not reference.available and reference.detail
        for reference in pending.external_references
    )
    with pytest.raises(ValueError, match="Unavailable"):
        scanner.complete(
            pending, frozenset({HostPath(nested)}), checkpoint=lambda: None
        )
    with pytest.raises(ValueError, match="pending playlist review"):
        scanner.complete(
            pending,
            frozenset({HostPath(tmp_path / "Hidden.wav")}),
            checkpoint=lambda: None,
        )


def test_replaced_external_file_is_not_read_after_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected, external = _fixture_library(tmp_path)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    before = external.stat()
    replacement = tmp_path / "replacement.wav"
    replacement.write_bytes(external.read_bytes())
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(external)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A replacement must never be inspected under the old approval")

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", forbidden)
    result = scanner.complete(
        pending, frozenset({HostPath(external)}), checkpoint=lambda: None
    )
    assert result.audio_count == 1
    assert any(
        issue.path == HostPath(external) and "changed" in issue.detail
        for issue in result.issues
    )


def test_selected_tree_is_revalidated_after_external_review(tmp_path: Path) -> None:
    selected, _external = _fixture_library(tmp_path)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    (selected / "Road Trip.m3u8").write_text("Changed.wav", encoding="utf-8")
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    assert result.audio_count == 1
    assert any(
        "changed during Playlist review" in issue.detail for issue in result.issues
    )


@pytest.mark.parametrize("extension", ["pls", "xspf", "wpl", "asx"])
def test_added_playlist_formats_reach_the_common_snapshot(
    tmp_path: Path, extension: str
) -> None:
    _write_wav(tmp_path / "Song.wav")
    payload = {
        "pls": "[playlist]\nFile1=Song.wav\nFile2=Song.wav\n",
        "xspf": '<playlist xmlns="http://xspf.org/ns/0/"><title>Favorites</title><trackList><track><location>Song.wav</location></track><track><location>Song.wav</location></track></trackList></playlist>',
        "wpl": '<smil><head><title>Favorites</title></head><body><seq><media src="Song.wav"/><media src="Song.wav"/></seq></body></smil>',
        "asx": '<asx><title>Favorites</title><entry><ref href="Song.wav"/></entry><entry><ref href="Song.wav"/></entry></asx>',
    }[extension]
    (tmp_path / f"Favorites.{extension}").write_text(payload, encoding="utf-8")
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    assert not pending.external_references
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.snapshot.playlists[0].name == "Favorites"
    assert len(library.snapshot.playlists[0].entries) == 2


def test_playlist_storage_rejection_is_a_scan_issue_not_a_scan_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storage import FileSizeLimitError
    from storage.host_input import LocalHostFile

    (tmp_path / "Mix.m3u8").write_text("Song.wav", encoding="utf-8")

    def bounded_read(*args: object, **kwargs: object) -> bytes:
        raise FileSizeLimitError("Playlist exceeds read limit")

    monkeypatch.setattr(LocalHostFile, "read_bytes", bounded_read)
    pending = HostMediaScanner().scan(
        (create_host_media_folder(tmp_path),), checkpoint=lambda: None
    )
    assert not pending.external_references
    assert any("read limit" in issue.detail for issue in pending.issues)


def test_external_embedded_artwork_retains_storage_authorization_after_scan(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "Selected"
    selected.mkdir()
    external = tmp_path / "Song.wav"
    _write_wav(external)
    _embed_front_cover(external, "red")
    (selected / "Mix.m3u8").write_text("../Song.wav", encoding="utf-8")
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    library = scanner.complete(
        pending, frozenset({HostPath(external)}), checkpoint=lambda: None
    )
    loader = HostMediaArtworkLoader()
    loader.replace_library(library)
    request = ArtworkRequest(library.snapshot.tracks[0].artwork_id, target_px=6)
    assert loader.load_artwork(request) is not None
    # A byte-identical replacement still needs a new scan/approval identity.
    original = external.stat()
    replacement = tmp_path / "Replacement.wav"
    replacement.write_bytes(external.read_bytes())
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    replacement.replace(external)
    with pytest.raises(HostMediaTreeChangedError, match="no longer safe"):
        loader.load_artwork(request)
