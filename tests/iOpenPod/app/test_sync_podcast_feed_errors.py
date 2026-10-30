"""An invalid subscribed feed must not abort ordinary music publication."""

import base64
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_music_import import FIXTURES
from tests.iOpenPod.app.test_sync_execution import _request

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.podcasts import feed_client
from iOpenPod.app.podcasts.sync import PodcastSyncRequest
from iOpenPod.app.sync_execution import (
    SyncExecutionStatus,
    SyncExecutor,
    SyncOptions,
)
from iPodDB.library import LibrarySnapshot, MediaKind, MediaType, Track, TrackMetadata
from storage import HostPath
from storage.host_input import LocalHostFile


@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="FFmpeg and FFprobe required for actual MP3 preparation",
)
def test_music_sync_preserves_podcasts_when_a_feed_repeats_episode_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path, model="MA978")
    feed_url = "https://publisher.example/feed"
    payload = b"""<rss version="2.0"><channel><title>Show</title>
    <item><guid>first</guid><title>First</title>
    <enclosure url="https://publisher.example/shared.mp3" type="audio/mpeg" />
    </item>
    <item><guid>second</guid><title>Second</title>
    <enclosure url="https://publisher.example/shared.mp3" type="audio/mpeg" />
    </item></channel></rss>"""

    def request_bytes(url: str, **kwargs: object) -> tuple[bytes, str]:
        assert url == feed_url
        return payload, url

    monkeypatch.setattr(feed_client, "request_podcast_bytes", request_bytes)
    try:
        original = device.active.library.tracks[0]
        podcast = replace(
            original,
            title="Retained Episode",
            album="Show",
            episode="retained-guid",
            media_types=(MediaType.PODCAST,),
            play_count=1,
            metadata=replace(
                original.metadata,
                podcast=True,
                podcast_rss_url=feed_url,
                podcast_guid="retained-guid",
            ),
        )
        review = device.prepare(
            replace(
                device.active.library,
                tracks=(podcast, *device.active.library.tracks[1:]),
            )
        )
        saved = device.coordinator.save_library(
            review, device.active, lambda _: None, Event()
        )
        assert saved.active is not None, saved.issues
        state = device.coordinator.load_podcast_state(device.active)
        assert state.snapshot.writable and state.snapshot.history
        retained_path = device.root / podcast.metadata.location
        retained_bytes = retained_path.read_bytes()

        source = tmp_path / "Ordinary song.mp3"
        source.write_bytes(base64.decodebytes((FIXTURES / "tone.mp3.b64").read_bytes()))
        observed = LocalHostFile.observe(HostPath(source))
        host = HostMediaLibrary(
            LibrarySnapshot(
                tracks=(
                    Track(
                        100,
                        "Ordinary song",
                        "Artist",
                        "Album",
                        1000,
                        size_bytes=observed.size_bytes,
                        metadata=TrackMetadata(location=str(source)),
                    ),
                )
            ),
            (
                HostMediaSource(
                    observed.path,
                    HostMediaFileKind.AUDIO,
                    observed.size_bytes,
                    observed.modified_ns,
                    "100,2,3",
                ),
            ),
            (),
            HostMediaCacheStats(),
        )
        request = replace(
            _request(device, host),
            podcasts=PodcastSyncRequest(state.snapshot),
            options=SyncOptions(analyze_for_genius=False, scrobble=False),
        )

        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )

        assert result.status is SyncExecutionStatus.PARTIAL, result.issues
        assert result.active is not None
        added = next(
            t for t in result.active.library.tracks if t.title == "Ordinary song"
        )
        assert added.media_kind is MediaKind.MUSIC and not added.metadata.podcast
        assert (device.root / added.metadata.location).is_file()
        assert len(result.completed) == 1
        retained = next(
            t for t in result.active.library.tracks if t.track_id == podcast.track_id
        )
        assert retained.media_kind is MediaKind.PODCAST
        assert retained_path.read_bytes() == retained_bytes
        refreshed = device.coordinator.load_podcast_state(result.active)
        assert refreshed.snapshot.history == state.snapshot.history
        assert refreshed.snapshot.subscriptions[0].on_device_count == 1
        issue = next(i for i in result.issues if i.code == "podcast.refresh_failed")
        assert "Show" in issue.message
        assert feed_url in issue.detail
        assert "Episode IDs" in issue.detail
    finally:
        device.coordinator.close()
