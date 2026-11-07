"""Last.fm date adjustment preserves evidence and survives delivery retries."""

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from whenever import SYSTEM_TZ, Instant, PlainDateTime

from iOpenPod.app.core.dates import refresh_host_timezone
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

NOW = (
    PlainDateTime(2026, 10, 1, 12)
    .assume_tz(SYSTEM_TZ, disambiguation="compatible")
    .timestamp()
)
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
        Instant.from_timestamp(date).to_tz(SYSTEM_TZ).date()
        == Instant.from_timestamp(NOW).to_tz(SYSTEM_TZ).date()
        for date in dates
    )
    assert max(dates) <= NOW
    assert [item.listen for item in changed] == [item.listen for item in old]


def test_midnight_defers_excess_without_future_dates_and_resumes_later() -> None:
    midnight = (
        PlainDateTime(2026, 10, 1)
        .assume_tz(SYSTEM_TZ, disambiguation="compatible")
        .timestamp()
    )
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
def test_unusual_adjusted_dates_do_not_block_loading_and_can_be_reassigned(
    tmp_path: Path, adjusted: object
) -> None:
    item = asdict(entry())
    item["submission_timestamp"] = adjusted
    raw = json.dumps(
        {"version": 2, "cursors": {}, "pending": [item], "lastfm_reserved_through": {}}
    )
    path = tmp_path / "queue.json"
    path.write_text(raw)
    state = ScrobbleQueue(AtomicHostFile(path)).load()
    assert path.read_text() == raw
    assert state.pending[0].identity == entry().identity
    assert state.pending[0].listen == entry().listen
    assert adjust_lastfm_dates(state, "volume", ACCOUNT, NOW) == 0
    assert state.pending[0].submission.timestamp == NOW


@pytest.mark.parametrize(
    "reserved",
    [{"listenbrainz:alice": NOW}, []],
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


@pytest.mark.parametrize("timestamp", [-1, 10**30])
def test_unusual_queue_dates_preserve_cursors_and_playback_evidence(
    tmp_path: Path, timestamp: int
) -> None:
    queue = ScrobbleQueue(AtomicHostFile(tmp_path / "queue.json"))
    state = QueueState(
        {"ordinal": 39}, [entry(timestamp=timestamp)], {ACCOUNT.identity: timestamp}
    )
    queue.save(state)
    assert queue.load() == state


def test_unrepresentable_host_clock_defers_delivery_without_an_error() -> None:
    state = QueueState(pending=[entry()])
    assert adjust_lastfm_dates(state, "volume", ACCOUNT, 10**30) == 1
    assert state.pending == [entry()]


def test_delivery_refreshes_host_zone_before_reserving_local_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = Instant.from_utc(2026, 10, 2, 4).timestamp()
    state = QueueState(
        pending=[entry(str(index), timestamp=now - 30 * 86400) for index in range(2)]
    )
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TZ", "UTC")
            assert refresh_host_timezone()
            patch.setenv("TZ", "America/New_York")
            # The new Host day has only one elapsed second available. The cached
            # UTC day would incorrectly allocate both old listens immediately.
            assert adjust_lastfm_dates(state, "volume", ACCOUNT, now) == 1
            assert [item.submission_timestamp for item in state.pending] == [now, None]
    finally:
        refresh_host_timezone()


def test_unavailable_host_zone_defers_delivery_and_preserves_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = QueueState(pending=[entry()])
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TZ", "Not/A_Zone")
            assert adjust_lastfm_dates(state, "volume", ACCOUNT, NOW) == 1
            assert state.pending == [entry()]
    finally:
        refresh_host_timezone()


@pytest.mark.parametrize(
    "zone,now,count,expected_deferred,earliest",
    [
        # First valid instant after a skipped midnight is 01:00 local.
        (
            "America/Sao_Paulo",
            Instant.from_utc(2018, 11, 4, 3),
            2,
            1,
            Instant.from_utc(2018, 11, 4, 3),
        ),
        # At the second midnight, the earlier 00:00 is already an hour old.
        (
            "America/Havana",
            Instant.from_utc(2020, 11, 1, 5),
            3602,
            1,
            Instant.from_utc(2020, 11, 1, 4),
        ),
    ],
)
def test_local_midnight_gap_and_fold_use_explicit_best_effort_policy(
    monkeypatch: pytest.MonkeyPatch,
    zone: str,
    now: Instant,
    count: int,
    expected_deferred: int,
    earliest: Instant,
) -> None:
    monkeypatch.setattr("iOpenPod.app.scrobbling.timestamps.SYSTEM_TZ", zone)
    old = [
        entry(str(index), timestamp=now.timestamp() - 30 * 86400)
        for index in range(count)
    ]
    state = QueueState(pending=old)
    assert (
        adjust_lastfm_dates(state, "volume", ACCOUNT, now.timestamp())
        == expected_deferred
    )
    assigned = [
        item.submission_timestamp
        for item in state.pending
        if item.submission_timestamp is not None
    ]
    assert min(assigned) == earliest.timestamp()
    assert max(assigned) == now.timestamp()
    assert [item.listen for item in state.pending] == [item.listen for item in old]


@pytest.mark.parametrize("value", [None, True, "unknown"])
def test_missing_or_malformed_queue_date_retains_cursors_and_identity(
    tmp_path: Path, value: object
) -> None:
    path = tmp_path / "queue.json"
    queue = ScrobbleQueue(AtomicHostFile(path))
    queue.save(QueueState({"ordinal": 39}, [entry()]))
    document = json.loads(path.read_bytes())
    if value is None:
        del document["pending"][0]["listen"]["timestamp"]
    else:
        document["pending"][0]["listen"]["timestamp"] = value
    raw = json.dumps(document).encode()
    path.write_bytes(raw)
    state = queue.load()
    assert path.read_bytes() == raw
    assert state.cursors == {"ordinal": 39}
    assert state.pending[0].identity == entry().identity
    assert state.pending[0].listen.timestamp == 0
