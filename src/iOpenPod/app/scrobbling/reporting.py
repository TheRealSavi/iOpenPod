"""Readable per-Track rejection details shared by Sync and manual scrobbling."""

from datetime import UTC, datetime

from .models import LASTFM_MAX_AGE, Account, RejectedListen, Service
from .queue import PendingListen

_LASTFM_REASONS = {
    1: (
        "Listen ignored",
        "Last.fm documents code 1 as artist filtering, but this code alone does not establish that the artist metadata is wrong.",
    ),
    2: (
        "Track title ignored",
        "Last.fm filtered the submitted title. Check the title metadata below; retrying unchanged metadata may be rejected again.",
    ),
    3: (
        "Timestamp too old",
        "Last.fm rejected the submitted dates as too old. Dates outside the 14-day window are adjusted on the next attempt.",
    ),
    4: (
        "Timestamp too new",
        "Last.fm considers these playback dates too far in the future. Check the iPod clock and device time settings.",
    ),
    5: (
        "Daily scrobble limit reached",
        "Retry after Last.fm's daily limit resets.",
    ),
}


def single_line(value: str, limit: int = 500) -> str:
    """Keep service text and metadata from adding misleading report lines."""
    value = " ".join("".join(c if c.isprintable() else " " for c in value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _listens(count: int) -> str:
    return f"{count} listen" if count == 1 else f"{count} listens"


def _date(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return f"UNIX timestamp {timestamp} (outside the supported date range)"


def rejection_report(
    account: Account,
    rejections: list[RejectedListen],
    *,
    now: int | None = None,
    adjusted: bool = False,
) -> str:
    groups: dict[int, dict[tuple[str, str, str, str], list[int]]] = {}
    for rejection in rejections:
        listen = rejection.listen
        key = (listen.artist, listen.title, listen.album, rejection.message)
        groups.setdefault(rejection.code, {}).setdefault(key, []).append(
            listen.timestamp
        )
    lines = [
        f"{account.service.label} ({single_line(account.username)}): "
        f"{_listens(len(rejections))} rejected. Unaccepted listens remain pending."
    ]
    if account.service is Service.LASTFM and now is not None:
        old = sum(item.listen.timestamp < now - LASTFM_MAX_AGE for item in rejections)
        if old:
            lines.append(
                f"{_listens(old)} {'is' if old == 1 else 'are'} more than 14 days old, outside Last.fm's backdating window. "
                "Their Last.fm submission dates will be adjusted on the next attempt."
            )
    for code, tracks in sorted(groups.items()):
        reason, advice = (
            _LASTFM_REASONS.get(code, ("Listen rejected", ""))
            if account.service is Service.LASTFM
            else ("Listen rejected", "")
        )
        count = sum(len(dates) for dates in tracks.values())
        lines.append(f"{reason} (code {code}): {_listens(count)}.")
        if advice:
            lines.append(advice)
        unexplained = sum(
            len(dates) for (*_, message), dates in tracks.items() if not message
        )
        if unexplained:
            lines.append(
                f"The service supplied no further explanation for {_listens(unexplained)}."
            )
        for (artist, title, album, message), dates in tracks.items():
            lines.append(
                f'  • Artist: "{single_line(artist)}"; Title: "{single_line(title)}"; '
                f'Album: "{single_line(album)}"'
            )
            first, last = min(dates), max(dates)
            span = _date(first) if first == last else f"{_date(first)} to {_date(last)}"
            label = "submitted start" if adjusted else "estimated playback start"
            lines.append(f"    {_listens(len(dates))}; {label} (UTC): {span}.")
            if message:
                lines.append(f"    Service message: {single_line(message)}")
    return "\n".join(lines)


def adjustment_report(account: Account, entries: list[PendingListen]) -> str:
    groups: dict[tuple[str, str, str], list[PendingListen]] = {}
    for entry in entries:
        listen = entry.listen
        groups.setdefault((listen.artist, listen.title, listen.album), []).append(entry)
    lines = [
        f"{account.service.label} ({single_line(account.username)}): "
        f"{_listens(len(entries))} use adjusted submission dates because the original "
        "dates are outside the 14-day backdating window.",
        "Dates are moved to today when first adjusted and reused on retries while "
        "eligible. Original playback dates on the iPod and ListenBrainz submissions are unchanged.",
    ]
    for (artist, title, album), items in groups.items():
        lines.append(
            f'  • Artist: "{single_line(artist)}"; Title: "{single_line(title)}"; '
            f'Album: "{single_line(album)}" ({_listens(len(items))})'
        )
        for label, dates in (
            (
                "Original estimated playback start",
                [item.listen.timestamp for item in items],
            ),
            ("Last.fm submission start", [item.submission.timestamp for item in items]),
        ):
            first, last = min(dates), max(dates)
            span = _date(first) if first == last else f"{_date(first)} to {_date(last)}"
            lines.append(f"    {label} (UTC): {span}.")
    return "\n".join(lines)
