"""Podcast media uses the shared verified Library publication and recovery path."""

from __future__ import annotations

import base64
import io
import json
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import pytest
from PIL import Image
from tests.iOpenPod.app.podcast_sync_test_support import (
    FixedPodcastPlan,
    PodcastOpener,
    PodcastOpenerFactory,
    podcast_addition,
    podcast_request,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES

from iOpenPod.app.display_text import SourceText
from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    SyncDetails,
    SyncedTrack,
)
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.podcasts import feed_client, media
from iOpenPod.app.podcasts.catalog import mark_episode_selection_listened
from iOpenPod.app.podcasts.documents import decode_history
from iOpenPod.app.podcasts.feed_client import FeedparserPodcastClient
from iOpenPod.app.podcasts.identity import episode_identity, subscription_identity
from iOpenPod.app.podcasts.models import (
    PodcastClearAge,
    PodcastFillMode,
    PodcastSubscription,
    PodcastSyncSettings,
)
from iOpenPod.app.podcasts.store import HISTORY_PATH
from iOpenPod.app.podcasts.sync import (
    PodcastSyncPlan,
    PodcastSyncRequest,
)
from iOpenPod.app.sync_execution import (
    SyncExecutionResult,
    SyncExecutionStatus,
    SyncExecutor,
)
from iOpenPod.app.sync_plan import SyncPlanAction
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import MediaKind
from storage import DevicePath, StorageOperationError

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_sync_helper import IPodTrackFingerprint
    from iOpenPod.app.library_write import WriteProgress
    from storage import HostPath
    from storage.media_processing import MediaTools


def test_download_checks_actual_size_and_cleans_private_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(b"episode media"))
    samples: list[int] = []
    with media.download_episode(
        podcast_addition(),
        checkpoint=lambda: None,
        progress=lambda size, _total: samples.append(size),
    ) as captured:
        path = Path(captured)
        assert path.read_bytes() == b"episode media"
    assert not path.exists()
    assert samples == [len(b"episode media")]
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(b"short", 100))
    with (
        pytest.raises(ValueError, match="incomplete"),
        media.download_episode(podcast_addition(), checkpoint=lambda: None),
    ):
        pytest.fail("An incomplete enclosure must never reach media preparation")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@example.com/a",
        "ftp://example.com/a",
    ],
)
def test_download_rejects_unsupported_or_credentialed_enclosures(url: str) -> None:
    addition = podcast_addition()
    addition = replace(addition, episode=replace(addition.episode, enclosure_url=url))
    with (
        pytest.raises(ValueError, match="HTTP or HTTPS"),
        media.download_episode(addition, checkpoint=lambda: None),
    ):
        pytest.fail("Unsupported URLs must not be opened")


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
def test_podcast_add_replace_and_remove_publish_verified_media_without_overwriting_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))
    addition = podcast_addition()
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    helper = device.root / str(LIBRARY_SYNC_HELPER_PATH)
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_bytes(b"existing host provenance is outside this Podcast Sync")
    try:
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        podcast = next(
            track
            for track in result.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert podcast.title == addition.episode.title
        assert podcast.metadata.podcast_rss_url == addition.subscription.feed_url
        assert podcast.metadata.podcast_enclosure_url == addition.episode.enclosure_url
        assert (
            podcast.metadata.podcast
            and podcast.metadata.skip_shuffle
            and podcast.metadata.remember_position
        )
        native = next(
            selection.chunk.header
            for selection in parse_iTunesDB(
                (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
            ).find_chunks(MhitHeader)
            if selection.chunk.header.track_id == podcast.track_id
        )
        assert native.podcast_now_playing_flag == 1
        assert podcast.metadata.release_date == addition.episode.published_at
        assert (podcast.episode_number, podcast.season_number) == (7, 2)
        path = device.root / podcast.metadata.location
        assert path.is_file()
        assert any(
            podcast.track_id in playlist.track_ids
            for playlist in result.active.library.playlists
            if playlist.system_managed
        )
        assert result.helper is None
        replacement = replace(
            addition,
            episode=replace(
                addition.episode,
                episode_id="newer-episode",
                title="Newer Episode",
                enclosure_url="https://publisher.example/newer.m4a",
            ),
            replaces_track_id=podcast.track_id,
        )
        monkeypatch.setattr(
            "iOpenPod.app.sync_execution.prepare_podcast_sync",
            FixedPodcastPlan(PodcastSyncPlan(additions=(replacement,))),
        )
        replaced = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert replaced.status is SyncExecutionStatus.SUCCESS, replaced.issues
        assert [item.action for item in replaced.completed] == [
            SyncPlanAction.ADD,
            SyncPlanAction.REMOVE,
        ]
        assert not path.exists()
        assert replaced.active is not None
        podcast = next(
            track
            for track in replaced.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert podcast.title == "Newer Episode"
        path = device.root / podcast.metadata.location
        assert path.exists()
        monkeypatch.setattr(
            "iOpenPod.app.sync_execution.prepare_podcast_sync",
            FixedPodcastPlan(PodcastSyncPlan(removals=(podcast.track_id,))),
        )
        removed = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert removed.status is SyncExecutionStatus.SUCCESS, removed.issues
        assert removed.active is not None
        assert all(
            track.track_id != podcast.track_id
            for track in removed.active.library.tracks
        )
        assert not path.exists()
        assert (
            helper.read_bytes()
            == b"existing host provenance is outside this Podcast Sync"
        )
    finally:
        device.coordinator.close()


def test_failed_podcast_replacement_preserves_existing_track_and_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    old = device.active.library.tracks[0]
    addition = replace(podcast_addition(), replaces_track_id=old.track_id)
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(b"short", 100))
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    try:
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.FAILED
        failure = next(
            issue for issue in result.issues if issue.code == "sync.podcast_failed"
        )
        assert isinstance(failure.message, SourceText)
        assert failure.message == (
            "Downloaded Episode could not be added. The Episode awaiting replacement was kept. "
            "Refresh the Podcast and retry."
        )
        assert dict(failure.message.parameters) == {"title": "Downloaded Episode"}
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
@pytest.mark.parametrize("existing_helper", (False, True))
def test_podcast_add_records_committed_episode_in_sync_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_helper: bool,
) -> None:
    device = build_device(tmp_path)
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(podcast_addition(),))),
    )
    fingerprinted: list[HostPath] = []

    def fingerprint(
        _self: FpcalcFingerprinter,
        source: HostPath,
        *,
        checkpoint: Callable[[], None],
    ) -> str:
        checkpoint()
        assert Path(source).is_file()
        fingerprinted.append(source)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    try:
        retained: tuple[IPodTrackFingerprint, ...] = ()
        if existing_helper:
            baseline = device.coordinator.publish_sync_success(
                device.active,
                podcast_request(device.active).ipod,
                (
                    SyncedTrack(
                        DevicePath(device.active.library.tracks[0].metadata.location),
                        "9,8,7",
                        SyncDetails(
                            "2026-09-26T12:00:00+00:00",
                            "previous-host-song.m4a",
                            123,
                            456,
                            "m4a",
                            "aac",
                            False,
                        ),
                    ),
                ),
            )
            retained = baseline.tracks
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        podcast = next(
            track
            for track in result.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        helper = device.root / str(LIBRARY_SYNC_HELPER_PATH)
        assert helper.is_file(), "Committed Podcast is missing from the Sync helper"
        document = json.loads(helper.read_bytes())
        entry = next(
            item for item in document["tracks"] if item["track_id"] == podcast.track_id
        )
        assert entry["acoustic_fingerprint"] == "1,2,3"
        assert entry["sync"] is None
        assert podcast.ipod is not None
        assert entry["database_track_id"] == str(podcast.ipod.db_track_id)
        assert entry["path"] == podcast.metadata.location
        assert result.helper is not None
        assert all(item in result.helper.tracks for item in retained)
        assert len(fingerprinted) == 1
        assert not Path(fingerprinted[0]).exists()

        replacement = replace(
            podcast_addition(),
            episode=replace(
                podcast_addition().episode, episode_id="new", title="New Episode"
            ),
            replaces_track_id=podcast.track_id,
        )
        monkeypatch.setattr(
            "iOpenPod.app.sync_execution.prepare_podcast_sync",
            FixedPodcastPlan(PodcastSyncPlan(additions=(replacement,))),
        )
        replaced = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert replaced.status is SyncExecutionStatus.SUCCESS, replaced.issues
        assert replaced.helper is not None
        assert all(item in replaced.helper.tracks for item in retained)
        assert all(item.track_id != podcast.track_id for item in replaced.helper.tracks)
        new = next(item for item in replaced.helper.tracks if item not in retained)
        assert new.acoustic_fingerprint == "1,2,3" and new.sync is None
        monkeypatch.setattr(
            "iOpenPod.app.sync_execution.prepare_podcast_sync",
            FixedPodcastPlan(PodcastSyncPlan(removals=(new.track_id,))),
        )
        removed = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert removed.status is SyncExecutionStatus.SUCCESS, removed.issues
        assert removed.helper is not None
        assert removed.helper.tracks == retained
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
@pytest.mark.parametrize("cover_available", (True, False))
def test_downloaded_podcast_persists_publisher_cover_in_device_artwork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cover_available: bool,
) -> None:
    device = build_device(tmp_path)
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))
    cover = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(cover, format="PNG")
    monkeypatch.setattr(
        feed_client,
        "urlopen",
        PodcastOpener(cover.getvalue() if cover_available else b"not an image").open,
    )
    addition = podcast_addition()
    addition = replace(
        addition,
        subscription=replace(
            addition.subscription, artwork_url="https://publisher.example/cover.png"
        ),
    )
    monkeypatch.setattr(
        "iOpenPod.app.sync_execution.prepare_podcast_sync",
        FixedPodcastPlan(PodcastSyncPlan(additions=(addition,))),
    )
    try:
        result = SyncExecutor(device.coordinator).execute(
            podcast_request(device.active), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        reloaded = device.coordinator.select_device(device.active.candidate.id)
        podcast = next(
            track
            for track in reloaded.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert (device.root / podcast.metadata.location).is_file()
        if not cover_available:
            assert podcast.artwork_id == 0
            assert any(
                issue.code == "sync.podcast_artwork_skipped" for issue in result.issues
            )
            return
        assert podcast.artwork_id > 0, "Downloaded Podcast lost its publisher artwork"
        decoded = device.coordinator.load_artwork(
            ArtworkRequest(podcast.artwork_id, 128)
        )
        assert decoded is not None, (
            "Saved ArtworkDB must reference readable iTHMB pixels"
        )
        center = ((decoded.height // 2) * decoded.width + decoded.width // 2) * 3
        red, green, blue = decoded.rgb888[center : center + 3]
        assert red >= 240 and green <= 12 and blue <= 12
        assert (
            device.root / "iPod_Control/Artwork/ArtworkDB"
        ).read_bytes() != device.original["iPod_Control/Artwork/ArtworkDB"]
    finally:
        device.coordinator.close()


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        pytest.fail("Repairing a retained Podcast cover must not prepare media")


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for initial Podcast preparation",
)
def test_podcast_sync_repairs_retained_cover_without_replacing_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    seed = podcast_addition()
    episode = replace(
        seed.episode,
        episode_id=episode_identity(
            enclosure_url=seed.episode.enclosure_url,
            guid=seed.episode.guid,
            title=seed.episode.title,
            published_at=seed.episode.published_at,
        ),
    )
    show = replace(
        seed.subscription,
        subscription_id=subscription_identity(
            seed.subscription.feed_url,
            seed.subscription.title,
            seed.subscription.author,
        ),
        episodes=(episode,),
    )

    def fetch(_self: FeedparserPodcastClient, feed_url: str) -> PodcastSubscription:
        assert feed_url == show.feed_url
        return show

    monkeypatch.setattr(FeedparserPodcastClient, "fetch", fetch)
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))

    def sync(*, repair_only: bool = False) -> SyncExecutionResult:
        state = device.coordinator.load_podcast_state(device.active)
        return SyncExecutor(
            device.coordinator,
            transcoder=_NoMediaPreparation() if repair_only else None,
        ).execute(
            replace(
                podcast_request(device.active),
                podcasts=PodcastSyncRequest(state.snapshot),
            ),
            lambda _: None,
            Event(),
        )

    try:
        loaded = device.coordinator.load_podcast_state(device.active)
        device.coordinator.save_podcast_state(
            device.active,
            replace(loaded, snapshot=replace(loaded.snapshot, subscriptions=(show,))),
        )
        added = sync()
        assert added.status is SyncExecutionStatus.SUCCESS, added.issues
        podcast = next(
            track
            for track in device.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        )
        assert podcast.artwork_id == 0
        media_path = device.root / podcast.metadata.location
        original_media = media_path.read_bytes()
        cover = io.BytesIO()
        Image.new("RGB", (64, 64), "blue").save(cover, format="PNG")
        monkeypatch.setattr(
            feed_client, "urlopen", PodcastOpener(cover.getvalue()).open
        )
        show = replace(show, artwork_url="https://publisher.example/cover.png")

        repaired = sync(repair_only=True)

        assert repaired.status is SyncExecutionStatus.SUCCESS, repaired.issues
        assert [item.action for item in repaired.completed] == [SyncPlanAction.UPDATE]
        assert repaired.completed[0].ipod_id == podcast.track_id
        reloaded = device.coordinator.select_device(device.active.candidate.id)
        retained = next(
            track
            for track in reloaded.library.tracks
            if track.track_id == podcast.track_id
        )
        assert retained.metadata.location == podcast.metadata.location
        assert media_path.read_bytes() == original_media
        assert retained.artwork_id > 0
        decoded = device.coordinator.load_artwork(
            ArtworkRequest(retained.artwork_id, 128)
        )
        assert decoded is not None
        center = ((decoded.height // 2) * decoded.width + decoded.width // 2) * 3
        red, green, blue = decoded.rgb888[center : center + 3]
        assert blue >= 240 and red <= 12 and green <= 12

        unchanged = sync(repair_only=True)
        assert unchanged.status is SyncExecutionStatus.SUCCESS, unchanged.issues
        assert not unchanged.completed
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
def test_saved_policy_sync_is_idempotent_and_retains_history_after_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    seed = podcast_addition()
    episode = replace(
        seed.episode,
        episode_id=episode_identity(
            enclosure_url=seed.episode.enclosure_url,
            guid=seed.episode.guid,
            title=seed.episode.title,
            published_at=seed.episode.published_at,
        ),
    )
    show = replace(
        seed.subscription,
        subscription_id=subscription_identity(
            seed.subscription.feed_url,
            seed.subscription.title,
            seed.subscription.author,
        ),
        episodes=(episode,),
    )
    fetches: list[str] = []

    def fetch(_self: FeedparserPodcastClient, feed_url: str) -> PodcastSubscription:
        fetches.append(feed_url)
        return show

    monkeypatch.setattr(FeedparserPodcastClient, "fetch", fetch)
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))
    try:
        loaded = device.coordinator.load_podcast_state(device.active)
        device.coordinator.save_podcast_state(
            device.active,
            replace(loaded, snapshot=replace(loaded.snapshot, subscriptions=(show,))),
        )

        def sync() -> SyncExecutionResult:
            state = device.coordinator.load_podcast_state(device.active)
            request = replace(
                podcast_request(device.active),
                podcasts=PodcastSyncRequest(state.snapshot),
            )
            return SyncExecutor(device.coordinator).execute(
                request, lambda _: None, Event()
            )

        first = sync()
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert len(first.completed) == 1
        second = sync()
        assert second.status is SyncExecutionStatus.SUCCESS, second.issues
        assert second.completed == ()
        assert second.active is not None
        podcasts = [
            track
            for track in second.active.library.tracks
            if track.media_kind is MediaKind.PODCAST
        ]
        assert len(podcasts) == 1
        path = device.root / podcasts[0].metadata.location
        loaded = device.coordinator.load_podcast_state(device.active)
        device.coordinator.save_podcast_state(
            device.active,
            replace(
                loaded,
                snapshot=mark_episode_selection_listened(
                    loaded.snapshot, ((show.subscription_id, episode.episode_id),), True
                ),
            ),
        )
        third = sync()
        assert third.status is SyncExecutionStatus.SUCCESS, third.issues
        assert len(third.completed) == 1 and not path.exists()
        loaded = device.coordinator.load_podcast_state(device.active)
        assert loaded.snapshot.history[0].listened
        assert loaded.snapshot.history[0].episode_id == episode.episode_id
        fourth = sync()
        assert fourth.status is SyncExecutionStatus.SUCCESS, fourth.issues
        assert fourth.completed == ()
        assert len(fetches) == 4
    finally:
        device.coordinator.close()


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual Podcast preparation",
)
@pytest.mark.parametrize("fill_mode", tuple(PodcastFillMode))
def test_age_clears_commit_with_library_and_do_not_redownload_after_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fill_mode: PodcastFillMode,
) -> None:
    device = build_device(tmp_path)
    seed = podcast_addition()
    episodes = tuple(
        replace(
            seed.episode,
            episode_id=episode_identity(
                enclosure_url=f"https://publisher.example/{number}.m4a",
                guid=f"guid-{number}",
                title=f"Episode {number}",
                published_at=1_700_000_000 + number,
            ),
            guid=f"guid-{number}",
            title=f"Episode {number}",
            enclosure_url=f"https://publisher.example/{number}.m4a",
            published_at=1_700_000_000 + number,
            episode_number=number,
        )
        for number in (1, 2)
    )
    show = replace(
        seed.subscription,
        subscription_id=subscription_identity(
            seed.subscription.feed_url,
            seed.subscription.title,
            seed.subscription.author,
        ),
        episodes=episodes,
        sync_settings=PodcastSyncSettings(
            episode_slots=1,
            fill_mode=fill_mode,
            clear_when_listened=False,
            clear_older_than=PodcastClearAge.IMMEDIATE,
        ),
    )

    def fetch(_self: FeedparserPodcastClient, feed_url: str) -> PodcastSubscription:
        assert feed_url == show.feed_url
        return show

    monkeypatch.setattr(FeedparserPodcastClient, "fetch", fetch)
    data = base64.decodebytes((FIXTURES / "tone.m4a.b64").read_bytes())
    monkeypatch.setattr(media, "build_opener", PodcastOpenerFactory(data))

    def sync(
        *,
        cancel_before_publication: bool = False,
        fail_after_history_publication: bool = False,
    ) -> SyncExecutionResult:
        state = device.coordinator.load_podcast_state(device.active)
        cancellation = Event()

        def progress(event: WriteProgress) -> None:
            if cancel_before_publication and event.phase == "save.storage.prepared":
                cancellation.set()
            if (
                fail_after_history_publication
                and event.phase == "save.storage.publishing"
                and event.current_item == str(HISTORY_PATH)
            ):
                records = decode_history((device.root / str(HISTORY_PATH)).read_bytes())
                assert any(record.automatically_cleared for record in records)
                raise StorageOperationError(
                    "Simulated interruption after history write"
                )

        return SyncExecutor(device.coordinator).execute(
            replace(
                podcast_request(device.active),
                podcasts=PodcastSyncRequest(state.snapshot),
            ),
            progress,
            cancellation,
        )

    try:
        loaded = device.coordinator.load_podcast_state(device.active)
        device.coordinator.save_podcast_state(
            device.active,
            replace(loaded, snapshot=replace(loaded.snapshot, subscriptions=(show,))),
        )
        first = sync()
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        old = next(
            t for t in device.active.library.tracks if t.media_kind is MediaKind.PODCAST
        )
        assert old.episode_number == (1 if fill_mode is PodcastFillMode.NEXT else 2)
        old_path = device.root / old.metadata.location
        before = device.active.database_fingerprint

        cancelled = sync(cancel_before_publication=True)
        assert cancelled.status is SyncExecutionStatus.CANCELLED, cancelled.issues
        assert old_path.exists()
        assert device.active.database_fingerprint == before
        state = device.coordinator.load_podcast_state(device.active)
        assert not any(
            record.automatically_cleared for record in state.snapshot.history
        )

        interrupted = sync(fail_after_history_publication=True)
        assert interrupted.status is SyncExecutionStatus.FAILED, interrupted.issues
        assert any(issue.code == "sync.restored" for issue in interrupted.issues)
        assert old_path.exists()
        assert device.active.database_fingerprint == before
        state = device.coordinator.load_podcast_state(device.active)
        assert not any(
            record.automatically_cleared for record in state.snapshot.history
        )

        # Restored bytes have new filesystem identities; reload the restored
        # Library before issuing another reviewed Sync.
        device.coordinator.select_device(device.active.candidate.id)
        cleared = sync()
        assert cleared.status is SyncExecutionStatus.SUCCESS, cleared.issues
        assert not old_path.exists()
        state = device.coordinator.load_podcast_state(device.active)
        record = next(r for r in state.snapshot.history if r.guid == old.episode)
        assert record.automatically_cleared and not record.listened
        assert record.published_at == old.metadata.release_date

        # Reload the Library and metadata, losing all runtime episode projections.
        device.coordinator.select_device(device.active.candidate.id)
        if fill_mode is PodcastFillMode.NEXT:
            assert [
                t.episode_number
                for t in device.active.library.tracks
                if t.media_kind is MediaKind.PODCAST
            ] == [2]
            final_clear = sync()
            assert final_clear.status is SyncExecutionStatus.SUCCESS, final_clear.issues
        repeat = sync()
        assert repeat.status is SyncExecutionStatus.SUCCESS, repeat.issues
        assert not repeat.completed
        assert not any(
            t.media_kind is MediaKind.PODCAST for t in device.active.library.tracks
        )
    finally:
        device.coordinator.close()
