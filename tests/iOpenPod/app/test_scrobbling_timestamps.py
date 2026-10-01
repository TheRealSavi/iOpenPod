"""Last.fm date adjustment preserves evidence and survives delivery retries."""

import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import pytest

from iOpenPod.app.scrobbling.models import (
    LASTFM_MAX_AGE,
    Account,
    Listen,
    ScrobbleError,
    Service,
)
from iOpenPod.app.scrobbling.queue import PendingListen, QueueState, ScrobbleQueue
from iOpenPod.app.scrobbling.timestamps import adjust_lastfm_dates
from storage import AtomicHostFile

NOW = int(datetime(2026, 10, 1, 12).timestamp())
ACCOUNT = Account(Service.LASTFM, "alice")


def entry(identity: str = "one", *, timestamp: int = NOW - 30 * 86400) -> PendingListen:
    return PendingListen(
        identity,
        "volume",
        ACCOUNT.identity,
        Listen("Artist", "Song", "Album", timestamp, 180),
    )


def test_only_old_lastfm_dates_for_the_selected_account_and_device_change() -> None:
    old = entry()
    boundary = entry("boundary", timestamp=NOW - LASTFM_MAX_AGE)
    recent = entry("recent", timestamp=NOW - 180)
    brainz = replace(old, identity="brainz", account="listenbrainz:alice")
    other_account = replace(old, identity="bob", account="lastfm:bob")
    other_device = replace(old, identity="device", device="other")
    original = [old, boundary, recent, brainz, other_account, other_device]
    state = QueueState(pending=original.copy())
    assert adjust_lastfm_dates(state, "volume", ACCOUNT, NOW) == 0
    assert state.pending[0].listen == old.listen
    assert state.pending[0].submission.timestamp == NOW
    assert state.pending[1:] == original[1:]
    assert (
        adjust_lastfm_dates(
            state, "volume", Account(Service.LISTENBRAINZ, "alice"), NOW
        )
        == 0
    )
    assert state.pending[3] == brainz


def test_adjusted_dates_keep_order_avoid_collisions_and_stay_today() -> None:
    old = [entry(str(index), timestamp=NOW - 30 * 86400 + index) for index in range(39)]
    state = QueueState(pending=[*reversed(old), entry("recent", timestamp=NOW - 2)])
    assert adjust_lastfm_dates(state, "volume", ACCOUNT, NOW) == 0
    changed = sorted(state.pending[:-1], key=lambda item: item.listen.timestamp)
    dates = [item.submission.timestamp for item in changed]
    assert dates == sorted(set(dates)) and len(dates) == 39
    assert NOW - 2 not in dates
    assert all(
        datetime.fromtimestamp(date).date() == datetime.fromtimestamp(NOW).date()
        for date in dates
    )
    assert max(dates) <= NOW
    assert [item.listen for item in changed] == [item.listen for item in old]


def test_midnight_defers_excess_without_future_dates_and_resumes_later() -> None:
    midnight = int(datetime(2026, 10, 1).timestamp())
    state = QueueState(pending=[entry(str(index)) for index in range(3)])
    assert adjust_lastfm_dates(state, "volume", ACCOUNT, midnight) == 2
    assert [item.submission_timestamp for item in state.pending] == [
        midnight,
        None,
        None,
    ]
    assert adjust_lastfm_dates(state, "volume", ACCOUNT, midnight + 2) == 0
    assert [item.submission_timestamp for item in state.pending] == [
        midnight,
        midnight + 1,
        midnight + 2,
    ]


def test_dates_survive_restart_and_accepted_seconds_are_not_reallocated(
    tmp_path: Path,
) -> None:
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState(pending=[entry()])
    adjust_lastfm_dates(state, "volume", ACCOUNT, NOW)
    queue.save(state)
    loaded = queue.load()
    assert loaded == state
    adjust_lastfm_dates(loaded, "volume", ACCOUNT, NOW + 1)
    assert loaded.pending == state.pending
    # Acknowledged deliveries leave the queue but retain the allocation watermark.
    loaded.pending = [entry("new")]
    queue.save(loaded)
    loaded = queue.load()
    assert adjust_lastfm_dates(loaded, "volume", ACCOUNT, NOW) == 1
    assert loaded.pending[0].submission_timestamp is None
    assert adjust_lastfm_dates(loaded, "volume", ACCOUNT, NOW + 1) == 0
    assert loaded.pending[0].submission.timestamp == NOW + 1


def test_a_saved_adjustment_is_reused_until_it_also_exceeds_the_window() -> None:
    state = QueueState(pending=[entry()])
    adjust_lastfm_dates(state, "volume", ACCOUNT, NOW)
    original = state.pending[0]
    adjust_lastfm_dates(state, "volume", ACCOUNT, NOW + LASTFM_MAX_AGE)
    assert state.pending[0] == original
    later = NOW + LASTFM_MAX_AGE + 1
    adjust_lastfm_dates(state, "volume", ACCOUNT, later)
    assert state.pending[0].submission.timestamp == later
    assert state.pending[0].listen == original.listen


def test_version_one_queue_migrates_without_losing_cursors_or_evidence(
    tmp_path: Path,
) -> None:
    old = entry()
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "cursors": {"ordinal": 39},
                "pending": [
                    {
                        "identity": old.identity,
                        "device": old.device,
                        "account": old.account,
                        "listen": asdict(old.listen),
                    }
                ],
            }
        )
    )
    queue = ScrobbleQueue(AtomicHostFile(path))
    state = queue.load()
    assert state.pending == [old] and state.cursors == {"ordinal": 39}
    adjust_lastfm_dates(state, "volume", ACCOUNT, NOW)
    queue.save(state)
    restored = queue.load()
    assert restored == state and restored.pending[0].listen == old.listen
    assert restored.cursors == {"ordinal": 39}


@pytest.mark.parametrize("adjusted", [True, "today", -1, NOW - 40 * 86400])
def test_malformed_adjusted_dates_are_preserved_without_submission(
    tmp_path: Path, adjusted: object
) -> None:
    item = asdict(entry())
    item["submission_timestamp"] = adjusted
    raw = json.dumps(
        {"version": 2, "cursors": {}, "pending": [item], "lastfm_reserved_through": {}}
    )
    path = tmp_path / "queue.json"
    path.write_text(raw)
    with pytest.raises(ScrobbleError, match="unreadable"):
        ScrobbleQueue(AtomicHostFile(path)).load()
    assert path.read_text() == raw


@pytest.mark.parametrize(
    "reserved",
    [{"lastfm:alice": True}, {"lastfm:alice": -1}, {"listenbrainz:alice": NOW}, []],
)
def test_malformed_reservations_are_not_silently_reset(
    tmp_path: Path, reserved: object
) -> None:
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "cursors": {},
                "pending": [],
                "lastfm_reserved_through": reserved,
            }
        )
    )
    with pytest.raises(ScrobbleError, match="unreadable"):
        ScrobbleQueue(AtomicHostFile(path)).load()
