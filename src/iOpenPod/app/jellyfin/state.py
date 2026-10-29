"""Per-song baselines and the merge rule; the Host store is read only to migrate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from storage import HostResourceLease

from ._json import integer, is_object, text
from .models import MAX_PLAY_COUNT, JellyfinError

if TYPE_CHECKING:
    from storage import AtomicHostFile

MAX_PAIRS = 500_000


@dataclass(frozen=True, slots=True)
class PairState:
    """What both sides held after the last reconciliation of one song.

    ``agreed`` is the merged total. ``ipod_seen`` and ``jellyfin_seen`` are the
    counts last confirmed on each side; plays above them are new. ``pending``
    marks an iPod save that started but was never confirmed, so the next run
    cannot tell whether it landed and merges conservatively.
    """

    item_id: str
    agreed: int
    ipod_seen: int
    jellyfin_seen: int
    pending: bool = False


@dataclass(slots=True)
class PlayCountState:
    pairs: dict[str, PairState] = field(default_factory=dict[str, PairState])


def pair_key(account: str, device: str, db_track_id: int) -> str:
    return hashlib.sha256(
        json.dumps([account, device, db_track_id]).encode()
    ).hexdigest()


def merged_count(previous: PairState | None, ipod: int, jellyfin: int) -> int:
    """Add plays made on either side since the last reconciliation.

    Without a trustworthy baseline the larger count wins, which can lose plays
    made on both sides but never counts one play twice. Decreases are not
    propagated; the merged value is restored to the side that went down.
    """
    if previous is None or previous.pending:
        return max(ipod, jellyfin)
    merged = (
        previous.agreed
        + max(0, ipod - previous.ipod_seen)
        + max(0, jellyfin - previous.jellyfin_seen)
    )
    return max(merged, ipod, jellyfin)


class PlayCountStore:
    def __init__(self, host_file: AtomicHostFile) -> None:
        self.host_file = host_file

    def lease(self) -> HostResourceLease:
        return HostResourceLease(
            f"jellyfin-play-counts:{self.host_file.path.absolute()}"
        )

    def load(self) -> PlayCountState:
        try:
            raw = self.host_file.read_bytes()
            if raw is None:
                return PlayCountState()
            data: object = json.loads(raw)
            if not is_object(data) or integer(data.get("version")) != 1:
                raise ValueError
            raw_pairs = data["pairs"]
            if not is_object(raw_pairs) or len(raw_pairs) > MAX_PAIRS:
                raise ValueError
            pairs: dict[str, PairState] = {}
            for key, item in raw_pairs.items():
                if not is_object(item) or set(item) != {
                    "item_id",
                    "agreed",
                    "ipod_seen",
                    "jellyfin_seen",
                    "pending",
                }:
                    raise ValueError
                pending = item["pending"]
                if not isinstance(pending, bool):
                    raise ValueError
                pair = PairState(
                    text(item["item_id"]),
                    integer(item["agreed"]),
                    integer(item["ipod_seen"]),
                    integer(item["jellyfin_seen"]),
                    pending,
                )
                if (
                    not pair.item_id
                    or not 0 <= pair.ipod_seen <= pair.agreed <= MAX_PLAY_COUNT
                    or not 0 <= pair.jellyfin_seen <= pair.agreed
                ):
                    raise ValueError
                pairs[key] = pair
            return PlayCountState(pairs)
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise JellyfinError(
                "The saved Jellyfin play count state is unreadable. It was preserved; restore it before syncing to avoid counting plays twice."
            ) from None

    def save(self, state: PlayCountState) -> None:
        self.host_file.replace_bytes(
            json.dumps(
                {
                    "version": 1,
                    "pairs": {key: asdict(pair) for key, pair in state.pairs.items()},
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )
