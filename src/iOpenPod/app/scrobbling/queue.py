"""Durable Host outbox and capture cursors; iPod counters remain evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING

from iPodDB.library import MediaKind
from storage import HostResourceLease

from ._json import integer, is_array, is_object, text
from .models import Account, Listen, ScrobbleError, Service

if TYPE_CHECKING:
    from iPodDB.library import LibrarySnapshot
    from storage import AtomicHostFile

MAX_PENDING = 50_000
MIN_TIMESTAMP = 1_033_430_400


@dataclass(frozen=True, slots=True)
class PendingListen:
    identity: str
    device: str
    account: str
    listen: Listen
    submission_timestamp: int | None = None

    @property
    def submission(self) -> Listen:
        if self.submission_timestamp is None:
            return self.listen
        return replace(self.listen, timestamp=self.submission_timestamp)


@dataclass(slots=True)
class QueueState:
    cursors: dict[str, int] = field(default_factory=dict[str, int])
    pending: list[PendingListen] = field(default_factory=list[PendingListen])
    # Latest allocated second per account, including acknowledged submissions.
    lastfm_reserved_through: dict[str, int] = field(default_factory=dict[str, int])


class ScrobbleQueue:
    def __init__(self, host_file: AtomicHostFile) -> None:
        self.host_file = host_file

    def lease(self) -> HostResourceLease:
        return HostResourceLease(f"scrobbling:{self.host_file.path.absolute()}")

    def load(self) -> QueueState:
        try:
            raw = self.host_file.read_bytes()
            if raw is None:
                return QueueState()
            data: object = json.loads(raw)
            if not is_object(data) or integer(data.get("version")) not in (1, 2):
                raise ValueError
            version = integer(data["version"])
            raw_cursors, pending = data["cursors"], data["pending"]
            if not is_object(raw_cursors):
                raise ValueError
            cursors = {key: integer(value) for key, value in raw_cursors.items()}
            if any(value < 0 for value in cursors.values()):
                raise ValueError
            if not is_array(pending) or len(pending) > MAX_PENDING:
                raise ValueError
            entries: list[PendingListen] = []
            for item in pending:
                if not is_object(item):
                    raise ValueError
                identity = text(item["identity"])
                device = text(item["device"])
                account = text(item["account"])
                if not identity or not device or not account:
                    raise ValueError
                fields = item["listen"]
                if not is_object(fields) or set(fields) != {
                    "artist",
                    "title",
                    "album",
                    "timestamp",
                    "duration",
                    "album_artist",
                    "track_number",
                }:
                    raise ValueError
                listen = Listen(
                    artist=text(fields["artist"]),
                    title=text(fields["title"]),
                    album=text(fields["album"]),
                    timestamp=integer(fields["timestamp"]),
                    duration=integer(fields["duration"]),
                    album_artist=text(fields["album_artist"]),
                    track_number=integer(fields["track_number"]),
                )
                if (
                    listen.timestamp < MIN_TIMESTAMP
                    or listen.duration < 30
                    or not listen.artist.strip()
                    or not listen.title.strip()
                ):
                    raise ValueError
                adjusted = item.get("submission_timestamp") if version == 2 else None
                submission_timestamp = None if adjusted is None else integer(adjusted)
                if submission_timestamp is not None and (
                    not account.startswith(f"{Service.LASTFM.value}:")
                    or submission_timestamp < listen.timestamp
                ):
                    raise ValueError
                entries.append(
                    PendingListen(
                        identity, device, account, listen, submission_timestamp
                    )
                )
            if len({entry.identity for entry in entries}) != len(entries):
                raise ValueError
            reserved: dict[str, int] = {}
            if version == 2:
                raw_reserved = data["lastfm_reserved_through"]
                if not is_object(raw_reserved):
                    raise ValueError
                reserved = {key: integer(value) for key, value in raw_reserved.items()}
                if any(
                    not key.startswith(f"{Service.LASTFM.value}:")
                    or value < MIN_TIMESTAMP
                    for key, value in reserved.items()
                ):
                    raise ValueError
            return QueueState(cursors, entries, reserved)
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ScrobbleError(
                "The saved scrobble queue is unreadable. It was preserved; restore it before scrobbling to avoid duplicates."
            ) from None

    def save(self, state: QueueState) -> None:
        self.host_file.replace_bytes(
            json.dumps(
                {
                    "version": 2,
                    "cursors": state.cursors,
                    "pending": [asdict(item) for item in state.pending],
                    "lastfm_reserved_through": state.lastfm_reserved_through,
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )


def capture(
    state: QueueState,
    device: str,
    library: LibrarySnapshot,
    accounts: tuple[Account, ...],
    now: int,
) -> int:
    """Capture only newly observed plays, oldest first, without inventing dates."""
    skipped = 0
    for track in library.tracks:
        pending = track.metadata.unscrobbled_play_count
        if pending <= 0:
            continue
        duration = track.length_ms // 1000
        last_played = track.metadata.last_played
        if (
            track.media_kind not in (MediaKind.MUSIC, MediaKind.MUSIC_VIDEO)
            or track.length_ms <= 30_000
            or duration > 2_073_600
            or not track.artist.strip()
            or not track.title.strip()
            or last_played > now
            or last_played - duration < MIN_TIMESTAMP
            or track.ipod is None
            or track.ipod.db_track_id <= 0
        ):
            skipped += 1
            continue
        total = max(track.play_count, pending)
        baseline = total - pending
        for account in accounts:
            key = hashlib.sha256(
                json.dumps([device, track.ipod.db_track_id, account.identity]).encode()
            ).hexdigest()
            observed = max(baseline, state.cursors.get(key, baseline))
            if total <= observed:
                continue
            count = total - observed
            if count + len(state.pending) > MAX_PENDING:
                raise ScrobbleError(
                    "The scrobble queue is full. Submit pending listens before capturing more plays."
                )
            earliest = last_played - count * duration
            if earliest < MIN_TIMESTAMP:
                skipped += 1
                continue
            for ordinal in range(observed + 1, total + 1):
                timestamp = last_played - (total - ordinal + 1) * duration
                state.pending.append(
                    PendingListen(
                        f"{key}:{ordinal}",
                        device,
                        account.identity,
                        Listen(
                            track.artist.strip(),
                            track.title.strip(),
                            track.album,
                            timestamp,
                            duration,
                            track.album_artist,
                            track.track_number,
                        ),
                    )
                )
            state.cursors[key] = total
    state.pending.sort(key=lambda item: (item.listen.timestamp, item.identity))
    return skipped
