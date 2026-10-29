"""Two-way play count sync through the verified Library save and Jellyfin API."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_jellyfin_client import FakeJellyfin, account, item

from iOpenPod.app.jellyfin.client import JellyfinClient
from iOpenPod.app.jellyfin.models import JellyfinAccount, JellyfinError
from iOpenPod.app.jellyfin.service import PlayCountService
from iOpenPod.app.jellyfin.state import PlayCountStore
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    LibrarySaveResult,
    WriteProgress,
)
from iOpenPod.app.models.device import ActiveIPod
from iPodDB.library import IssueSeverity, WriteIssue
from iPodDB.library.editing import TrackFieldEdit, edit_track_metadata
from storage import AtomicHostFile

FIRST, SECOND = "a" * 32, "b" * 32


class MemoryTokens:
    def __init__(self, value: JellyfinAccount | None) -> None:
        self.value = value

    def load(self) -> JellyfinAccount | None:
        return self.value

    def save(self, account: JellyfinAccount) -> None:
        self.value = account

    def remove(self) -> None:
        self.value = None


class FailingSave:
    """The real coordinator, except that publication reports a failure."""

    def __init__(self, device: Device) -> None:
        self._coordinator = device.coordinator

    def scrobble_context(self, expected: ActiveIPod) -> tuple[str, Callable[[], None]]:
        return self._coordinator.scrobble_context(expected)

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> LibraryReview:
        return self._coordinator.prepare_library(request, progress, cancelled)

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> LibrarySaveResult:
        return LibrarySaveResult(
            (WriteIssue("save.failed", "Disk full.", severity=IssueSeverity.ERROR),)
        )


@pytest.fixture
def device(tmp_path: Path) -> Iterator[Device]:
    device = build_device(tmp_path)
    yield device
    device.coordinator.close()


def server(first: int = 0, second: int = 0) -> FakeJellyfin:
    return FakeJellyfin(
        [item(FIRST, "Track 1", count=first), item(SECOND, "Track 2", count=second)]
    )


def service(
    device: Device,
    tmp_path: Path,
    jellyfin: FakeJellyfin,
    *,
    coordinator: FailingSave | None = None,
) -> PlayCountService:
    return PlayCountService(
        coordinator or device.coordinator,
        PlayCountStore(AtomicHostFile(tmp_path / "play-counts.json")),
        MemoryTokens(account()),
        client=JellyfinClient(jellyfin),
    )


def counts(active: ActiveIPod) -> dict[str, int]:
    return {track.title: track.play_count for track in active.library.tracks}


def play_on_ipod(device: Device, title: str, count: int) -> None:
    active = device.active
    tracks = tuple(
        edit_track_metadata(
            track,
            (
                TrackFieldEdit("play_count", count),
                TrackFieldEdit("metadata.played", True),
            ),
        )
        if track.title == title
        else track
        for track in active.library.tracks
    )
    review = device.prepare(replace(active.library, tracks=tracks))
    saved = device.coordinator.save_library(review, active, lambda _: None, Event())
    assert saved.active is not None, saved.issues


def test_first_sync_copies_jellyfin_plays_to_the_ipod(
    device: Device, tmp_path: Path
) -> None:
    jellyfin = server(first=4)
    result = service(device, tmp_path, jellyfin).run(
        device.active, Event(), lambda _: None
    )
    assert result.matched == 2 and result.ipod_updated == 1
    assert result.jellyfin_updated == 0 and not result.issues
    assert result.active is device.active
    assert counts(device.active) == {"Track 1": 4, "Track 2": 0}
    first = next(t for t in device.active.library.tracks if t.title == "Track 1")
    assert first.metadata.played
    assert first.metadata.unscrobbled_play_count == 0


def test_first_sync_copies_ipod_plays_to_jellyfin(
    device: Device, tmp_path: Path
) -> None:
    play_on_ipod(device, "Track 2", 6)
    jellyfin = server(second=2)
    result = service(device, tmp_path, jellyfin).run(
        device.active, Event(), lambda _: None
    )
    assert result.ipod_updated == 0 and result.jellyfin_updated == 1
    assert result.active is None
    assert jellyfin.count(SECOND) == 6


def test_later_syncs_add_plays_from_both_sides(device: Device, tmp_path: Path) -> None:
    jellyfin = server(first=4)
    sync = service(device, tmp_path, jellyfin)
    sync.run(device.active, Event(), lambda _: None)
    play_on_ipod(device, "Track 1", 6)
    jellyfin.items[FIRST]["UserData"] = {"PlayCount": 5}
    result = sync.run(device.active, Event(), lambda _: None)
    assert result.ipod_updated == 1 and result.jellyfin_updated == 1
    assert counts(device.active)["Track 1"] == 7
    assert jellyfin.count(FIRST) == 7
    again = sync.run(device.active, Event(), lambda _: None)
    assert again.ipod_updated == again.jellyfin_updated == 0


def test_unsent_jellyfin_counts_are_retried_without_double_counting(
    device: Device, tmp_path: Path
) -> None:
    play_on_ipod(device, "Track 1", 3)
    jellyfin = server(first=1)
    jellyfin.fail_updates = True
    sync = service(device, tmp_path, jellyfin)
    failed = sync.run(device.active, Event(), lambda _: None)
    assert failed.jellyfin_updated == 0
    assert any("sent next time" in issue for issue in failed.issues)
    jellyfin.fail_updates = False
    jellyfin.items[FIRST]["UserData"] = {"PlayCount": 2}
    retried = sync.run(device.active, Event(), lambda _: None)
    # 3 on the iPod, plus the one new Jellyfin play since it was last seen at 1.
    assert counts(device.active)["Track 1"] == 4
    assert jellyfin.count(FIRST) == 4
    assert retried.jellyfin_updated == 1


def test_a_failed_ipod_save_changes_nothing_and_merges_conservatively_next(
    device: Device, tmp_path: Path
) -> None:
    jellyfin = server(first=4)
    failing = service(device, tmp_path, jellyfin, coordinator=FailingSave(device))
    result = failing.run(device.active, Event(), lambda _: None)
    assert result.active is None and result.issues == ("Disk full.",)
    assert counts(device.active)["Track 1"] == 0
    assert len(jellyfin.requests) == 1
    retried = service(device, tmp_path, jellyfin).run(
        device.active, Event(), lambda _: None
    )
    assert retried.ipod_updated == 1
    assert counts(device.active)["Track 1"] == 4


def test_unmatched_and_duplicate_songs_are_reported_not_guessed(
    device: Device, tmp_path: Path
) -> None:
    jellyfin = FakeJellyfin(
        [
            item(FIRST, "Track 1", count=4),
            item(SECOND, "Track 1", count=9),
        ]
    )
    result = service(device, tmp_path, jellyfin).run(
        device.active, Event(), lambda _: None
    )
    assert result.matched == 0
    assert result.ambiguous == ("Track 1",) and result.unmatched == ("Track 2",)
    assert counts(device.active) == {"Track 1": 0, "Track 2": 0}


def test_cancelled_before_reading_changes_nothing(
    device: Device, tmp_path: Path
) -> None:
    jellyfin = server(first=4)
    cancelled = Event()
    cancelled.set()
    result = service(device, tmp_path, jellyfin).run(
        device.active, cancelled, lambda _: None
    )
    assert result.cancelled and result.active is None
    assert counts(device.active)["Track 1"] == 0
    assert not jellyfin.requests


def test_sync_requires_a_connected_account(device: Device, tmp_path: Path) -> None:
    sync = PlayCountService(
        device.coordinator,
        PlayCountStore(AtomicHostFile(tmp_path / "play-counts.json")),
        MemoryTokens(None),
        client=JellyfinClient(server()),
    )
    with pytest.raises(JellyfinError, match="Connect Jellyfin"):
        sync.run(device.active, Event(), lambda _: None)
