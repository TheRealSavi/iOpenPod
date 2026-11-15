"""Capture latest rating-feedback intent separately from play deliveries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.media.recording_id import recording_mbid
from iPodDB.library import MediaKind

from ._json import integer, is_array, is_object, text
from .models import ScrobbleError, Service

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from iPodDB.library import LibrarySnapshot, Track

    from .models import Account
    from .queue import QueueState

MAX_PENDING_FEEDBACK = 50_000


@dataclass(frozen=True, slots=True)
class RatingFeedback:
    """Observed rating range: -1 means Last.fm Unlove or ListenBrainz Hate."""

    identity: str
    device: str
    account: str
    artist: str
    title: str
    score: int
    recording_mbid: str = ""
    pending: bool = True


class FeedbackCancelledError(Exception):
    """Stop bounded metadata capture while retaining completed captures."""


def feedback_score(rating: int) -> int:
    if rating in (80, 100):
        return 1
    return -1 if rating in (20, 40) else 0


def load_feedback(value: object, *, lastfm: bool) -> dict[str, RatingFeedback]:
    """Reject damaged delivery state rather than silently replaying observations."""
    if not is_array(value):
        raise ValueError
    entries: dict[str, RatingFeedback] = {}
    for item in value:
        if not is_object(item):
            raise ValueError
        pending = item["pending"]
        if type(pending) is not bool:
            raise ValueError
        entry = RatingFeedback(
            text(item["identity"]),
            text(item["device"]),
            text(item["account"]),
            text(item["artist"]),
            text(item["title"]),
            integer(item["score"]),
            text(item["recording_mbid"]),
            pending,
        )
        service, _, username = entry.account.partition(":")
        if (
            not entry.identity
            or entry.identity in entries
            or not entry.device
            or service not in (Service.LASTFM, Service.LISTENBRAINZ)
            or (service == Service.LASTFM and (not lastfm or entry.recording_mbid))
            or not username.strip()
            or not entry.artist.strip()
            or not entry.title.strip()
            or entry.score not in (-1, 1)
            or (entry.recording_mbid and not recording_mbid(entry.recording_mbid))
        ):
            raise ValueError
        entries[entry.identity] = entry
    if sum(entry.pending for entry in entries.values()) > MAX_PENDING_FEEDBACK:
        raise ValueError
    return entries


def capture_feedback(
    state: QueueState,
    device: str,
    library: LibrarySnapshot,
    accounts: tuple[Account, ...],
    read_mbid: Callable[[Track], str],
    cancelled: Event,
) -> None:
    """Observe ratings even without plays; neutral values withdraw unsent intent."""
    if not accounts:
        return
    pending_count = sum(entry.pending for entry in state.feedback.values())
    for track in library.tracks:
        if cancelled.is_set():
            break
        if track.ipod is None or track.ipod.db_track_id <= 0:
            continue
        for account in accounts:
            key = hashlib.sha256(
                json.dumps([device, track.ipod.db_track_id, account.identity]).encode()
            ).hexdigest()
            previous = state.feedback.get(key)
            score = feedback_score(track.rating)
            if (
                not score
                or track.media_kind not in (MediaKind.MUSIC, MediaKind.MUSIC_VIDEO)
                or not track.artist.strip()
                or not track.title.strip()
            ):
                if previous is not None:
                    pending_count -= previous.pending
                    del state.feedback[key]
                continue
            if previous is not None and (
                previous.score,
                previous.artist,
                previous.title,
            ) == (score, track.artist.strip(), track.title.strip()):
                continue
            pending_count += 1 - (previous.pending if previous is not None else 0)
            if pending_count > MAX_PENDING_FEEDBACK:
                raise ScrobbleError(
                    "The rating feedback queue is full. Retry pending feedback before capturing more ratings."
                )
            try:
                mbid = (
                    read_mbid(track) if account.service is Service.LISTENBRAINZ else ""
                )
            except FeedbackCancelledError:
                return
            state.feedback[key] = RatingFeedback(
                key,
                device,
                account.identity,
                track.artist.strip(),
                track.title.strip(),
                score,
                recording_mbid(mbid),
            )
