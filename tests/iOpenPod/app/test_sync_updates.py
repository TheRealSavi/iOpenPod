"""Sync update combinations through real scans, database verification and Storage."""

import base64
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import NoReturn, Protocol, cast

import pytest
from mutagen.mp3 import MP3
from PIL import Image
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device

from iOpenPod.app.artwork_policy import rockbox_tag_policy
from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.host_media_library import HostMediaLibrary, HostMediaScanner
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.media.lyrics import embedded_lyrics
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    SyncOptions,
)
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    host_path_identity,
    prepare_sync_plan,
    select_sync_plan,
)
from iPodDB.library import Track, TrackMetadata
from storage import AtomicHostFile, HostPath

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="Media tools required",
)
FIXTURES = Path(__file__).parents[2] / "fixtures" / "media"


class _ArtworkFrame(Protocol):
    data: bytes


class _ID3Tags(Protocol):
    def __getitem__(self, key: str) -> object: ...

    def getall(self, key: str) -> list[_ArtworkFrame]: ...


class _MPEGInfo(Protocol):
    frame_offset: int


class _MP3File(Protocol):
    tags: _ID3Tags | None
    info: _MPEGInfo | None


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> NoReturn:
        pytest.fail("Tag and artwork updates must not prepare replacement media")


@pytest.mark.parametrize("model", ["M9802", "MB565"])
@pytest.mark.parametrize(
    "case,rockbox",
    [
        ("title", True),
        ("title", False),
        ("lyrics", False),
        ("cover", True),
        ("cover", False),
        ("all", True),
        ("all", False),
        ("remove", True),
        ("remove", False),
        ("enable", True),
        ("retry", True),
        ("payload", True),
        ("payload", False),
        ("reencoded", True),
        ("reencoded", False),
    ],
)
def test_updates_retain_payload_and_commit_only_required_changes(
    tmp_path: Path,
    model: str,
    case: str,
    rockbox: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Control acoustic evidence while real media verifies the selected write path.
    acoustic = "1,2,3"

    def fingerprint(*args: object, **kwargs: object) -> str:
        return acoustic

    monkeypatch.setattr(
        "iOpenPod.app.host_media_fingerprint.FpcalcFingerprinter.fingerprint",
        fingerprint,
    )
    host_dir = tmp_path / "host"
    host_dir.mkdir()
    path = host_dir / "track.mp3"
    path.write_bytes(base64.b64decode((FIXTURES / "tone.mp3.b64").read_bytes()))
    cover = host_dir / "cover.png"
    Image.new("RGB", (240, 180), (30, 80, 140)).save(cover)
    tagger = ExportMediaTagger()
    host_track = Track(
        1,
        "Original",
        "Artist",
        "Album",
        1000,
        metadata=TrackMetadata(lyrics="Old words"),
    )
    tagger.prepare(HostPath(path), host_track, None)
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "host-cache.json"))

    def scan() -> HostMediaLibrary:
        pending = scanner.scan(
            (create_host_media_folder(host_dir),), checkpoint=lambda: None
        )
        return scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    host = scan()
    device = bare_device(tmp_path, model_number=model)
    try:
        ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        active = device.active
        first_rockbox = rockbox and case != "enable"
        comparison = prepare_sync_plan(host, ipod, active.library)
        selected = select_sync_plan(
            comparison,
            selected_host_paths=frozenset({host_path_identity(str(path))}),
            selected_ipod_removals=frozenset(),
        )
        with monkeypatch.context() as embedding_patch:
            if case == "retry":

                def fail_embedding(*args: object, **kwargs: object) -> None:
                    raise ValueError("Cover embedding unavailable")

                embedding_patch.setattr(
                    "iOpenPod.app.sync_execution.MediaTranscoder.embed_artwork",
                    fail_embedding,
                )
            initial = SyncExecutor(device.coordinator).execute(
                SyncExecutionRequest(
                    selected,
                    host,
                    ipod,
                    active,
                    1,
                    1,
                    options=SyncOptions(rockbox_metadata=first_rockbox),
                ),
                lambda _: None,
                Event(),
            )
        assert initial.status is SyncExecutionStatus.SUCCESS, initial.issues
        assert initial.active is not None and initial.helper is not None
        active, ipod = initial.active, initial.helper
        old = next(
            track for track in active.library.tracks if track.title == "Original"
        )
        retained = replace(
            old,
            rating=80,
            play_count=5,
            metadata=replace(
                old.metadata,
                unscrobbled_play_count=3,
                checked=False,
                played=True,
                skip_count=2,
                bookmark_time_ms=50,
            ),
        )
        review = device.prepare(
            replace(
                active.library,
                tracks=tuple(
                    retained if t.track_id == old.track_id else t
                    for t in active.library.tracks
                ),
            )
        )
        saved = device.coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        active = saved.active
        old = next(t for t in active.library.tracks if t.track_id == old.track_id)
        device_path = device.root / old.metadata.location
        original_payload = _mp3_audio_bytes(device_path)
        old_bytes = device_path.read_bytes()
        art_files = {
            p: p.read_bytes()
            for p in (device.root / "iPod_Control/Artwork").iterdir()
            if p.is_file()
        }
        if case in {"title", "all", "remove"}:
            host_track = replace(host_track, title="  Updated   title  ")
        if case in {"lyrics", "all", "remove"}:
            host_track = replace(
                host_track,
                metadata=replace(
                    host_track.metadata, lyrics="" if case == "remove" else "New words"
                ),
            )
        if case == "payload":
            acoustic = "4,5,6"
        if case in {"payload", "reencoded"}:
            path.write_bytes(
                base64.b64decode((FIXTURES / "tone-vbr.mp3.b64").read_bytes())
            )
        if case not in {"enable", "retry", "cover"}:
            tagger.prepare(HostPath(path), host_track, None)
        if case in {"all", "cover"}:
            Image.new("RGB", (240, 180), (220, 30, 90)).save(cover)
        elif case == "remove":
            cover.unlink()
        host = scan()
        policy = rockbox_tag_policy(active.profile) if rockbox else None
        comparison = prepare_sync_plan(
            host, ipod, active.library, file_tag_policy=policy
        )
        selected = select_sync_plan(
            comparison,
            selected_host_paths=frozenset({host_path_identity(str(path))}),
            selected_ipod_removals=frozenset(),
        )
        selected = replace(
            selected, items=tuple(i for i in selected.items if i.host_path == str(path))
        )
        assert len(selected.items) == 1
        item = selected.items[0]
        if case == "reencoded":
            assert _mp3_audio_bytes(path) != original_payload
            assert item.action is SyncPlanAction.UNCHANGED
            assert device_path.read_bytes() == old_bytes
            return
        assert item.action is SyncPlanAction.UPDATE
        assert item.audio_payload_changed == (case == "payload")
        assert item.file_tags_changed == (case in {"enable", "retry"})
        executor = (
            SyncExecutor(device.coordinator)
            if case == "payload"
            else SyncExecutor(device.coordinator, transcoder=_NoMediaPreparation())
        )
        result = executor.execute(
            SyncExecutionRequest(
                selected,
                host,
                ipod,
                active,
                1,
                1,
                options=SyncOptions(
                    rockbox_metadata=rockbox, normalize_tags=case != "enable"
                ),
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        updated = next(
            track
            for track in result.active.library.tracks
            if track.track_id == old.track_id
        )
        if case == "payload":
            assert updated.metadata.location != old.metadata.location
            assert not device_path.exists()
            device_path = device.root / updated.metadata.location
        else:
            assert updated.metadata.location == old.metadata.location
        assert updated.size_bytes == device_path.stat().st_size
        assert updated.rating == 80 and updated.play_count == 5
        assert updated.metadata.unscrobbled_play_count == 3
        assert not updated.metadata.checked and updated.metadata.played
        assert (
            updated.metadata.skip_count == 2 and updated.metadata.bookmark_time_ms == 50
        )
        new_payload = _mp3_audio_bytes(device_path)
        assert (new_payload != original_payload) == (case == "payload")
        parsed = _read_mp3(device_path)
        assert embedded_lyrics(parsed) == host_track.metadata.lyrics
        if rockbox:
            assert parsed.tags is not None
            assert str(parsed.tags["TIT2"]) == updated.title
            pictures = parsed.tags.getall("APIC")
            assert bool(pictures) == (case != "remove")
            if pictures and model == "M9802":
                import io

                with Image.open(io.BytesIO(pictures[0].data)) as embedded:
                    assert embedded.size == (120, 120)
                    assert embedded.mode == "L"
        if case not in {"all", "cover", "remove"}:
            assert updated.artwork_id == old.artwork_id
            assert {p: p.read_bytes() for p in art_files} == art_files
        elif case == "remove":
            assert updated.artwork_id == 0
        else:
            assert updated.artwork_id != old.artwork_id
        if not rockbox and case in {"title", "cover"}:
            assert device_path.read_bytes() == old_bytes
        repeated = prepare_sync_plan(
            host, result.helper, result.active.library, file_tag_policy=policy
        )
        assert (
            next(i for i in repeated.items if i.host_path == str(path)).action
            is SyncPlanAction.UNCHANGED
        )
    finally:
        device.coordinator.close()


def _read_mp3(path: Path) -> _MP3File:
    return cast("_MP3File", MP3(path))  # type: ignore[no-untyped-call]


def _mp3_audio_bytes(path: Path) -> bytes:
    """Compare actual MPEG bytes independently of the Sync decision evidence."""
    parsed = _read_mp3(path)
    assert parsed.info is not None
    with path.open("rb") as stream:
        stream.seek(parsed.info.frame_offset)
        data = stream.read()
    return data[:-128] if data[-128:-125] == b"TAG" else data
