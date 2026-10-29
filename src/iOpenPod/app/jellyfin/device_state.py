"""The play count memory kept on the iPod, so every Host merges from it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

from storage import DevicePath, FileContent, TransactionWrite

from ._json import integer, is_object, text
from .models import MAX_PLAY_COUNT, JellyfinError
from .state import PairState

if TYPE_CHECKING:
    from storage import FileFingerprint

PLAY_COUNTS_PATH = DevicePath(
    "iPod_Control/iOpenPod/Integrations/jellyfin-play-counts-v1.json"
)
MAX_DOCUMENT = 8 * 1024 * 1024
_MAX_TRACK_ID = 1 << 64


@dataclass(slots=True)
class DevicePlayCounts:
    """Per Jellyfin account, the last reconciliation of each iPod Track.

    The document lives on the iPod it describes, so it needs no device key.
    Tracks are keyed by their persistent iPod ID, which survives Library saves.
    """

    accounts: dict[str, dict[int, PairState]] = field(
        default_factory=dict[str, dict[int, PairState]]
    )


def encode_play_counts(state: DevicePlayCounts) -> bytes:
    data = json.dumps(
        {
            "version": 1,
            "accounts": {
                account: {
                    str(track_id): {
                        "item": pair.item_id,
                        "agreed": pair.agreed,
                        "ipod": pair.ipod_seen,
                        "jellyfin": pair.jellyfin_seen,
                    }
                    for track_id, pair in pairs.items()
                }
                for account, pairs in state.accounts.items()
                if pairs
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(data) > MAX_DOCUMENT:
        raise JellyfinError("The play count memory is too large to store on the iPod.")
    return data


def decode_play_counts(data: bytes) -> DevicePlayCounts:
    """Validate the document completely; a partial read would miscount plays."""
    try:
        document: object = json.loads(data)
        if not is_object(document) or integer(document.get("version")) != 1:
            raise ValueError
        raw_accounts = document["accounts"]
        if not is_object(raw_accounts):
            raise ValueError
        accounts: dict[str, dict[int, PairState]] = {}
        for account, raw_pairs in raw_accounts.items():
            if not account or not is_object(raw_pairs):
                raise ValueError
            pairs: dict[int, PairState] = {}
            for key, item in raw_pairs.items():
                track_id = int(key)
                if str(track_id) != key or not 0 < track_id < _MAX_TRACK_ID:
                    raise ValueError
                if not is_object(item) or set(item) != {
                    "item",
                    "agreed",
                    "ipod",
                    "jellyfin",
                }:
                    raise ValueError
                pair = PairState(
                    text(item["item"]),
                    integer(item["agreed"]),
                    integer(item["ipod"]),
                    integer(item["jellyfin"]),
                )
                if (
                    not pair.item_id
                    or not 0 <= pair.ipod_seen <= pair.agreed <= MAX_PLAY_COUNT
                    or not 0 <= pair.jellyfin_seen <= pair.agreed
                ):
                    raise ValueError
                pairs[track_id] = pair
            accounts[account] = pairs
        return DevicePlayCounts(accounts)
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise JellyfinError(
            "The play count memory on the iPod is unreadable. It was preserved; "
            "restore it from a Backup Snapshot or remove "
            "iPod_Control/iOpenPod/Integrations/jellyfin-play-counts-v1.json to start over."
        ) from None


def play_counts_write(data: bytes, before: FileFingerprint | None) -> TransactionWrite:
    """Describe the document for the Library's recoverable Storage transaction."""
    return TransactionWrite(
        PLAY_COUNTS_PATH,
        data,
        FileContent(len(data), sha256(data).hexdigest()),
        before,
    )
