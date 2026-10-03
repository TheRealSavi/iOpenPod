"""Behavioral tests for Host Media Library scanning and caching."""

import base64
import hashlib
import json
import os
import threading
import wave
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol, cast

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
    HostMediaScanner,
    HostMediaScanProgress,
    HostMediaTreeChangedError,
)
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.models.photos import PhotoRequest
from iPodDB.library import LibrarySnapshot, MediaKind, MediaType
from storage import AtomicHostFile, HostPath, StorageError
from storage.host_directory import HostDirectoryEntry, LocalHostDirectory


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
    ) -> tuple[HostDirectoryEntry, ...]:
        if self.path.path.name == "a-denied":
            raise PermissionError("folder unavailable")
        return native(self, checkpoint=checkpoint, on_issue=on_issue)

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
    (selected / "Movie.mp4").write_bytes(b"not a complete MP4")
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

    assert second.cache.inspected == 1
    assert second.cache.reused == 0
    assert second.snapshot.tracks[0].artwork_id > 0


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


def test_cache_uses_kind_specific_metadata_documents(tmp_path: Path) -> None:
    selected, _external = _fixture_library(tmp_path)
    cache_path = tmp_path / "cache" / "host-media-library-v7.json"
    scanner = HostMediaScanner(AtomicHostFile(cache_path))

    scanner.scan(
        (create_host_media_folder(selected),),
        checkpoint=lambda: None,
    )

    document = json.loads(cache_path.read_text(encoding="utf-8"))
    assert document["version"] == 9
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
