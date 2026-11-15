"""Rating feedback has independent, durable latest-intent delivery semantics."""

import io
import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import mutagen
import pytest
from mutagen import id3
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_scrobbling import (
    ACCOUNTS,
    NOW,
    MemoryCredentials,
    SourceStub,
    track,
)
from tests.iOpenPod.lyrics_test_support import MemorySource, SourceProvider, media

from iOpenPod.app.media.recording_id import embedded_recording_mbid
from iOpenPod.app.media.tag_reader import read_embedded_media
from iOpenPod.app.scrobbling.clients import (
    LISTENBRAINZ_URL,
    ListenBrainzClient,
    Response,
)
from iOpenPod.app.scrobbling.feedback import capture_feedback, feedback_score
from iOpenPod.app.scrobbling.models import Account, Credentials, ScrobbleError, Service
from iOpenPod.app.scrobbling.queue import QueueState, ScrobbleQueue, capture
from iOpenPod.app.scrobbling.service import ScrobbleService
from iPodDB.library import LibrarySnapshot, MediaType
from storage import AtomicHostFile, StorageError

MBID = "9f24c0f7-a644-4074-8fbd-a1dba03de129"
OTHER_MBID = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
CREDS = Credentials("alice", "private-token")
LB = ACCOUNTS[1:]
FRAMES: Any = id3
MUTAGEN: Any = mutagen


class FeedbackTransport:
    def __init__(
        self, *responses: dict[str, object] | Response | ScrobbleError
    ) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, bytes | None, Mapping[str, str]]] = []
        self.after_request: Callable[[], None] = lambda: None

    def request(
        self, url: str, data: bytes | None, headers: Mapping[str, str]
    ) -> Response:
        self.calls.append((url, data, headers))
        result = self.responses.pop(0)
        self.after_request()
        if isinstance(result, ScrobbleError):
            raise result
        return result if isinstance(result, Response) else Response(result)


@pytest.fixture
def device(tmp_path: Path) -> Iterator[Device]:
    device = build_device(tmp_path)
    yield device
    device.coordinator.close()


@pytest.mark.parametrize(
    ("rating", "score"),
    [
        (0, 0),
        (20, -1),
        (40, -1),
        (60, 0),
        (80, 1),
        (100, 1),
        (255, 0),
        (-1, 0),
        (70, 0),
    ],
)
def test_exact_native_rating_mapping(rating: int, score: int) -> None:
    assert feedback_score(rating) == score


def test_client_contract_and_no_match() -> None:
    transport = FeedbackTransport({"recording_mbid": MBID}, {"status": "ok"}, {})
    client = ListenBrainzClient(transport)
    assert client.lookup_recording("Björk & band", "Jóga?", CREDS) == MBID
    client.submit_feedback(MBID, -1, CREDS)
    assert client.lookup_recording("Unknown", "Unknown", CREDS) == ""
    lookup, post, _ = transport.calls
    assert parse_qs(urlsplit(lookup[0]).query) == {
        "artist_name": ["Björk & band"],
        "recording_name": ["Jóga?"],
    }
    assert lookup[1] is None
    assert all(
        call[2]["Authorization"] == "Token private-token" for call in transport.calls
    )
    assert post[0] == LISTENBRAINZ_URL + "feedback/recording-feedback"
    assert post[1] is not None
    assert json.loads(post[1]) == {"recording_mbid": MBID, "score": -1}


@pytest.mark.parametrize(
    "payload", [{"recording_mbid": "invalid"}, {"error": "secret"}]
)
def test_malformed_lookup_is_retryable_and_does_not_reflect_response(
    payload: dict[str, object],
) -> None:
    client = ListenBrainzClient(FeedbackTransport(payload))
    with pytest.raises(ScrobbleError, match="invalid recording lookup") as error:
        client.lookup_recording("Artist", "Title", CREDS)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("score", [0, 2, True])
def test_client_never_sends_clear_or_invalid_scores(score: int) -> None:
    transport = FeedbackTransport()
    with pytest.raises(ScrobbleError, match="Invalid"):
        ListenBrainzClient(transport).submit_feedback(MBID, score, CREDS)
    assert not transport.calls


def test_capture_coalesces_ratings_independently_of_play_counts() -> None:
    song = replace(track(count=0, last_played=0), rating=100)
    state = QueueState()
    reads: list[int] = []

    def mbid(song: object) -> str:
        reads.append(1)
        return MBID

    def observe(rating: int) -> None:
        capture_feedback(
            state,
            "volume",
            LibrarySnapshot((replace(song, rating=rating),)),
            LB,
            mbid,
            Event(),
        )

    observe(100)
    item = next(iter(state.feedback.values()))
    assert item.account == LB[0].identity and item.score == 1
    assert not state.pending and not state.cursors
    observe(80)
    assert len(reads) == 1
    observe(20)
    assert len(state.feedback) == 1 and next(iter(state.feedback.values())).score == -1
    observe(60)
    assert not state.feedback
    observe(100)
    assert len(state.feedback) == 1 and len(reads) == 3


def test_non_music_and_missing_identity_do_not_capture() -> None:
    song = replace(track(), rating=100)
    state = QueueState()
    songs = (
        replace(song, ipod=None),
        replace(song, artist=""),
        replace(song, media_types=(MediaType.PODCAST,)),
        replace(song, media_types=(MediaType.AUDIOBOOK,)),
    )

    def unexpected_read(song: object) -> str:
        pytest.fail("ineligible Track metadata was read")

    for song in songs:
        capture_feedback(
            state,
            "volume",
            LibrarySnapshot((song,)),
            LB,
            unexpected_read,
            Event(),
        )
    assert not state.feedback


def test_feedback_retries_without_replaying_accepted_listens_after_removal(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    transport = FeedbackTransport(
        {"status": "ok"}, {"recording_mbid": MBID}, ScrobbleError("offline")
    )
    brainz = ListenBrainzClient(transport)

    def service() -> ScrobbleService:
        return ScrobbleService(
            SourceStub(),
            queue,
            MemoryCredentials(),
            clients=lambda _: brainz,
            clock=lambda: NOW,
        )

    result = service().run(active, LB, Event(), lambda _: None, ratings=True)
    assert (
        result.accepted,
        result.pending,
        result.feedback_accepted,
        result.feedback_pending,
    ) == (2, 0, 0, 1)
    assert "private-token" not in queue.host_file.path.read_text()
    saved = next(iter(queue.load().feedback.values()))
    assert saved.pending and saved.recording_mbid == MBID
    transport.responses.append({"status": "ok"})
    removed = replace(active, library=LibrarySnapshot())
    result = service().run(removed, LB, Event(), lambda _: None, ratings=True)
    assert (result.accepted, result.feedback_accepted, result.feedback_pending) == (
        0,
        1,
        0,
    )
    assert [urlsplit(call[0]).path for call in transport.calls] == [
        "/1/submit-listens",
        "/1/metadata/lookup/",
        "/1/feedback/recording-feedback",
        "/1/feedback/recording-feedback",
    ]
    # Reloading unchanged committed evidence does not repost feedback or plays.
    assert (
        service()
        .run(active, LB, Event(), lambda _: None, ratings=True)
        .feedback_accepted
        == 0
    )
    assert len(transport.calls) == 4


def test_disabled_feedback_and_disconnected_accounts_retain_pending_work(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture_feedback(state, "volume", active.library, LB, lambda _: MBID, Event())
    queue.save(state)
    transport = FeedbackTransport({"status": "ok"})
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    for accounts, ratings in ((LB, False), ((), True)):
        service.run(active, accounts, Event(), lambda _: None, ratings=ratings)
        assert not transport.calls
        assert next(iter(queue.load().feedback.values())).pending
    assert (
        service.run(active, LB, Event(), lambda _: None, ratings=True).feedback_accepted
        == 1
    )


def test_no_match_is_skipped_and_new_observation_can_retry(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    transport = FeedbackTransport({})
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    result = service.run(active, LB, Event(), lambda _: None, ratings=True)
    assert result.feedback_skipped == 1 and result.feedback_pending == 0
    assert "unmatched" in result.summary
    service.run(active, LB, Event(), lambda _: None, ratings=True)
    assert len(transport.calls) == 1
    changed = replace(
        active, library=LibrarySnapshot((replace(active.library.tracks[0], rating=20),))
    )
    transport.responses.extend([{"recording_mbid": MBID}, {"status": "ok"}])
    assert (
        service.run(
            changed, LB, Event(), lambda _: None, ratings=True
        ).feedback_accepted
        == 1
    )
    data = transport.calls[-1][1]
    assert data is not None and json.loads(data)["score"] == -1


@pytest.mark.parametrize("phase", ["lookup", "post"])
def test_cancellation_after_response_keeps_identity_or_acknowledgement(
    device: Device, tmp_path: Path, phase: str
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture_feedback(
        state,
        "volume",
        active.library,
        LB,
        lambda _: MBID if phase == "post" else "",
        Event(),
    )
    queue.save(state)
    cancelled = Event()
    transport = FeedbackTransport(
        {"status": "ok"} if phase == "post" else {"recording_mbid": MBID}
    )
    transport.after_request = cancelled.set
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    result = service.run(active, LB, cancelled, lambda _: None, ratings=True)
    saved = next(iter(queue.load().feedback.values()))
    assert saved.recording_mbid == MBID and saved.pending == (phase == "lookup")
    assert result.cancelled and len(transport.calls) == 1
    assert result.feedback_accepted == (phase == "post")


def test_rate_limit_after_lookup_retains_resolved_identity(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    transport = FeedbackTransport(Response({"recording_mbid": MBID}, retry_after=61))
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    result = service.run(active, LB, Event(), lambda _: None, ratings=True)
    assert result.feedback_pending == 1 and "longer pause" in result.issues[0]
    assert len(transport.calls) == 1
    assert next(iter(queue.load().feedback.values())).recording_mbid == MBID


def test_disconnect_after_lookup_stops_post(device: Device, tmp_path: Path) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    source = SourceStub()
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    transport = FeedbackTransport({"recording_mbid": MBID})

    def unplug() -> None:
        source.disconnected = True

    transport.after_request = unplug
    service = ScrobbleService(
        source,
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    with pytest.raises(StorageError, match="disconnected"):
        service.run(active, LB, Event(), lambda _: None, ratings=True)
    assert len(transport.calls) == 1
    assert next(iter(queue.load().feedback.values())).pending


@pytest.mark.parametrize("version", [1, 2])
def test_old_queue_upgrade_preserves_play_history(tmp_path: Path, version: int) -> None:
    state = QueueState(lastfm_reserved_through={ACCOUNTS[0].identity: NOW})
    capture(state, "volume", LibrarySnapshot((track(),)), ACCOUNTS, NOW)
    payload: dict[str, object] = {
        "version": version,
        "pending": [asdict(item) for item in state.pending],
        "cursors": state.cursors,
    }
    if version == 2:
        payload["lastfm_reserved_through"] = state.lastfm_reserved_through
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(payload))
    queue = ScrobbleQueue(AtomicHostFile(path))
    migrated = queue.load()
    assert not migrated.feedback
    assert migrated.pending == state.pending and migrated.cursors == state.cursors
    queue.save(migrated)
    assert queue.load() == migrated
    assert migrated.lastfm_reserved_through == (
        state.lastfm_reserved_through if version == 2 else {}
    )
    assert json.loads(path.read_text())["version"] == 4


@pytest.mark.parametrize(
    "change",
    [
        {"score": 0},
        {"pending": "yes"},
        {"recording_mbid": "invalid"},
        {"account": "lastfm:alice"},
    ],
)
def test_corrupt_feedback_is_preserved_and_blocks_queue(
    tmp_path: Path, change: dict[str, object]
) -> None:
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture_feedback(
        state,
        "volume",
        LibrarySnapshot((replace(track(), rating=100),)),
        LB,
        lambda _: MBID,
        Event(),
    )
    queue.save(state)
    payload = json.loads(queue.host_file.path.read_bytes())
    payload["feedback"][0].update(change)
    raw = json.dumps(payload).encode()
    queue.host_file.path.write_bytes(raw)
    with pytest.raises(ScrobbleError, match="preserved"):
        queue.load()
    assert queue.host_file.path.read_bytes() == raw


@pytest.mark.parametrize("name", ["tone.mp3", "tone.m4a", "tone.wav", "tone.aiff"])
def test_embedded_ids_are_read_without_lookup_or_source_writes(
    device: Device, tmp_path: Path, name: str
) -> None:
    stream = io.BytesIO(media(name))
    parsed = MUTAGEN.File(stream)
    if name.endswith("m4a"):
        parsed.tags["----:com.apple.iTunes:MusicBrainz Track Id"] = [MBID.encode()]
    else:
        parsed.tags.add(FRAMES.UFID(owner="http://musicbrainz.org", data=MBID.encode()))
    parsed.save(stream)
    original = stream.getvalue()
    source = MemorySource(original, name)
    provider = SourceProvider({1: source})
    transport = FeedbackTransport({"status": "ok"})
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
        media=provider,
    )
    assert (
        service.run(active, LB, Event(), lambda _: None, ratings=True).feedback_accepted
        == 1
    )
    assert len(transport.calls) == 1 and "recording-feedback" in transport.calls[0][0]
    assert source.payload == original and all(
        size <= 64 * 1024 for _, size in source.reads
    )
    service.run(active, LB, Event(), lambda _: None, ratings=True)
    assert len(provider.opened) == 1


def test_release_track_id_malformed_and_conflicting_recording_ids_are_not_used() -> (
    None
):
    for tags in (
        {"musicbrainz_releasetrackid": [MBID]},
        {"musicbrainz_trackid": [MBID, OTHER_MBID]},
        {"musicbrainz_trackid": ["invalid", MBID]},
    ):
        assert not embedded_recording_mbid(SimpleNamespace(tags=tags))
    assert (
        embedded_recording_mbid(SimpleNamespace(tags={"musicbrainz_trackid": [MBID]}))
        == MBID
    )
    source = MemorySource(media())
    assert not embedded_recording_mbid(
        read_embedded_media(source, checkpoint=lambda: None)
    )


def test_feedback_receipts_are_account_and_volume_scoped() -> None:
    state = QueueState()
    library = LibrarySnapshot((replace(track(count=0), rating=100),))
    for volume, account in (
        ("one", LB[0]),
        ("two", LB[0]),
        ("one", Account(Service.LISTENBRAINZ, "bob")),
    ):
        capture_feedback(state, volume, library, (account,), lambda _: MBID, Event())
    assert len(state.feedback) == 3
    capture_feedback(
        state,
        "one",
        library,
        (Account(Service.LISTENBRAINZ, "ALICE"),),
        lambda _: MBID,
        Event(),
    )
    assert len(state.feedback) == 3


@pytest.mark.parametrize("rating", [0, 60, 20])
def test_new_rating_withdraws_or_supersedes_failed_feedback(
    device: Device, tmp_path: Path, rating: int
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture_feedback(state, "volume", active.library, LB, lambda _: MBID, Event())
    queue.save(state)
    changed = replace(
        active,
        library=LibrarySnapshot((replace(active.library.tracks[0], rating=rating),)),
    )
    transport = FeedbackTransport({"recording_mbid": MBID}, {"status": "ok"})
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    result = service.run(changed, LB, Event(), lambda _: None, ratings=True)
    assert result.feedback_pending == 0
    if rating == 20:
        payload = transport.calls[-1][1]
        assert payload is not None and json.loads(payload)["score"] == -1
    else:
        assert not transport.calls and not queue.load().feedback


def test_feedback_capture_persistence_failure_prevents_network(
    device: Device, tmp_path: Path
) -> None:
    class FailingQueue(ScrobbleQueue):
        def save(self, state: QueueState) -> None:
            raise OSError("disk full")

    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=0), rating=100),))
    )
    transport = FeedbackTransport()
    service = ScrobbleService(
        SourceStub(),
        FailingQueue(AtomicHostFile(tmp_path / "queue.json")),
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    with pytest.raises(OSError, match="disk full"):
        service.run(active, LB, Event(), lambda _: None, ratings=True)
    assert not transport.calls
