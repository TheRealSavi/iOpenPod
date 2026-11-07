"""Pure firmware sidecar formats, without Library projection or filesystem I/O."""

from iPodDB.sidecars.codec import (
    MAX_SIDECAR_BYTES,
    genius_playlist_number,
    is_playback_sidecar,
    otg_number,
    parse_itunes_stats,
    parse_otg_playlist,
    parse_play_counts,
    parse_play_counts_plist,
    parse_playback,
    parse_positional_sidecar,
)
from iPodDB.sidecars.genius import (
    GeniusPlaylist,
    GeniusPlaylistDocument,
    create_genius_playlist,
    parse_genius_playlist,
    remap_genius_playlist,
    validate_genius_playlist_tracks,
    write_genius_playlist,
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
    "GeniusPlaylist",
    "GeniusPlaylistDocument",
    "OTGPlaylistDocument",
    "PlaybackDateKind",
    "PlaybackDocument",
    "PlaybackEntry",
    "PlaybackSidecar",
    "PositionalSidecar",
    "create_genius_playlist",
    "genius_playlist_number",
    "is_playback_sidecar",
    "otg_number",
    "parse_genius_playlist",
    "parse_itunes_stats",
    "parse_otg_playlist",
    "parse_play_counts",
    "parse_play_counts_plist",
    "parse_playback",
    "parse_positional_sidecar",
    "remap_genius_playlist",
    "remap_playback_sidecar",
    "validate_genius_playlist_tracks",
    "write_genius_playlist",
]
