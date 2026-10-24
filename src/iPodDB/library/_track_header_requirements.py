"""Plan native fields supplied after ordinary Track metadata reconciliation."""

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.library._artist_groups import shared_artist_changes
from iPodDB.library._browse_groups import album_values, native_browse_groups
from iPodDB.library._track_header_expansion import optional_field_available
from iPodDB.library.models import LibrarySnapshot
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_field import ChunkFieldValue


def derived_header_requirements(
    document: DatabaseDocument[MhbdHeader],
    before: LibrarySnapshot,
    desired: LibrarySnapshot,
    database_version: int | None,
    artwork_tracks: tuple[int, ...] = (),
) -> dict[int, dict[str, ChunkFieldValue]]:
    """Derive required extents from source and intent, never allocated IDs.

    Nonzero placeholders require the complete field without predicting identity
    allocation. Composer text works without a native ID on older layouts. Album
    and artist references are required only when their retained datasets change.
    Artwork can use reverse links, so its optional direct link never forces growth.
    """
    previous = {t.track_id: t for t in before.tracks}
    source = {
        s.chunk.header.track_id: s.chunk for s in document.find_chunks(MhitHeader)
    }
    requirements: dict[int, dict[str, ChunkFieldValue]] = {}

    def require(identity: int, field: str) -> None:
        requirements.setdefault(identity, {})[field] = 1

    artwork = set(artwork_tracks)
    for track in desired.tracks:
        old = previous.get(track.track_id)
        if (
            track.metadata.composer
            and (old is None or old.metadata.composer != track.metadata.composer)
            and optional_field_available(
                source.get(track.track_id), "composer_id", database_version
            )
        ):
            require(track.track_id, "composer_id")
        if track.artwork_id and (
            old is None
            or old.artwork_id != track.artwork_id
            or track.track_id in artwork
        ):
            require(track.track_id, "has_artwork")

    kinds = {s.chunk.header.dataset_type for s in document.find_chunks(MhsdHeader)}
    artist_changes = shared_artist_changes(before.tracks, desired.tracks)
    for kind, field in ((4, "album_id"), (8, "artist_id_ref")):
        if kind not in kinds:
            continue
        album = kind == 4
        prior_groups = native_browse_groups(before.tracks, album=album)
        for key, members in native_browse_groups(desired.tracks, album=album).items():
            prior = prior_groups.get(key, ())
            if (
                {t.track_id for t in prior} != {t.track_id for t in members}
                or (
                    album
                    and bool(prior)
                    and album_values(prior) != album_values(members)
                )
                or (not album and members[0].artist in artist_changes)
            ):
                for track in members:
                    require(track.track_id, field)
    return requirements
