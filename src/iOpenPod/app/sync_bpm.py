"""Fill missing Track BPM from the shared music analysis results."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from iPodDB.library import MediaKind, is_video_track

if TYPE_CHECKING:
    from collections.abc import Mapping

    from iOpenPod.app.genius_audio import GeniusAudioProfile
    from iPodDB.library import LibrarySnapshot, Track


def with_missing_bpm(
    snapshot: LibrarySnapshot,
    original: LibrarySnapshot,
    profiles: Mapping[int, GeniusAudioProfile],
) -> LibrarySnapshot:
    """Keep supplied or existing BPM; use measured tempo only for missing values."""
    previous = {track.track_id: track.metadata.bpm for track in original.tracks}
    tracks: list[Track] = []
    for track in snapshot.tracks:
        if (
            track.metadata.bpm == 0
            and track.media_kind is MediaKind.MUSIC
            and not track.metadata.podcast
            and not is_video_track(track)
        ):
            bpm = previous.get(track.track_id, 0)
            profile = profiles.get(track.track_id)
            if bpm == 0 and profile is not None:
                tempo = profile.body[0]
                if math.isfinite(tempo) and 0.5 <= tempo < 65535.5:
                    bpm = math.floor(tempo + 0.5)
            if bpm:
                track = replace(track, metadata=replace(track.metadata, bpm=bpm))
        tracks.append(track)
    return replace(snapshot, tracks=tuple(tracks))
