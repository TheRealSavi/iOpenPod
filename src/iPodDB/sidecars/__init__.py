"""Pure firmware sidecar formats, without Library projection or filesystem I/O."""

from iPodDB.sidecars.codec import (
    MAX_SIDECAR_BYTES,
    is_playback_sidecar,
    otg_number,
    parse_itunes_stats,
    parse_otg_playlist,
    parse_play_counts,
    parse_play_counts_plist,
    parse_playback,
    parse_positional_sidecar,
)
from iPodDB.sidecars.models import (
    OTGPlaylistDocument,
    PlaybackDateKind,
    PlaybackDocument,
    PlaybackEntry,
    PlaybackSidecar,
    PositionalSidecar,
)
from iPodDB.sidecars.remapping import remap_playback_sidecar

__all__ = [
    "MAX_SIDECAR_BYTES",
    "OTGPlaylistDocument",
    "PlaybackDateKind",
    "PlaybackDocument",
    "PlaybackEntry",
    "PlaybackSidecar",
    "PositionalSidecar",
    "is_playback_sidecar",
    "otg_number",
    "parse_itunes_stats",
    "parse_otg_playlist",
    "parse_play_counts",
    "parse_play_counts_plist",
    "parse_playback",
    "parse_positional_sidecar",
    "remap_playback_sidecar",
]
