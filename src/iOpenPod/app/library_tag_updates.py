"""Derive retained-file tag work from ordinary Library edits."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from iOpenPod.app.artwork_policy import (
    application_artwork_read_formats,
    rockbox_artwork,
)
from iOpenPod.app.library_write import RockboxMediaUpdate
from iOpenPod.app.sync_track_details import track_tag_values
from iPodDB.library import ArtworkGroupReference, TimedArtworkAsset

if TYPE_CHECKING:
    from iOpenPod.app.library_write import LibraryPreparationRequest
    from iPodDB.library import ArtworkPixels, IPodLibrary


def with_rockbox_edits(
    request: LibraryPreparationRequest, source: IPodLibrary
) -> LibraryPreparationRequest:
    """Capture changed tags and covers without reading or rewriting unchanged media.

    Sync supplies explicit updates, including policy-only changes. Ordinary edits
    derive the same intent from the retained Library and the reviewed snapshot.
    Existing covers stay embedded unless the artwork assignment changed.
    """
    if not request.rockbox_metadata:
        return request
    originals = {track.track_id: track for track in request.source.library.tracks}
    explicit = {update.track_id for update in request.rockbox_media}
    incoming = {item.media.track_id for item in request.media}
    excluded = explicit | incoming | set(request.replace_media)
    assets = {asset.artwork_id: asset for asset in request.artwork}
    embedded: dict[int, ArtworkPixels] = {}
    profile = request.source.profile
    updates = list(request.rockbox_media)
    for track in request.snapshot.tracks:
        original = originals.get(track.track_id)
        if (
            original is None
            or track.track_id in excluded
            or track.metadata.location != original.metadata.location
        ):
            continue
        artwork_changed = track.artwork_id != original.artwork_id
        asset = assets.get(track.artwork_id)
        cover_source = None
        if asset is not None:
            if isinstance(asset, TimedArtworkAsset):
                cover = next(
                    (frame for frame in asset.frames if frame.display_time_ms == 0),
                    None,
                )
                if cover is None:
                    raise ValueError(
                        "An artwork sequence requires a cover at time zero."
                    )
                cover_source = cover.source
            else:
                cover_source = asset.pixels
        if (
            artwork_changed
            and isinstance(cover_source, ArtworkGroupReference)
            and cover_source.artwork_id == original.artwork_id
            and cover_source.display_time_ms == 0
        ):
            # Changing later artwork does not change the file's embedded cover.
            artwork_changed = False
        if not artwork_changed and track_tag_values(track) == track_tag_values(
            original
        ):
            continue
        pixels = None
        read = None
        if artwork_changed and track.artwork_id:
            if isinstance(cover_source, ArtworkGroupReference):
                read = source.artwork_read(
                    cover_source.artwork_id,
                    application_artwork_read_formats(profile),
                    4096,
                    display_time_ms=cover_source.display_time_ms,
                )
                if read is None:
                    raise ValueError(
                        "The selected artwork cannot be embedded in this Track."
                    )
            elif cover_source is not None:
                if track.artwork_id not in embedded:
                    embedded[track.artwork_id] = rockbox_artwork(profile, cover_source)
                pixels = embedded[track.artwork_id]
            else:
                read = source.artwork_read(
                    track.artwork_id, application_artwork_read_formats(profile), 4096
                )
                if read is None:
                    raise ValueError(
                        "The selected artwork cannot be embedded in this Track."
                    )
        updates.append(
            RockboxMediaUpdate(
                track.track_id,
                pixels,
                preserve_artwork=not artwork_changed,
                artwork_read=read,
            )
        )
    return replace(request, rockbox_media=tuple(updates))
