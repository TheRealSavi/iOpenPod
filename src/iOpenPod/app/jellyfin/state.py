"""Per-song reconciliation baselines and the play count merge rule."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PairState:
    """What both sides held after the last reconciliation of one song.

    ``agreed`` is the merged total. ``ipod_seen`` and ``jellyfin_seen`` are the
    counts last confirmed on each side; plays above them are new.
    """

    item_id: str
    agreed: int
    ipod_seen: int
    jellyfin_seen: int


def merged_count(previous: PairState | None, ipod: int, jellyfin: int) -> int:
    """Add plays made on either side since the last reconciliation.

    Without a baseline the larger count wins, which can lose plays made on both
    sides but never counts one play twice. Decreases are not propagated; the
    merged value is restored to the side that went down.
    """
    if previous is None:
        return max(ipod, jellyfin)
    merged = (
        previous.agreed
        + max(0, ipod - previous.ipod_seen)
        + max(0, jellyfin - previous.jellyfin_seen)
    )
    return max(merged, ipod, jellyfin)
