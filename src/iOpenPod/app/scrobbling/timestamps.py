"""Keep original playback evidence while adjusting old Last.fm delivery dates."""

from dataclasses import replace

from whenever import SYSTEM_TZ, Instant

from iOpenPod.app.core.dates import refresh_host_timezone

from .models import LASTFM_MAX_AGE, Account, Service
from .queue import QueueState


def adjust_lastfm_dates(
    state: QueueState, device: str, account: Account, now: int
) -> int:
    """Reserve distinct seconds today; return listens deferred until space exists."""
    if account.service is not Service.LASTFM:
        return 0
    old = sorted(
        (
            entry
            for entry in state.pending
            if entry.device == device
            and entry.account == account.identity
            and entry.submission.timestamp < now - LASTFM_MAX_AGE
        ),
        key=lambda entry: (entry.listen.timestamp, entry.identity),
    )
    if not old:
        return 0
    # Background delivery may run without a GUI activation since the Host zone
    # changed. Failure defers optional delivery without changing queued evidence.
    if not refresh_host_timezone():
        return len(old)
    # "Today" follows the Host's local calendar, while the wire format stays UTC.
    try:
        # A repeated midnight selects the earlier occurrence; a missing midnight
        # moves forward across the gap. This is Host delivery policy, not a
        # reconstruction of the iPod's historical city/DST setting (ADR-0240).
        today = (
            Instant.from_timestamp(now)
            .to_tz(SYSTEM_TZ)
            .to_plain()
            .start_of("day")
            .assume_tz(SYSTEM_TZ, disambiguation="compatible")
            .timestamp()
        )
    except (OverflowError, OSError, ValueError):
        # Keep queued listens for a later delivery without blocking Library Sync.
        return len(old)
    previous = state.lastfm_reserved_through.get(account.identity, today - 1)
    earliest = max(today, previous + 1)
    candidate = now
    occupied = {
        entry.submission.timestamp
        for entry in state.pending
        if entry.account == account.identity
    }
    dates: list[int] = []
    while candidate >= earliest and len(dates) < len(old):
        if candidate not in occupied:
            dates.append(candidate)
        candidate -= 1
    replacements = {
        entry.identity: replace(entry, submission_timestamp=timestamp)
        for entry, timestamp in zip(old, reversed(dates), strict=False)
    }
    if dates:
        state.lastfm_reserved_through[account.identity] = dates[0]
        state.pending = [
            replacements.get(entry.identity, entry) for entry in state.pending
        ]
    return len(old) - len(dates)
