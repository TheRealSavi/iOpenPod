"""Automatic video covers through reviewed Sync and real Storage publication."""

import base64
import io
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest
from PIL import Image
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastOpener,
    PodcastOpenerFactory,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaScanner,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import (
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodTrackFingerprint,
    SyncDetails,
)
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.podcasts import feed_client, media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
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
from iPodDB.library import (
    ArtworkPixels,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
)
from storage import AtomicHostFile, DevicePath, HostPath

FIXTURES = Path(__file__).parents[2] / "fixtures" / "media"
FRAME = ArtworkPixels(2, 2, b"\xff\x00\x00" * 4)


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> NoReturn:
        pytest.fail("A missing video cover must not prepare replacement media")


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("cover_id", [0, 7])
@pytest.mark.parametrize("previous_digest", [None, "", "a" * 64])
def test_video_frame_plan_preserves_existing_covers_and_fills_absence(
    tmp_path: Path, available: bool, cover_id: int, previous_digest: str | None
) -> None:
    path = tmp_path / "video.mp4"
    track = Track(
        1,
        "Video",
        "",
        "",
        1000,
        media_types=(MediaType.VIDEO,),
        metadata=TrackMetadata(location=str(path)),
    )
    source = HostMediaSource(
        HostPath(path), HostMediaFileKind.VIDEO, 100, 1000, "1,2,3"
    )
    host = HostMediaLibrary(
        LibrarySnapshot(tracks=(track,)),
        (source,),
        (),
        HostMediaCacheStats(),
        unavailable_artwork_paths=frozenset() if available else frozenset({str(path)}),
    )
    device_path = DevicePath("iPod_Control/Music/F00/video.m4v")
    old = replace(
        track,
        track_id=10,
        artwork_id=cover_id,
        metadata=replace(track.metadata, location=str(device_path)),
    )
    sync = SyncDetails(
        "2026-10-20T00:00:00Z",
        str(path),
        100,
        1000,
        "mp4",
        "m4v",
        False,
        host_artwork_sha256=previous_digest,
        ipod_artwork_id=cover_id,
    )
    ipod = IPodMediaLibrary(
        (IPodTrackFingerprint(10, 10, device_path, 90, 900, "1,2,3", sync),),
        (),
        (),
        IPodMediaCacheStats(),
        None,
        False,
    )
    (item,) = prepare_sync_plan(host, ipod, LibrarySnapshot(tracks=(old,))).items
    needs_cover = not cover_id or (available and bool(previous_digest))
    assert item.action is (
        SyncPlanAction.UPDATE if needs_cover else SyncPlanAction.UNCHANGED
    )
    assert item.artwork_changed is needs_cover
    assert not item.audio_payload_changed


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="Media tools required",
)
@pytest.mark.parametrize("fixture", ["silent.mp4", "source.mkv"])
def test_video_frame_failure_retries_without_replacing_media_and_stays_in_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    path = tmp_path / fixture
    path.write_bytes(base64.b64decode((FIXTURES / f"{fixture}.b64").read_bytes()))

    def fingerprint(*args: object, **kwargs: object) -> str:
        return "1,2,3"

    monkeypatch.setattr(
        "iOpenPod.app.host_media_fingerprint.FpcalcFingerprinter.fingerprint",
        fingerprint,
    )
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "host-cache.json"))

    def scan() -> HostMediaLibrary:
        pending = scanner.scan((), files=(HostPath(path),), checkpoint=lambda: None)
        return scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    attempts: list[HostPath] = []
    fail = True

    def frame(source: HostPath, *args: object, **kwargs: object) -> ArtworkPixels:
        attempts.append(source)
        if fail:
            raise ValueError("Frame unavailable")
        return FRAME

    monkeypatch.setattr("iOpenPod.app.sync_execution.capture_video_frame", frame)
    device = bare_device(tmp_path, model_number="MB565")
    try:
        host = scan()
        ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        active = device.active

        def request() -> SyncExecutionRequest:
            selected = select_sync_plan(
                prepare_sync_plan(host, ipod, active.library),
                selected_host_paths=frozenset({host_path_identity(str(path))}),
                selected_ipod_removals=frozenset(),
            )
            selected = replace(
                selected,
                items=tuple(
                    item for item in selected.items if item.host_path == str(path)
                ),
            )
            return SyncExecutionRequest(
                selected,
                host,
                ipod,
                active,
                1,
                1,
                options=SyncOptions(rockbox_metadata=False),
            )

        added = SyncExecutor(device.coordinator).execute(
            request(), lambda _: None, Event()
        )
        assert added.status is SyncExecutionStatus.SUCCESS, added.issues
        assert added.active is not None and added.helper is not None
        assert any(issue.code == "sync.video_artwork_skipped" for issue in added.issues)
        active, ipod = added.active, added.helper
        old = next(
            track
            for track in active.library.tracks
            if track.title == host.snapshot.tracks[0].title
        )
        assert old.artwork_id == 0
        # Incoming extraction uses the prepared private copy, not the mutable Host original.
        assert attempts[0] != HostPath(path)
        media_path = device.root / old.metadata.location
        media_bytes = media_path.read_bytes()

        fail = False
        host = scan()
        cover_request = request()
        (item,) = cover_request.plan.items
        assert item.action is SyncPlanAction.UPDATE and item.artwork_changed
        assert not item.audio_payload_changed
        saved = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(cover_request, lambda _: None, Event())
        assert saved.status is SyncExecutionStatus.SUCCESS, saved.issues
        assert saved.active is not None and saved.helper is not None
        active, ipod = saved.active, saved.helper
        covered = next(
            track for track in active.library.tracks if track.track_id == old.track_id
        )
        assert covered.artwork_id > 0
        assert covered.track_id == old.track_id
        assert covered.metadata.location == old.metadata.location
        assert media_path.read_bytes() == media_bytes
        assert attempts[-1] == HostPath(path)
        assert request().plan.items[0].action is SyncPlanAction.UNCHANGED

        if fixture == "source.mkv":
            return
        # A real folder cover takes priority over the generated frame.
        cover = tmp_path / "poster.jpg"
        Image.new("RGB", (16, 16), "blue").save(cover)
        host = scan()
        count = len(attempts)
        real = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(request(), lambda _: None, Event())
        assert real.status is SyncExecutionStatus.SUCCESS, real.issues
        assert real.active is not None and real.helper is not None
        active, ipod = real.active, real.helper
        with_real_cover = next(
            track for track in active.library.tracks if track.track_id == old.track_id
        )
        assert with_real_cover.artwork_id != covered.artwork_id
        assert len(attempts) == count

        # Removing the real Host image restores the frame fallback. A transient
        # decoder failure must keep that cover and its retryable provenance.
        cover.unlink()
        host = scan()
        fail = True
        failed = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(request(), lambda _: None, Event())
        assert failed.active is not None and failed.helper is not None, failed.issues
        active, ipod = failed.active, failed.helper
        assert (
            next(
                track.artwork_id
                for track in active.library.tracks
                if track.track_id == old.track_id
            )
            == with_real_cover.artwork_id
        )
        assert request().plan.items[0].artwork_changed
        fail = False

        # Native thumbnail preparation can also defer a valid captured frame.
        # Keep the known Host-image baseline until that frame actually commits.
        def fail_encoding(*args: object, **kwargs: object) -> NoReturn:
            raise ValueError("Thumbnail encoder unavailable")

        with monkeypatch.context() as encoding_failure:
            encoding_failure.setattr(
                "iPodDB.library._artwork_writing.encode_ithmb", fail_encoding
            )
            deferred = SyncExecutor(
                device.coordinator, transcoder=_NoMediaPreparation()
            ).execute(request(), lambda _: None, Event())
        assert deferred.status is SyncExecutionStatus.PARTIAL, deferred.issues
        assert deferred.active is not None and deferred.helper is not None
        active, ipod = deferred.active, deferred.helper
        assert request().plan.items[0].artwork_changed
        restored = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(request(), lambda _: None, Event())
        assert restored.status is SyncExecutionStatus.SUCCESS, restored.issues
        assert restored.active is not None and restored.helper is not None
        active, ipod = restored.active, restored.helper
        assert next(
            track.artwork_id
            for track in active.library.tracks
            if track.track_id == old.track_id
        ) not in (
            0,
            with_real_cover.artwork_id,
        )
        assert media_path.read_bytes() == media_bytes
        assert request().plan.items[0].action is SyncPlanAction.UNCHANGED
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="Media tools required",
)
@pytest.mark.parametrize("publisher_cover", [False, True])
def test_downloaded_video_podcast_uses_frame_only_after_publisher_artwork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publisher_cover: bool
) -> None:
    data = base64.b64decode((FIXTURES / "silent.mp4.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))
    addition = podcast_addition()
    if publisher_cover:
        addition = replace(
            addition,
            subscription=replace(
                addition.subscription, artwork_url="https://publisher.example/cover.png"
            ),
        )
        image = io.BytesIO()
        Image.new("RGB", (16, 16), "blue").save(image, format="PNG")
        monkeypatch.setattr(
            feed_client, "urlopen", PodcastOpener(image.getvalue()).open
        )
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    calls: list[HostPath] = []

    def frame(source: HostPath, *args: object, **kwargs: object) -> ArtworkPixels:
        calls.append(source)
        return FRAME

    monkeypatch.setattr("iOpenPod.app.sync_execution.capture_video_frame", frame)
    device = bare_device(tmp_path, model_number="MB565")
    try:
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        episode = next(
            track
            for track in result.active.library.tracks
            if track.title == addition.episode.title
        )
        assert episode.artwork_id > 0
        assert bool(calls) is not publisher_cover
    finally:
        device.coordinator.close()
