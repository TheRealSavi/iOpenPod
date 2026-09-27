import json
from dataclasses import replace
from pathlib import Path

import pytest

from iOpenPod.app.podcasts.models import ListeningRecord, PodcastIssueCode
from iOpenPod.app.podcasts.store import (
    HISTORY_PATH,
    SUBSCRIPTIONS_PATH,
    PodcastDeviceStore,
)
from iPodDB.library import MediaType, Track, TrackMetadata
from storage import AccessMode, FilesystemSession, Storage
from storage.testing import VirtualStoragePlatform


def _track() -> Track:
    return Track(
        19,
        "Episode",
        "Network",
        "Recovered Show",
        1_000,
        play_count=1,
        media_types=(MediaType.PODCAST,),
        metadata=TrackMetadata(
            podcast=True,
            podcast_rss_url="https://example.test/feed",
            podcast_enclosure_url="https://example.test/episode.mp3",
            last_played=1_700_000_000,
        ),
    )


def _session(tmp_path: Path) -> tuple[Path, FilesystemSession]:
    root = tmp_path / "ipod"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Test iPod")
    storage = Storage(platform)
    mounted = storage.discover().volumes[0]
    return root, storage.open_session(mounted, access=AccessMode.READ_WRITE)


def test_store_recovers_device_podcasts_and_keeps_history_after_removal(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    store = PodcastDeviceStore()
    with session:
        loaded = store.load(session, (_track(),), writable=True)
        assert loaded.requires_persistence is True
        saved = store.save(session, loaded)
        assert (root / Path(str(SUBSCRIPTIONS_PATH))).is_file()
        assert (root / Path(str(HISTORY_PATH))).is_file()
        subscriptions_document = json.loads(
            (root / Path(str(SUBSCRIPTIONS_PATH))).read_bytes()
        )
        assert "episodes" not in subscriptions_document["subscriptions"][0]

        reloaded = store.load(session, (), writable=True)

    assert saved.requires_persistence is False
    assert reloaded.snapshot.subscriptions[0].episodes == ()
    assert reloaded.snapshot.history[0].observed_play_count == 1


def test_store_never_overwrites_an_invalid_existing_document(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    subscriptions = root / Path(str(SUBSCRIPTIONS_PATH))
    subscriptions.parent.mkdir(parents=True)
    subscriptions.write_bytes(b"broken")
    store = PodcastDeviceStore()

    with session:
        loaded = store.load(session, (_track(),), writable=True)
        with pytest.raises(ValueError, match="not safely writable"):
            store.save(session, loaded)

    assert subscriptions.read_bytes() == b"broken"
    assert loaded.snapshot.writable is False
    assert loaded.snapshot.issues[0].code is PodcastIssueCode.SUBSCRIPTIONS_UNREADABLE


def test_oversized_history_cannot_be_saved_or_join_media_removal(
    tmp_path: Path,
) -> None:
    root, session = _session(tmp_path)
    store = PodcastDeviceStore()
    with session:
        loaded = store.load(session, (_track(),), writable=True)
        oversized = replace(
            loaded,
            snapshot=replace(
                loaded.snapshot,
                history=(
                    ListeningRecord("show", "episode", title="x" * (8 * 1024 * 1024)),
                ),
            ),
        )
        with pytest.raises(ValueError, match="Listening History exceeds"):
            store.history_transaction(oversized)
        with pytest.raises(ValueError, match="Listening History exceeds"):
            store.save(session, oversized)
    assert not (root / str(HISTORY_PATH)).exists()
    assert not (root / str(SUBSCRIPTIONS_PATH)).exists()
