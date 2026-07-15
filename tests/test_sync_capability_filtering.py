from pathlib import Path
from types import SimpleNamespace

from iopenpod.sync.contracts import StorageSummary, SyncAction, SyncItem, SyncPlan
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
from iopenpod.sync.integrity import IntegrityReport
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.pc_library import PCLibrary, PCTrack
from iopenpod.sync.photos import PhotoSyncItem, PhotoSyncPlan
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext


def _track(
    title: str,
    *,
    size: int,
    extension: str,
    is_video: bool = False,
    is_podcast: bool = False,
) -> PCTrack:
    filename = f"{title}{extension}"
    return PCTrack(
        path=f"/tmp/{filename}",
        relative_path=filename,
        filename=filename,
        extension=extension,
        mtime=0.0,
        size=size,
        title=title,
        artist="Artist",
        album="Album",
        album_artist=None,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=1000,
        bitrate=None,
        sample_rate=None,
        rating=None,
        is_video=is_video,
        is_podcast=is_podcast,
    )


def test_executor_filters_unsupported_video_podcast_and_photo(tmp_path: Path) -> None:
    audio_item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_track("Song", size=10, extension=".mp3"),
        estimated_size=10,
    )
    video_item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_track("Movie", size=20, extension=".m4v", is_video=True),
        estimated_size=20,
    )
    podcast_item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_track("Episode", size=30, extension=".mp3", is_podcast=True),
        estimated_size=30,
    )
    photo_plan = PhotoSyncPlan()
    photo_plan.photos_to_add = [PhotoSyncItem("hash", "Photo")]
    photo_plan.thumb_bytes_to_add = 100
    plan = SyncPlan(
        to_add=[audio_item, video_item, podcast_item],
        photo_plan=photo_plan,
        storage=StorageSummary(bytes_to_add=160),
    )
    ctx = _SyncContext(
        plan=plan,
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    executor = SyncExecutor(
        tmp_path,
        device_capabilities=SimpleNamespace(
            supports_video=False,
            supports_podcast=False,
            supports_photo=False,
        ),
    )

    executor._apply_device_capability_filters(ctx)

    assert plan.to_add == [audio_item]
    assert plan.photo_plan is None
    assert plan.storage.bytes_to_add == 10
    assert ctx.result.errors
    assert "video is not supported" in ctx.result.errors[0][1]
    assert "podcasts are not supported" in ctx.result.errors[0][1]
    assert "photos are not supported" in ctx.result.errors[0][1]


def test_diff_engine_skips_photo_planning_when_device_lacks_photo_support(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class EmptyLibrary(PCLibrary):
        def __init__(self, root_path: Path):
            super().__init__(root_path)

        def scan(
            self,
            progress_callback=None,
            include_video: bool = True,
            max_workers=None,
            is_cancelled=None,
        ):
            return iter(())

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.is_fpcalc_available",
        lambda _path="": True,
    )
    monkeypatch.setattr(
        "iopenpod.sync.integrity.check_integrity",
        lambda *_args, **_kwargs: IntegrityReport(),
    )
    monkeypatch.setattr(
        "iopenpod.sync.audio_fingerprint.FingerprintCache.get_instance",
        lambda *_args: SimpleNamespace(save=lambda: None),
    )

    def fail_read_photo_db(_path):
        raise AssertionError("photo DB should not be read")

    monkeypatch.setattr(
        "iopenpod.sync.fingerprint_diff_engine.read_photo_db",
        fail_read_photo_db,
    )

    engine = FingerprintDiffEngine(
        EmptyLibrary(tmp_path),
        tmp_path,
        supports_photo=False,
    )

    plan = engine.compute_diff([])

    assert plan.photo_plan is None
