"""Count processed work after persistence without conflating it with acceptance."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device
from tests.iOpenPod.app.test_lastfm_feedback import ImmediateEvent
from tests.iOpenPod.app.test_listenbrainz_feedback import MBID, FeedbackTransport
from tests.iOpenPod.app.test_scrobbling import (
    ACCOUNTS,
    NOW,
    MemoryCredentials,
    SourceStub,
    track,
)
from tests.iOpenPod.app.test_scrobbling import device as device
from tests.iOpenPod.app.test_scrobbling_clients import acknowledgement

from iOpenPod.app.scrobbling.clients import LastFmClient, ListenBrainzClient
from iOpenPod.app.scrobbling.models import ScrobbleError, ScrobbleProgress, Service
from iOpenPod.app.scrobbling.queue import QueueState, ScrobbleQueue, capture
from iOpenPod.app.scrobbling.service import ScrobbleService
from iPodDB.library import IPodTrackDetails, LibrarySnapshot
from storage import AtomicHostFile


def test_progress_resets_for_each_service_and_work_type(
    device: Device, tmp_path: Path
) -> None:
    active = replace(
        device.active, library=LibrarySnapshot((replace(track(count=3), rating=100),))
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState()
    capture(state, "volume", active.library, ACCOUNTS, NOW)
    queue.save(state)
    listens = sorted(
        (item.listen for item in state.pending if item.account == ACCOUNTS[0].identity),
        key=lambda item: item.timestamp,
    )
    lastfm = LastFmClient(
        FeedbackTransport(
            {
                "scrobbles": {
                    "scrobble": [acknowledgement(item, 0) for item in listens[:2]]
                }
            },
            {"scrobbles": {"scrobble": [acknowledgement(listens[2], 0)]}},
            {"status": "ok"},
        )
    )
    listenbrainz = ListenBrainzClient(
        FeedbackTransport(
            {"status": "ok"},
            {"status": "ok"},
            {"recording_mbid": MBID},
            {"status": "ok"},
        )
    )
    lastfm.batch_size = listenbrainz.batch_size = 2
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda service: lastfm if service is Service.LASTFM else listenbrainz,
        clock=lambda: NOW,
    )
    events: list[ScrobbleProgress] = []
    result = service.run(
        active, ACCOUNTS, ImmediateEvent(), events.append, ratings=True
    )
    assert result.accepted == 6 and result.feedback_accepted == 2
    assert events[0].total is None
    assert list(dict.fromkeys(event.phase for event in events)) == [
        "capture",
        "lastfm.plays",
        "lastfm.ratings",
        "listenbrainz.plays",
        "listenbrainz.ratings",
    ]
    for account in ACCOUNTS:
        plays = [event for event in events if event.phase == f"{account.service}.plays"]
        ratings = [
            event for event in events if event.phase == f"{account.service}.ratings"
        ]
        assert [event.completed for event in plays] == [0, 2, 2, 3]
        assert all(event.total == 3 and event.unit == "plays" for event in plays)
        assert [event.completed for event in ratings] == [0, 1]
        assert all(event.total == 1 and event.unit == "ratings" for event in ratings)
        assert ratings[-1].current_item == "Artist — Song"


@pytest.mark.parametrize("outcome", ["accepted", "unmatched", "failed", "cancelled"])
def test_rating_progress_follows_saved_receipts_and_stops_on_interruption(
    device: Device, tmp_path: Path, outcome: str
) -> None:
    active = replace(
        device.active,
        library=LibrarySnapshot(
            tuple(
                replace(
                    track(count=0),
                    track_id=index,
                    title=f"Song {index}",
                    rating=100,
                    ipod=IPodTrackDetails(db_track_id=index),
                )
                for index in (1, 2)
            )
        ),
    )
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    responses: list[dict[str, object] | ScrobbleError] = (
        [{}, {}]
        if outcome == "unmatched"
        else [
            {"recording_mbid": MBID},
            {"status": "ok"},
            {"recording_mbid": MBID},
            ScrobbleError("offline") if outcome == "failed" else {"status": "ok"},
        ]
    )
    transport = FeedbackTransport(*responses)
    service = ScrobbleService(
        SourceStub(),
        queue,
        MemoryCredentials(),
        clients=lambda _: ListenBrainzClient(transport),
        clock=lambda: NOW,
    )
    cancelled = ImmediateEvent()
    events: list[ScrobbleProgress] = []

    def progress(event: ScrobbleProgress) -> None:
        events.append(event)
        if event.completed:
            saved = queue.load()
            assert (
                sum(not item.pending for item in saved.feedback.values())
                == event.completed
            )
            if outcome == "cancelled":
                cancelled.set()

    result = service.run(active, ACCOUNTS[1:], cancelled, progress, ratings=True)
    ratings = [event for event in events if event.unit == "ratings"]
    assert all(event.total == 2 for event in ratings)
    assert ratings[-1].completed == (1 if outcome in ("failed", "cancelled") else 2)
    assert result.feedback_pending == int(outcome in ("failed", "cancelled"))
    assert result.feedback_skipped == (2 if outcome == "unmatched" else 0)
    assert result.cancelled == (outcome == "cancelled")
