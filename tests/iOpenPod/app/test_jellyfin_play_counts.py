"""Two-way play count sync through the verified Library save and Jellyfin API."""

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_jellyfin_client import FakeJellyfin, account, item

from iOpenPod.app.jellyfin.client import JellyfinClient
from iOpenPod.app.jellyfin.device_state import PLAY_COUNTS_PATH
from iOpenPod.app.jellyfin.models import JellyfinAccount, JellyfinError
from iOpenPod.app.jellyfin.service import PlayCountService
from iOpenPod.app.jellyfin.state import (
    PairState,
    PlayCountState,
    PlayCountStore,
    pair_key,
)
from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    LibrarySaveResult,
    WriteProgress,
)
from iOpenPod.app.models.device import ActiveIPod
from iPodDB.library import IssueSeverity, WriteIssue
from iPodDB.library.editing import TrackFieldEdit, edit_track_metadata
from storage import AtomicHostFile, DevicePath, FileFingerprint, TransactionWrite

FIRST, SECOND = "a" * 32, "b" * 32
FIRST_ID = 101


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
        *,
        application_writes: tuple[TransactionWrite, ...] = (),
    ) -> LibraryReview:
        return self._coordinator.prepare_library(
            request, progress, cancelled, application_writes=application_writes
        )

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

    def load_application_document(
        self, expected: ActiveIPod, path: DevicePath, max_bytes: int
    ) -> tuple[bytes | None, FileFingerprint | None]:
        return self._coordinator.load_application_document(expected, path, max_bytes)

    def save_application_document(
        self,
        expected: ActiveIPod,
        path: DevicePath,
        data: bytes,
        before: FileFingerprint | None,
    ) -> FileFingerprint:
        return self._coordinator.save_application_document(expected, path, data, before)


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
    jellyfin: FakeJellyfin,
    *,
    coordinator: FailingSave | None = None,
    legacy: PlayCountStore | None = None,
) -> PlayCountService:
    return PlayCountService(
        coordinator or device.coordinator,
        MemoryTokens(account()),
        client=JellyfinClient(jellyfin),
        legacy=legacy,
    )


def sync(sync_service: PlayCountService, device: Device) -> object:
    return sync_service.run(device.active, Event(), lambda _: None)


def counts(active: ActiveIPod) -> dict[str, int]:
    return {track.title: track.play_count for track in active.library.tracks}


def memory(device: Device) -> dict[str, dict[str, int | str]]:
    path = device.root / "/".join(PLAY_COUNTS_PATH.parts)
    document = json.loads(path.read_bytes())
    return cast(
        "dict[str, dict[str, int | str]]", document["accounts"][account().identity]
    )


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


def test_first_sync_copies_jellyfin_plays_and_the_memory_to_the_ipod(
    device: Device,
) -> None:
    result = service(device, server(first=4)).run(
        device.active, Event(), lambda _: None
    )
    assert result.matched == 2 and result.ipod_updated == 1
    assert result.jellyfin_updated == 0 and not result.issues
    assert result.active is device.active
    assert counts(device.active) == {"Track 1": 4, "Track 2": 0}
    first = next(t for t in device.active.library.tracks if t.title == "Track 1")
    assert first.metadata.played
    assert first.metadata.unscrobbled_play_count == 0
    # Saved in the same transaction as the counts, keyed without a device ID.
    assert memory(device)[str(FIRST_ID)] == {
        "item": FIRST,
        "agreed": 4,
        "ipod": 4,
        "jellyfin": 4,
    }


def test_first_sync_copies_ipod_plays_to_jellyfin(device: Device) -> None:
    play_on_ipod(device, "Track 2", 6)
    jellyfin = server(second=2)
    result = service(device, jellyfin).run(device.active, Event(), lambda _: None)
    assert result.ipod_updated == 0 and result.jellyfin_updated == 1
    assert result.active is None
    assert jellyfin.count(SECOND) == 6
    assert memory(device)["102"]["agreed"] == 6


def test_later_syncs_add_plays_from_both_sides(device: Device) -> None:
    jellyfin = server(first=4)
    first = service(device, jellyfin)
    sync(first, device)
    play_on_ipod(device, "Track 1", 6)
    jellyfin.items[FIRST]["UserData"] = {"PlayCount": 5}
    result = first.run(device.active, Event(), lambda _: None)
    assert result.ipod_updated == 1 and result.jellyfin_updated == 1
    assert counts(device.active)["Track 1"] == 7
    assert jellyfin.count(FIRST) == 7
    again = first.run(device.active, Event(), lambda _: None)
    assert again.ipod_updated == again.jellyfin_updated == 0


def test_another_computer_continues_from_the_memory_on_the_ipod(
    device: Device,
) -> None:
    jellyfin = server(first=5)
    sync(service(device, jellyfin), device)
    play_on_ipod(device, "Track 1", 7)
    jellyfin.items[FIRST]["UserData"] = {"PlayCount": 6}
    sync(service(device, jellyfin), device)
    assert counts(device.active)["Track 1"] == jellyfin.count(FIRST) == 8
    # A second Host has no memory of its own; it must not add those plays again.
    other_computer = service(device, jellyfin)
    result = other_computer.run(device.active, Event(), lambda _: None)
    assert result.ipod_updated == result.jellyfin_updated == 0
    assert counts(device.active)["Track 1"] == jellyfin.count(FIRST) == 8
    play_on_ipod(device, "Track 1", 9)
    other_computer.run(device.active, Event(), lambda _: None)
    assert counts(device.active)["Track 1"] == jellyfin.count(FIRST) == 9


def test_unsent_jellyfin_counts_are_retried_without_double_counting(
    device: Device,
) -> None:
    play_on_ipod(device, "Track 1", 3)
    jellyfin = server(first=1)
    jellyfin.fail_updates = True
    sync_service = service(device, jellyfin)
    failed = sync_service.run(device.active, Event(), lambda _: None)
    assert failed.jellyfin_updated == 0
    assert any("sent next time" in issue for issue in failed.issues)
    assert memory(device)[str(FIRST_ID)]["jellyfin"] == 1
    jellyfin.fail_updates = False
    jellyfin.items[FIRST]["UserData"] = {"PlayCount": 2}
    retried = sync_service.run(device.active, Event(), lambda _: None)
    # 3 on the iPod, plus the one new Jellyfin play since it was last seen at 1.
    assert counts(device.active)["Track 1"] == 4
    assert jellyfin.count(FIRST) == 4
    assert retried.jellyfin_updated == 1


def test_unsent_counts_after_an_ipod_save_are_recorded_on_the_new_revision(
    device: Device,
) -> None:
    jellyfin = server(first=4)
    sync(service(device, jellyfin), device)
    play_on_ipod(device, "Track 1", 6)
    jellyfin.items[FIRST]["UserData"] = {"PlayCount": 5}
    jellyfin.fail_updates = True
    result = service(device, jellyfin).run(device.active, Event(), lambda _: None)
    assert result.ipod_updated == 1 and result.jellyfin_updated == 0
    assert counts(device.active)["Track 1"] == 7
    assert memory(device)[str(FIRST_ID)] == {
        "item": FIRST,
        "agreed": 7,
        "ipod": 7,
        "jellyfin": 5,
    }


def test_a_failed_ipod_save_writes_neither_counts_nor_memory(device: Device) -> None:
    jellyfin = server(first=4)
    failing = service(device, jellyfin, coordinator=FailingSave(device))
    result = failing.run(device.active, Event(), lambda _: None)
    assert result.active is None and result.issues == ("Disk full.",)
    assert counts(device.active)["Track 1"] == 0
    assert not (device.root / "/".join(PLAY_COUNTS_PATH.parts)).exists()
    assert len(jellyfin.requests) == 1
    retried = service(device, jellyfin).run(device.active, Event(), lambda _: None)
    assert retried.ipod_updated == 1
    assert counts(device.active)["Track 1"] == 4


def test_earlier_host_memory_seeds_the_ipod_memory(
    device: Device, tmp_path: Path
) -> None:
    play_on_ipod(device, "Track 1", 12)
    jellyfin = server(first=11)
    volume, _ = device.coordinator.scrobble_context(device.active)
    legacy = PlayCountStore(AtomicHostFile(tmp_path / "legacy.json"))
    legacy.save(
        PlayCountState(
            {
                pair_key(account().identity, volume, FIRST_ID): PairState(
                    FIRST, 10, 10, 10
                )
            }
        )
    )
    sync(service(device, jellyfin, legacy=legacy), device)
    # 10 agreed earlier, plus 2 new iPod plays and 1 new Jellyfin play.
    assert counts(device.active)["Track 1"] == jellyfin.count(FIRST) == 13
    assert memory(device)[str(FIRST_ID)]["agreed"] == 13


def test_unreadable_ipod_memory_stops_before_any_change(device: Device) -> None:
    path = device.root / "/".join(PLAY_COUNTS_PATH.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not json")
    jellyfin = server(first=4)
    with pytest.raises(JellyfinError, match="unreadable"):
        sync(service(device, jellyfin), device)
    assert path.read_bytes() == b"not json"
    assert counts(device.active)["Track 1"] == 0
    assert not jellyfin.requests


def test_unmatched_and_duplicate_songs_are_reported_not_guessed(
    device: Device,
) -> None:
    jellyfin = FakeJellyfin(
        [
            item(FIRST, "Track 1", count=4),
            item(SECOND, "Track 1", count=9),
        ]
    )
    result = service(device, jellyfin).run(device.active, Event(), lambda _: None)
    assert result.matched == 0
    assert result.ambiguous == ("Track 1",) and result.unmatched == ("Track 2",)
    assert counts(device.active) == {"Track 1": 0, "Track 2": 0}
    assert not (device.root / "/".join(PLAY_COUNTS_PATH.parts)).exists()


def test_cancelled_before_reading_changes_nothing(device: Device) -> None:
    jellyfin = server(first=4)
    cancelled = Event()
    cancelled.set()
    result = service(device, jellyfin).run(device.active, cancelled, lambda _: None)
    assert result.cancelled and result.active is None
    assert counts(device.active)["Track 1"] == 0
    assert not jellyfin.requests


def test_sync_requires_a_connected_account(device: Device) -> None:
    sync_service = PlayCountService(
        device.coordinator,
        MemoryTokens(None),
        client=JellyfinClient(server()),
    )
    with pytest.raises(JellyfinError, match="Connect Jellyfin"):
        sync(sync_service, device)
