"""Durable capture, account isolation, retries, cancellation, and Sync ordering."""

import json
from collections.abc import Callable, Iterator
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_scrobbling_clients import TransportStub, acknowledgement

from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.scrobbling.clients import LastFmClient
from iOpenPod.app.scrobbling.models import (
    Account,
    Credentials,
    Listen,
    RejectedListen,
    ScrobbleError,
    Service,
    Submission,
)
from iOpenPod.app.scrobbling.queue import QueueState, ScrobbleQueue, capture
from iOpenPod.app.scrobbling.service import ScrobbleService
from iPodDB.library import (
    IPodTrackDetails,
    LibrarySnapshot,
    MediaType,
    Track,
    TrackMetadata,
)
from storage import AtomicHostFile, StorageError

NOW = 1_790_000_000
ACCOUNTS = (Account(Service.LASTFM, "alice"), Account(Service.LISTENBRAINZ, "alice"))


def track(*, count: int = 2, last_played: int = NOW) -> Track:
    return Track(
        1,
        "Song",
        "Artist",
        "Album",
        180_000,
        play_count=10 + count,
        metadata=TrackMetadata(unscrobbled_play_count=count, last_played=last_played),
        ipod=IPodTrackDetails(db_track_id=1234),
    )


class MemoryCredentials:
    def __init__(self) -> None:
        self.values = {
            service: Credentials("alice", "token", "key", "secret")
            for service in Service
        }

    def load(self, service: Service) -> Credentials | None:
        return self.values.get(service)

    def save(self, service: Service, credentials: Credentials) -> None:
        self.values[service] = credentials

    def remove(self, service: Service) -> None:
        self.values.pop(service, None)


class SourceStub:
    def __init__(self) -> None:
        self.disconnected = False

    def scrobble_context(self, expected: ActiveIPod) -> tuple[str, Callable[[], None]]:
        return "volume", self.check

    def check(self) -> None:
        if self.disconnected:
            raise StorageError("disconnected")


class ClientStub:
    batch_size = 50

    def __init__(self) -> None:
        self.calls: list[tuple[Listen, ...]] = []
        self.error = False
        self.partial = False
        self.after_submit: Callable[[], None] = lambda: None

    def submit(
        self, entries: tuple[Listen, ...], credentials: Credentials
    ) -> Submission:
        self.calls.append(entries)
        if self.error:
            raise ScrobbleError("offline")
        self.after_submit()
        return Submission(
            tuple(not self.partial or index == 0 for index in range(len(entries))),
            tuple(RejectedListen(entry, 3) for entry in entries[1:])
            if self.partial
            else (),
        )


@pytest.fixture
def device(tmp_path: Path) -> Iterator[Device]:
    device = build_device(tmp_path)
    yield device
    device.coordinator.close()


def test_capture_stable_ordinals_timestamps_and_account_device_isolation() -> None:
    state = QueueState()
    library = LibrarySnapshot((track(),))
    assert capture(state, "one", library, ACCOUNTS, NOW) == 0
    assert len(state.pending) == 4
    assert [entry.listen.timestamp for entry in state.pending] == [
        NOW - 360,
        NOW - 360,
        NOW - 180,
        NOW - 180,
    ]
    capture(state, "one", library, ACCOUNTS, NOW)
    assert len(state.pending) == 4
    # Newly observed plays do not change timestamps of older pending entries.
    identities = {entry.identity: entry.listen for entry in state.pending}
    capture(
        state,
        "one",
        LibrarySnapshot((track(count=3, last_played=NOW + 500),)),
        ACCOUNTS,
        NOW + 500,
    )
    assert len(state.pending) == 6
    assert all(
        identities[e.identity] == e.listen
        for e in state.pending
        if e.identity in identities
    )
    capture(state, "two", library, ACCOUNTS[:1], NOW)
    capture(state, "one", library, (Account(Service.LASTFM, "bob"),), NOW)
    assert len(state.pending) == 10


@pytest.mark.parametrize(
    "song",
    [
        track(last_played=0),
        track(last_played=NOW + 1),
        replace(track(), length_ms=30_000),
        replace(track(), artist="  "),
        replace(track(), title=""),
        replace(track(), ipod=None),
        replace(track(), media_types=(MediaType.PODCAST,)),
        replace(track(), media_types=(MediaType.AUDIOBOOK,)),
    ],
)
def test_unsupported_or_uncertain_plays_are_not_invented(song: Track) -> None:
    state = QueueState()
    assert capture(state, "one", LibrarySnapshot((song,)), ACCOUNTS, NOW) == 1
    assert not state.pending and not state.cursors


def test_two_services_partial_success_survives_restart_and_track_removal(
    device: Device, tmp_path: Path
) -> None:
    active = replace(device.active, library=LibrarySnapshot((track(),)))
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    source = SourceStub()
    lastfm, brainz = ClientStub(), ClientStub()
    lastfm.partial = True
    brainz.error = True
    clients = {Service.LASTFM: lastfm, Service.LISTENBRAINZ: brainz}
    service = ScrobbleService(
        source,
        queue,
        MemoryCredentials(),
        clients=clients.__getitem__,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS, Event(), lambda _: None)
    assert (result.accepted, result.pending) == (1, 3)
    assert len(result.issues) == 2
    assert "token" not in queue.host_file.path.read_text()
    # Fresh service and queue instances model restarting the app after Sync removal.
    lastfm.partial = brainz.error = False
    service = ScrobbleService(
        source,
        ScrobbleQueue(queue.host_file),
        MemoryCredentials(),
        clients=clients.__getitem__,
        clock=lambda: NOW,
    )
    removed = replace(active, library=LibrarySnapshot())
    result = service.run(removed, ACCOUNTS, Event(), lambda _: None)
    assert (result.accepted, result.pending) == (3, 0)
    assert [len(call) for call in lastfm.calls] == [2, 1]
    # Reloading the same evidence does not submit again.
    assert service.run(active, ACCOUNTS, Event(), lambda _: None).accepted == 0
    assert len(lastfm.calls) == len(brainz.calls) == 2


def test_rejections_identify_metadata_and_combine_repeated_plays_across_batches(
    device: Device, tmp_path: Path
) -> None:
    song = replace(track(count=3), artist="Unknown Artist")
    active = replace(device.active, library=LibrarySnapshot((song,)))
    rejections = [
        acknowledgement(
            Listen(song.artist, song.title, song.album, NOW - index * 180, 180),
            1,
            "Artist name failed filter: Unknown Artist",
        )
        for index in (3, 2, 1)
    ]
    lastfm = LastFmClient(
        TransportStub(
            {"scrobbles": {"scrobble": rejections[:2]}},
            {"scrobbles": {"scrobble": rejections[2]}},
        )
    )
    lastfm.batch_size = 2
    brainz = ClientStub()
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda service: lastfm if service is Service.LASTFM else brainz,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS, Event(), lambda _: None)
    assert (result.accepted, result.pending) == (3, 3)
    assert len(result.issues) == 1
    report = result.issues[0]
    assert "Last.fm (alice): 3 listens rejected" in report
    assert "Listen ignored (code 1): 3 listens" in report
    assert report.count('Artist: "Unknown Artist"; Title: "Song"; Album: "Album"') == 1
    assert "3 listens; estimated playback start (UTC):" in report
    assert "2026-09-21 14:04:20 to 2026-09-21 14:10:20" in report
    assert "Service message: Artist name failed filter: Unknown Artist" in report
    assert "does not establish that the artist metadata is wrong" in report
    assert all(entry.account == ACCOUNTS[0].identity for entry in queue.load().pending)


def test_reordered_lastfm_reply_only_removes_the_acknowledged_listen_from_disk(
    device: Device, tmp_path: Path
) -> None:
    active = replace(device.active, library=LibrarySnapshot((track(count=12),)))
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture(state, "volume", active.library, ACCOUNTS[:1], NOW)
    original = tuple(state.pending)
    queue.save(state)
    replies = [
        acknowledgement(original[index].listen, 0 if index == 11 else 1)
        for index in sorted(range(12), key=str)
    ]
    client = LastFmClient(TransportStub({"scrobbles": {"scrobble": replies}}))
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS[:1], Event(), lambda _: None)
    assert (result.accepted, result.pending) == (1, 11)
    assert queue.load().pending == list(original[:-1])


@pytest.mark.parametrize("old_dates", [False, True])
def test_cancel_after_reply_retains_receipts_before_stopping(
    device: Device, tmp_path: Path, old_dates: bool
) -> None:
    song = track(count=51, last_played=NOW - 30 * 86400 if old_dates else NOW)
    active = replace(device.active, library=LibrarySnapshot((song,)))
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    cancelled = Event()
    client = ClientStub()
    client.after_submit = cancelled.set
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS[:1], cancelled, lambda _: None)
    assert result.cancelled and result.accepted == 50 and result.pending == 1
    assert len(queue.load().pending) == 1
    if old_dates:
        assert result.adjusted == 51
        assert queue.load().pending[0].submission.timestamp == NOW
    assert len(client.calls) == 1


def test_queue_failure_prevents_any_network_and_preserves_corrupt_file(
    device: Device, tmp_path: Path
) -> None:
    path = tmp_path / "queue.json"
    path.write_text("broken")
    queue = ScrobbleQueue(AtomicHostFile(path))
    client = ClientStub()
    service = ScrobbleService(
        SourceStub(), queue, MemoryCredentials(), clients=lambda _: client
    )
    with pytest.raises(ScrobbleError, match="unreadable"):
        service.run(device.active, ACCOUNTS, Event(), lambda _: None)
    assert not client.calls
    assert path.read_text() == "broken"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artist", None),
        ("title", []),
        ("album", 123),
        ("album_artist", {}),
        ("timestamp", str(NOW)),
        ("duration", True),
        ("track_number", 1.5),
    ],
)
def test_saved_queue_rejects_invalid_listen_field_types_without_rewriting(
    tmp_path: Path, field: str, value: object
) -> None:
    fields: dict[str, object] = asdict(Listen("Artist", "Song", "Album", NOW, 180))
    fields[field] = value
    raw = json.dumps(
        {
            "version": 1,
            "cursors": {},
            "pending": [
                {
                    "identity": "entry",
                    "device": "volume",
                    "account": "alice",
                    "listen": fields,
                }
            ],
        }
    )
    path = tmp_path / "queue.json"
    path.write_text(raw)
    with pytest.raises(ScrobbleError, match="unreadable"):
        ScrobbleQueue(AtomicHostFile(path)).load()
    assert path.read_text() == raw


@pytest.mark.parametrize("cursor", [True, -1, 1.5, "1", None])
def test_saved_queue_rejects_invalid_capture_cursors(
    tmp_path: Path, cursor: object
) -> None:
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps({"version": 1, "cursors": {"entry": cursor}, "pending": []})
    )
    with pytest.raises(ScrobbleError, match="unreadable"):
        ScrobbleQueue(AtomicHostFile(path)).load()


def test_receipt_write_failure_stops_before_contacting_second_service(
    device: Device,
    tmp_path: Path,
) -> None:
    class FailingQueue(ScrobbleQueue):
        writes = 0

        def save(self, state: QueueState) -> None:
            self.writes += 1
            if self.writes == 2:
                raise OSError("disk full")
            super().save(state)

    queue = FailingQueue(AtomicHostFile(tmp_path / "queue.json"))
    client = ClientStub()
    active = replace(device.active, library=LibrarySnapshot((track(),)))
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    with pytest.raises(OSError, match="disk full"):
        service.run(active, ACCOUNTS, Event(), lambda _: None)
    assert len(client.calls) == 1
    # The last durable state remains intact; uncertain remote receipts are retriable.
    assert len(queue.load().pending) == 4


def test_fractional_duration_over_thirty_seconds_qualifies(tmp_path: Path) -> None:
    state = QueueState()
    capture(
        state,
        "volume",
        LibrarySnapshot((replace(track(), length_ms=30_500),)),
        ACCOUNTS[:1],
        NOW,
    )
    assert len(state.pending) == 2
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    queue.save(state)
    assert queue.load().pending == state.pending


def test_disconnect_stops_before_next_request_but_keeps_first_receipt(
    device: Device, tmp_path: Path
) -> None:
    active = replace(device.active, library=LibrarySnapshot((track(count=51),)))
    source, client = SourceStub(), ClientStub()
    client.after_submit = lambda: setattr(source, "disconnected", True)
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    service = ScrobbleService(
        source, queue, MemoryCredentials(), clients=lambda _: client, clock=lambda: NOW
    )
    with pytest.raises(StorageError, match="disconnected"):
        service.run(active, ACCOUNTS[:1], Event(), lambda _: None)
    assert len(client.calls) == 1 and len(queue.load().pending) == 1


def test_real_device_context_rejects_stale_or_disconnected_session(
    device: Device,
) -> None:
    identity, check = device.coordinator.scrobble_context(device.active)
    assert identity == device.coordinator.active_volume_id.value  # type: ignore[union-attr]
    with pytest.raises(Exception, match="changed"):
        device.coordinator.scrobble_context(replace(device.active))
    device.platform.disconnect(device.root)
    with pytest.raises(StorageError):
        check()


def test_old_lastfm_dates_are_persisted_before_network_and_reused_after_restart(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((track(last_played=NOW - 30 * 86400),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    lastfm, brainz = ClientStub(), ClientStub()
    lastfm.partial = True
    clients = {Service.LASTFM: lastfm, Service.LISTENBRAINZ: brainz}

    def check_saved_dates() -> None:
        pending = queue.load().pending
        assert sorted(
            item.submission.timestamp
            for item in pending
            if item.account == ACCOUNTS[0].identity
        ) == [NOW - 1, NOW]
        assert all(item.listen.timestamp < NOW - 14 * 86400 for item in pending)

    lastfm.after_submit = check_saved_dates
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=clients.__getitem__,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS, Event(), lambda _: None)
    assert (result.accepted, result.pending, result.adjusted) == (3, 1, 2)
    assert "2 dates adjusted" in result.summary
    assert "Original estimated playback start (UTC)" in result.notices[0]
    assert "Last.fm submission start (UTC)" in result.notices[0]
    assert "submitted start (UTC)" in result.issues[0]
    assert "more than 14 days old" not in result.issues[0]
    assert all(listen.timestamp < NOW - 14 * 86400 for listen in brainz.calls[0])
    lastfm.partial = False
    lastfm.after_submit = lambda: None
    restarted = ScrobbleService(
        SourceStub(),
        ScrobbleQueue(queue.host_file),
        MemoryCredentials(),
        clients=clients.__getitem__,
        clock=lambda: NOW + 60,
    )
    removed = replace(active, library=LibrarySnapshot())
    retry = restarted.run(removed, ACCOUNTS, Event(), lambda _: None)
    assert (retry.accepted, retry.pending, retry.adjusted) == (1, 0, 1)
    assert lastfm.calls[1] == (lastfm.calls[0][1],)
    assert restarted.run(active, ACCOUNTS, Event(), lambda _: None).accepted == 0
    assert len(lastfm.calls) == 2 and len(brainz.calls) == 1


def test_uncertain_response_retries_the_saved_adjusted_date(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((track(last_played=NOW - 30 * 86400),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    client = ClientStub()
    client.error = True
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    assert service.run(active, ACCOUNTS[:1], Event(), lambda _: None).pending == 2
    client.error = False
    restarted = ScrobbleService(
        SourceStub(),
        ScrobbleQueue(queue.host_file),
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW + 120,
    )
    assert restarted.run(active, ACCOUNTS[:1], Event(), lambda _: None).accepted == 2
    assert client.calls[0] == client.calls[1]


def test_adjustment_write_failure_prevents_network(
    device: Device, tmp_path: Path
) -> None:
    class FailingQueue(ScrobbleQueue):
        def save(self, state: QueueState) -> None:
            raise OSError("disk full")

    queue = FailingQueue(AtomicHostFile(tmp_path / "queue.json"))
    client = ClientStub()
    active = replace(
        device.active, library=LibrarySnapshot((track(last_played=NOW - 30 * 86400),))
    )
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    with pytest.raises(OSError, match="disk full"):
        service.run(active, ACCOUNTS, Event(), lambda _: None)
    assert not client.calls


def test_no_available_seconds_defers_old_dates_without_submitting_them(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((track(last_played=NOW - 30 * 86400),))
    )
    state = QueueState()
    state.lastfm_reserved_through[ACCOUNTS[0].identity] = NOW
    capture(state, "volume", active.library, ACCOUNTS[:1], NOW)
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    queue.save(state)
    client = ClientStub()
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS[:1], Event(), lambda _: None)
    assert (result.accepted, result.pending, result.adjusted) == (0, 2, 0)
    assert "Retry later" in result.issues[0]
    assert not client.calls and queue.load().pending == state.pending
    later = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW + 2,
    )
    assert later.run(active, ACCOUNTS[:1], Event(), lambda _: None).accepted == 2
    assert [listen.timestamp for listen in client.calls[0]] == [NOW + 1, NOW + 2]


def test_adjusted_lastfm_dates_match_reordered_response_receipts(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((track(last_played=NOW - 30 * 86400),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    replies = [
        acknowledgement(Listen("Artist", "Song", "Album", NOW, 180), 0),
        acknowledgement(Listen("Artist", "Song", "Album", NOW - 1, 180), 1),
    ]
    client = LastFmClient(TransportStub({"scrobbles": {"scrobble": replies}}))
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: client,
        clock=lambda: NOW,
    )
    result = service.run(active, ACCOUNTS[:1], Event(), lambda _: None)
    assert (result.accepted, result.pending, result.adjusted) == (1, 1, 2)
    remaining = queue.load().pending[0]
    assert remaining.submission.timestamp == NOW - 1
    assert remaining.listen.timestamp == NOW - 30 * 86400 - 360
