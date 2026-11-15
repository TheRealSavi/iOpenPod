"""Last.fm loved status shares durable rating intent, never ListenBrainz's Hate."""

import hashlib
import io
import json
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs
from urllib.request import Request

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device
from tests.iOpenPod.app.test_listenbrainz_feedback import MBID, FeedbackTransport
from tests.iOpenPod.app.test_scrobbling import (
    ACCOUNTS,
    NOW,
    MemoryCredentials,
    SourceStub,
    track,
)
from tests.iOpenPod.app.test_scrobbling import device as device
from tests.iOpenPod.app.test_scrobbling_clients import CREDENTIALS, acknowledgement

from iOpenPod.app.scrobbling import clients
from iOpenPod.app.scrobbling.clients import LastFmClient, ListenBrainzClient
from iOpenPod.app.scrobbling.feedback import capture_feedback
from iOpenPod.app.scrobbling.models import ScrobbleError, Service
from iOpenPod.app.scrobbling.queue import QueueState, ScrobbleQueue, capture
from iOpenPod.app.scrobbling.service import ScrobbleService
from iPodDB.library import LibrarySnapshot
from storage import AtomicHostFile, StorageError

LF = ACCOUNTS[:1]


class ImmediateEvent(Event):
    """Advance rate-limit waits synchronously while retaining cancellation checks."""

    def wait(self, timeout: float | None = None) -> bool:
        return self.is_set()


class _HttpReply(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers: dict[str, str] = {}


def _http_reply(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[Request]:
    requests: list[Request] = []

    def open_reply(request: Request, *, timeout: int) -> _HttpReply:
        requests.append(request)
        assert timeout == 15
        return _HttpReply(payload)

    def build_reply(*_: object) -> SimpleNamespace:
        return SimpleNamespace(open=open_reply)

    monkeypatch.setattr(clients, "build_opener", build_reply)
    return requests


@pytest.mark.parametrize("loved", [False, True])
def test_signed_loved_status_post_uses_explicit_xml_acknowledgement(
    monkeypatch: pytest.MonkeyPatch, loved: bool
) -> None:
    requests = _http_reply(monkeypatch, b'<?xml version="1.0"?><lfm status="ok"/>')
    LastFmClient().set_loved("Björk & band", "Jóga?", loved, CREDENTIALS)
    (request,) = requests
    assert request.full_url == clients.LASTFM_URL
    assert request.get_method() == "POST"
    assert request.get_header("Accept") == "application/xml"
    assert isinstance(request.data, bytes)
    form = parse_qs(request.data.decode())
    values = {
        "method": "track.love" if loved else "track.unlove",
        "artist": "Björk & band",
        "track": "Jóga?",
        "api_key": CREDENTIALS.api_key,
        "sk": CREDENTIALS.token,
    }
    signature = "".join(key + values[key] for key in sorted(values))
    signature += CREDENTIALS.api_secret
    assert form == {
        **{key: [value] for key, value in values.items()},
        "format": ["xml"],
        "api_sig": [hashlib.md5(signature.encode()).hexdigest()],
    }


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{}",
        b'<?xml version="1.0" encoding="unknown-encoding"?><lfm status="ok"/>',
        b'<lfm status="ok">',
        b'<html status="ok"/>',
        b"<lfm/>",
        b'<lfm status="failed"/>',
        b'<lfm status="ok"><error code="9">secret</error></lfm>',
        b'<lfm status="ok">unexpected</lfm>',
        b'<lfm status="ok"><scrobbles/></lfm>',
        b'<lfm status="failed"><error code="invalid">secret</error></lfm>',
        b'<!DOCTYPE lfm [<!ENTITY value "ok">]><lfm status="&value;"/>',
        '<!DOCTYPE lfm SYSTEM "file:///secret"><lfm status="ok"/>'.encode("utf-16"),
        b"x" * (clients.MAX_RESPONSE + 1),
    ],
    ids=[
        "empty",
        "json",
        "unknown-encoding",
        "truncated",
        "wrong-root",
        "missing-status",
        "missing-error",
        "error-in-success",
        "unexpected-text",
        "wrong-ack",
        "invalid-code",
        "entity",
        "external-dtd",
        "oversized",
    ],
)
def test_unacknowledged_or_unsafe_xml_never_settles_ratings(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    _http_reply(monkeypatch, payload)
    with pytest.raises(ScrobbleError) as error:
        LastFmClient().set_loved("Artist", "Song", True, CREDENTIALS)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("code", [9, 13, 29])
def test_xml_errors_use_existing_authentication_and_rate_limit_diagnostics(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    _http_reply(
        monkeypatch,
        f'<lfm status="failed"><error code="{code}">private-secret</error></lfm>'.encode(),
    )
    with pytest.raises(ScrobbleError, match=f"Last.fm error {code}") as error:
        LastFmClient().set_loved("Artist", "Song", False, CREDENTIALS)
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize(("artist", "title"), [("", "Song"), ("Artist", " ")])
def test_missing_track_identity_never_posts(artist: str, title: str) -> None:
    transport = FeedbackTransport()
    with pytest.raises(ScrobbleError, match="Invalid"):
        LastFmClient(transport).set_loved(artist, title, True, CREDENTIALS)
    assert not transport.calls


@pytest.mark.parametrize(
    ("rating", "method"),
    [
        (0, None),
        (20, "track.unlove"),
        (40, "track.unlove"),
        (60, None),
        (80, "track.love"),
        (100, "track.love"),
        (70, None),
        (255, None),
    ],
)
def test_rating_mapping_needs_no_plays_or_recording_lookup(
    device: Device, tmp_path: Path, rating: int, method: str | None
) -> None:
    active = replace(
        device.active,
        library=LibrarySnapshot(
            (replace(track(count=0, last_played=0), rating=rating),)
        ),
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    transport = FeedbackTransport({"status": "ok"})
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: LastFmClient(transport),
        clock=lambda: NOW,
    )
    result = service.run(active, LF, ImmediateEvent(), lambda _: None, ratings=True)
    assert result.accepted == result.pending == result.feedback_pending == 0
    assert result.feedback_accepted == int(method is not None)
    if method:
        (call,) = transport.calls
        assert call[0] == clients.LASTFM_URL and call[1] is not None
        assert parse_qs(call[1].decode())["method"] == [method]
        assert "Star ratings: 1 accepted" in result.summary
        assert "ListenBrainz" not in result.summary
        (receipt,) = queue.load().feedback.values()
        assert not receipt.pending and not receipt.recording_mbid
    else:
        assert not transport.calls and not queue.load().feedback
    # Reloaded receipts suppress duplicate feedback even though no play cursor exists.
    again = service.run(active, LF, ImmediateEvent(), lambda _: None, ratings=True)
    assert again.feedback_accepted == 0


def test_capture_coalesces_lastfm_intent_without_reading_media() -> None:
    state = QueueState()

    def unexpected_read(_: object) -> str:
        pytest.fail("Last.fm ratings must not read embedded recording IDs")

    for rating, expected in [
        (100, 1),
        (80, 1),
        (20, -1),
        (40, -1),
        (60, 0),
        (0, 0),
        (100, 1),
    ]:
        capture_feedback(
            state,
            "volume",
            LibrarySnapshot((replace(track(count=0), rating=rating),)),
            LF,
            unexpected_read,
            Event(),
        )
        assert len(state.feedback) == bool(expected)
        if expected:
            (item,) = state.feedback.values()
            assert item.score == expected and not item.recording_mbid


def test_failed_lastfm_feedback_retries_without_replaying_listens_or_listenbrainz(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture(state, "volume", active.library, LF, NOW)
    lf = FeedbackTransport(
        {
            "scrobbles": {
                "scrobble": [acknowledgement(item.listen, 0) for item in state.pending]
            }
        },
        ScrobbleError("offline"),
    )
    lb = FeedbackTransport({"status": "ok"}, {"recording_mbid": MBID}, {"status": "ok"})

    def service() -> ScrobbleService:
        return ScrobbleService(
            SourceStub(),
            queue,
            MemoryCredentials(),
            clients=lambda s: (
                LastFmClient(lf) if s is Service.LASTFM else ListenBrainzClient(lb)
            ),
            clock=lambda: NOW,
        )

    result = service().run(
        active, ACCOUNTS, ImmediateEvent(), lambda _: None, ratings=True
    )
    assert (
        result.accepted,
        result.pending,
        result.feedback_accepted,
        result.feedback_pending,
    ) == (4, 0, 1, 1)
    assert result.issues == ("Last.fm: offline",)
    removed = replace(active, library=LibrarySnapshot())
    lf.responses.append({"status": "ok"})
    result = service().run(
        removed, ACCOUNTS, ImmediateEvent(), lambda _: None, ratings=True
    )
    assert (result.accepted, result.feedback_accepted, result.feedback_pending) == (
        0,
        1,
        0,
    )
    assert len(lf.calls) == len(lb.calls) == 3
    assert parse_qs((lf.calls[-1][1] or b"").decode())["method"] == ["track.love"]


@pytest.mark.parametrize("rating", [0, 20, 40, 60, 80, 100])
def test_latest_rating_replaces_unsent_intent(
    device: Device, tmp_path: Path, rating: int
) -> None:
    song = replace(track(count=0), rating=100)
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture_feedback(
        state, "volume", LibrarySnapshot((song,)), LF, lambda _: "", Event()
    )
    queue.save(state)
    transport = FeedbackTransport({"status": "ok"})
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: LastFmClient(transport),
    )
    active = replace(
        device.active, library=LibrarySnapshot((replace(song, rating=rating),))
    )
    result = service.run(active, LF, ImmediateEvent(), lambda _: None, ratings=True)
    assert result.feedback_pending == 0
    if rating in (0, 60):
        assert not transport.calls
    else:
        assert parse_qs((transport.calls[0][1] or b"").decode())["method"] == [
            "track.unlove" if rating in (20, 40) else "track.love"
        ]


def test_disabled_and_disconnected_accounts_preserve_pending_lastfm_work(
    device: Device, tmp_path: Path
) -> None:
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture_feedback(
        state,
        "volume",
        LibrarySnapshot((replace(track(count=0), rating=20),)),
        LF,
        lambda _: "",
        Event(),
    )
    queue.save(state)
    transport = FeedbackTransport({"status": "ok"})
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: LastFmClient(transport),
    )
    removed = replace(device.active, library=LibrarySnapshot())
    for accounts, ratings in [(LF, False), (ACCOUNTS[1:], True), ((), True)]:
        result = service.run(
            removed, accounts, ImmediateEvent(), lambda _: None, ratings=ratings
        )
        assert not transport.calls and result.feedback_pending == 0
        assert next(iter(queue.load().feedback.values())).pending
    result = service.run(removed, LF, ImmediateEvent(), lambda _: None, ratings=True)
    assert result.feedback_accepted == 1


@pytest.mark.parametrize("interrupt", ["cancel", "disconnect"])
def test_received_acknowledgement_is_saved_before_interruption(
    device: Device, tmp_path: Path, interrupt: str
) -> None:
    song = replace(track(count=0), rating=100)
    assert song.ipod is not None
    second = replace(song, track_id=2, ipod=replace(song.ipod, db_track_id=2345))
    active = replace(device.active, library=LibrarySnapshot((song, second)))
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    source, cancelled = SourceStub(), ImmediateEvent()
    transport = FeedbackTransport({"status": "ok"})

    def stop() -> None:
        if interrupt == "cancel":
            cancelled.set()
        else:
            source.disconnected = True

    transport.after_request = stop
    service = ScrobbleService(
        source, queue, MemoryCredentials(), clients=lambda _: LastFmClient(transport)
    )
    if interrupt == "disconnect":
        with pytest.raises(StorageError, match="disconnected"):
            service.run(active, LF, cancelled, lambda _: None, ratings=True)
    else:
        result = service.run(active, LF, cancelled, lambda _: None, ratings=True)
        assert (
            result.cancelled
            and result.feedback_accepted == result.feedback_pending == 1
        )
    assert len(transport.calls) == 1
    assert sum(item.pending for item in queue.load().feedback.values()) == 1


def test_v3_upgrade_preserves_listenbrainz_receipts_and_play_history(
    tmp_path: Path,
) -> None:
    state = QueueState(lastfm_reserved_through={LF[0].identity: NOW})
    library = LibrarySnapshot((replace(track(), rating=100),))
    capture(state, "volume", library, ACCOUNTS, NOW)
    capture_feedback(state, "volume", library, ACCOUNTS[1:], lambda _: MBID, Event())
    for key, item in state.feedback.items():
        state.feedback[key] = replace(item, pending=False)
    payload = {
        "version": 3,
        "cursors": state.cursors,
        "pending": [asdict(item) for item in state.pending],
        "lastfm_reserved_through": state.lastfm_reserved_through,
        "feedback": [asdict(item) for item in state.feedback.values()],
    }
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    queue.host_file.replace_bytes(json.dumps(payload).encode())
    migrated = queue.load()
    assert migrated == state
    capture_feedback(migrated, "volume", library, ACCOUNTS, lambda _: MBID, Event())
    queue.save(migrated)
    assert queue.load() == migrated
    assert len(migrated.feedback) == 2
    assert sum(item.pending for item in migrated.feedback.values()) == 1
    assert json.loads(queue.host_file.path.read_bytes())["version"] == 4
