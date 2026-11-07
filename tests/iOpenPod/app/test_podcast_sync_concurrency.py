"""Podcast downloads overlap Host preparation without parallel device access."""

from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, get_ident
from typing import TYPE_CHECKING

import pytest
from tests.iOpenPod.app.podcast_sync_test_support import (
    PodcastOpenerFactory,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app import sync_execution
from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.library_write import PreparationCancelledError
from iOpenPod.app.media.inspection import _parse  # pyright: ignore[reportPrivateUsage]
from iOpenPod.app.media.transcoding import MediaTranscoder, PreparedTranscode
from iOpenPod.app.podcasts import media
from iOpenPod.app.podcasts.sync import PodcastSyncPlan
from iOpenPod.app.sync_execution import SyncExecutor
from iPodDB.library import AudioEncoding
from storage import DevicePath, FilesystemSession, HostPath, capture_host_file
from storage.media_processing import MediaTools

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from iOpenPod.app.library_write import WriteProgress
    from iOpenPod.app.podcasts.sync import PodcastEpisodeAddition


def _additions(count: int) -> tuple[PodcastEpisodeAddition, ...]:
    seed = podcast_addition()
    return tuple(
        replace(
            seed,
            episode=replace(
                seed.episode,
                episode_id=str(index),
                guid=f"guid-{index}",
                enclosure_url=f"https://publisher.example/{index}.m4a",
            ),
        )
        for index in range(count)
    )


@contextmanager
def _prepare(
    _self: MediaTranscoder, source: HostPath, *args: object, **kwargs: object
) -> Generator[PreparedTranscode]:
    with capture_host_file(source, checkpoint=lambda: None) as captured:
        inspection = _parse(
            json.dumps(
                {
                    "format": {
                        "format_name": "m4a",
                        "duration": "1.0",
                        "size": str(captured.fingerprint.size),
                    },
                    "streams": [
                        {
                            "index": 0,
                            "codec_type": "audio",
                            "codec_name": "aac",
                            "sample_rate": "44100",
                            "channels": 2,
                        }
                    ],
                }
            ).encode(),
            captured,
        )
        yield PreparedTranscode(
            captured.snapshot,
            inspection,
            AudioEncoding.AAC,
            captured.fingerprint,
            False,
        )


@pytest.fixture
def prepared_media(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace codec work, retaining actual Storage captures and Sync orchestration."""
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(b"media"))

    def fingerprint(
        _self: FpcalcFingerprinter,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        checkpoint()
        assert Path(source).is_file()
        return "1,2,3"

    monkeypatch.setattr(MediaTranscoder, "prepare", _prepare)
    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)


@pytest.mark.parametrize("stage", ("download", "prepare"))
def test_next_download_starts_while_an_episode_is_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepared_media: None,
    stage: str,
) -> None:
    device = build_device(tmp_path)
    first_started = Event()
    second_started = Event()
    overlapped: list[bool] = []
    downloads: list[Path] = []
    download_episode = media.download_episode

    @contextmanager
    def download(
        addition: PodcastEpisodeAddition,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[int, int | None], None] | None = None,
    ) -> Generator[HostPath]:
        if addition.episode.episode_id == "0":
            if stage == "download":
                first_started.set()
                overlapped.append(second_started.wait(1))
        else:
            assert first_started.wait(1)
            second_started.set()
        with download_episode(
            addition, checkpoint=checkpoint, progress=progress
        ) as source:
            downloads.append(Path(source))
            yield source

    @contextmanager
    def preparing(
        transcoder: MediaTranscoder, source: HostPath, *args: object, **kwargs: object
    ) -> Generator[PreparedTranscode]:
        if stage == "prepare" and not first_started.is_set():
            first_started.set()
            overlapped.append(second_started.wait(1))
        with _prepare(transcoder, source, *args, **kwargs) as result:
            yield result

    monkeypatch.setattr(sync_execution, "download_episode", download)
    monkeypatch.setattr(MediaTranscoder, "prepare", preparing)
    try:
        with ExitStack() as resources:
            prepared, issues = SyncExecutor(
                device.coordinator, workers=2
            )._prepare_podcasts(  # pyright: ignore[reportPrivateUsage]
                podcast_request(device.active),
                PodcastSyncPlan(additions=_additions(2)),
                MediaTools(HostPath(tmp_path), HostPath(tmp_path), None, frozenset()),
                resources,
                lambda _: None,
                lambda: None,
                (),
            )
            assert overlapped == [True], f"The next download waited for {stage}"
            assert len(prepared) == 2, issues
            assert not issues
            assert all(path.exists() for path in downloads)
            assert len({p.song.track.metadata.location for p in prepared}) == 2
        assert all(not path.exists() for path in downloads)
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("workers,limit", ((1, 1), (2, 2), (16, 4)))
def test_concurrency_is_bounded_and_progress_and_paths_stay_on_owner_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepared_media: None,
    workers: int,
    limit: int,
) -> None:
    device = build_device(tmp_path)
    owner = get_ident()
    release = Event()
    lock = Lock()
    running = 0
    peak = 0
    events: list[WriteProgress] = []
    download_episode = media.download_episode
    exists = FilesystemSession.exists

    @contextmanager
    def download(
        addition: PodcastEpisodeAddition,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[int, int | None], None] | None = None,
    ) -> Generator[HostPath]:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        with ExitStack() as lifetime:
            try:
                assert release.wait(2), "Concurrent items never appeared in progress"
                if addition.episode.episode_id == "0":
                    raise OSError("Publisher unavailable")
                source = lifetime.enter_context(
                    download_episode(addition, checkpoint=checkpoint, progress=progress)
                )
            finally:
                with lock:
                    running -= 1
            yield source

    def progress(update: WriteProgress) -> None:
        assert get_ident() == owner
        events.append(update)
        if len(update.active_items) == limit:
            assert len({item.item_id for item in update.active_items}) == limit
            with lock:
                if running == limit:
                    release.set()

    def path_exists(self: FilesystemSession, path: DevicePath) -> bool:
        assert get_ident() == owner, "A worker accessed the iPod"
        return exists(self, path)

    monkeypatch.setattr(sync_execution, "download_episode", download)
    monkeypatch.setattr(FilesystemSession, "exists", path_exists)
    try:
        with ExitStack() as resources:
            prepared, issues = SyncExecutor(
                device.coordinator, workers=workers
            )._prepare_podcasts(  # pyright: ignore[reportPrivateUsage]
                podcast_request(device.active),
                PodcastSyncPlan(additions=_additions(7)),
                MediaTools(HostPath(tmp_path), HostPath(tmp_path), None, frozenset()),
                resources,
                progress,
                lambda: None,
                (),
            )
            assert peak == limit
            assert [p.episode.episode_id for p in prepared if p.episode] == [
                str(index) for index in range(1, 7)
            ]
            assert len(issues) == 1 and issues[0].code == "sync.podcast_failed"
            assert len({p.song.track.metadata.location for p in prepared}) == 6
            assert events[-1].completed == events[-1].total == 7
            assert not events[-1].active_items
    finally:
        release.set()
        device.coordinator.close()


@pytest.mark.parametrize("abort", ("cancel", "progress_error"))
@pytest.mark.parametrize("already_prepared", (False, True))
def test_abort_joins_downloads_and_cleans_captures_without_starting_more(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepared_media: None,
    abort: str,
    already_prepared: bool,
) -> None:
    device = build_device(tmp_path)
    cancelled = Event()
    downloads: list[Path] = []
    download_episode = media.download_episode

    def checkpoint() -> None:
        if cancelled.is_set():
            raise PreparationCancelledError

    @contextmanager
    def download(
        addition: PodcastEpisodeAddition,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[int, int | None], None] | None = None,
    ) -> Generator[HostPath]:
        with download_episode(
            addition, checkpoint=checkpoint, progress=progress
        ) as source:
            downloads.append(Path(source))
            assert progress is not None
            progress(1, 2)
            if not already_prepared:
                for _ in range(400):
                    checkpoint()
                    if cancelled.wait(0.005):
                        checkpoint()
            yield source

    def progress(update: WriteProgress) -> None:
        should_abort = (
            bool(update.completed) if already_prepared else len(downloads) == 2
        )
        if should_abort:
            assert all(path.exists() for path in downloads)
            if abort == "progress_error":
                raise RuntimeError("Progress consumer failed")
            cancelled.set()

    monkeypatch.setattr(sync_execution, "download_episode", download)
    try:
        with (
            pytest.raises(
                RuntimeError if abort == "progress_error" else PreparationCancelledError
            ),
            ExitStack() as resources,
        ):
            SyncExecutor(device.coordinator, workers=2)._prepare_podcasts(  # pyright: ignore[reportPrivateUsage]
                podcast_request(device.active),
                PodcastSyncPlan(additions=_additions(8)),
                MediaTools(HostPath(tmp_path), HostPath(tmp_path), None, frozenset()),
                resources,
                progress,
                checkpoint,
                (),
            )
        assert 1 <= len(downloads) <= 2 if already_prepared else len(downloads) == 2
        assert all(not path.exists() for path in downloads)
        device.assert_original()
    finally:
        device.coordinator.close()
