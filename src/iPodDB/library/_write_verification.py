"""Checks over reparsed artifacts, independent of the reconciliation edits."""

from collections import defaultdict

from iPodDB.ArtworkDB.shared.artwork_index import ArtworkIndex
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader as ArtworkDataset
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.library._artwork_writing import artwork_path
from iPodDB.library.file_content import content_sha256
from iPodDB.library.writing import PreparedFile, RetainedArtworkFile, WriteResources
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def retained_artwork(index: ArtworkIndex) -> tuple[RetainedArtworkFile, ...]:
    files: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for item in index.items:
        for location in item.locations:
            files[location.file_name].add((location.offset, location.byte_length))
    return tuple(
        RetainedArtworkFile(name, tuple(sorted(ranges)))
        for name, ranges in files.items()
    )


def _bytes(chunk: ParsedChunk[ChunkHeader], data: bytes) -> bytes:
    return data[
        chunk.offset : chunk.offset + chunk.generic_header.length_or_child_count
    ]


def verify_relationships(
    original: DatabaseDocument[MhbdHeader],
    checked: DatabaseDocument[MhbdHeader],
    original_bytes: bytes,
    output_bytes: bytes,
    old_artwork: DatabaseDocument[MhfdHeader] | None,
    new_artwork: DatabaseDocument[MhfdHeader] | None,
    original_artwork_bytes: bytes | None,
    output_artwork_bytes: bytes | None,
    old_index: ArtworkIndex,
    new_index: ArtworkIndex,
    artwork_files: tuple[PreparedFile, ...],
    resources: WriteResources,
    changed_artwork_ids: set[int],
) -> None:
    def dangling(document: DatabaseDocument[MhbdHeader]) -> set[tuple[int, int]]:
        tracks = {s.chunk.header.track_id for s in document.find_chunks(MhitHeader)}
        return {
            (s.chunk.header.track_id, s.chunk.header.track_persistent_id)
            for s in document.find_chunks(MhipHeader)
            if not s.chunk.header.podcast_group_flag & 0x100
            and s.chunk.header.track_id not in tracks
        }

    if dangling(checked) - dangling(original):
        raise ValueError("Verification found newly dangling Playlist Track references.")
    original_unknown = [
        _bytes(s.chunk, original_bytes)
        for s in original.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type not in (1, 2, 3, 4, 5, 8)
    ]
    output_unknown = [
        _bytes(s.chunk, output_bytes)
        for s in checked.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type not in (1, 2, 3, 4, 5, 8)
    ]
    if original_unknown != output_unknown:
        raise ValueError("Verification found a changed unrelated iTunesDB dataset.")
    if old_artwork and new_artwork and original_artwork_bytes and output_artwork_bytes:
        old_photos = [
            _bytes(s.chunk, original_artwork_bytes)
            for s in old_artwork.find_chunks(ArtworkDataset)
            if s.chunk.header.dataset_type not in (1, 3)
        ]
        new_photos = [
            _bytes(s.chunk, output_artwork_bytes)
            for s in new_artwork.find_chunks(ArtworkDataset)
            if s.chunk.header.dataset_type not in (1, 3)
        ]
        if old_photos != new_photos:
            raise ValueError(
                "Verification found changed photo data or unrelated ArtworkDB datasets."
            )
    old_ids = {item.image_id for item in old_index.items}
    new_ids = {item.image_id for item in new_index.items}
    if not old_ids <= new_ids:
        raise ValueError("Verification found deleted retained artwork records.")
    for original_item in old_index.items:
        retained = new_index.item_for_image_id(original_item.image_id)
        assert retained is not None
        if (
            retained.locations != original_item.locations
            or retained.source_image_size != original_item.source_image_size
        ):
            raise ValueError(
                f"Verification found changed retained artwork ranges or image size: {original_item.image_id}"
            )
    output_files = {f.relative_path.casefold(): f.data for f in artwork_files}
    if len(output_files) != len(artwork_files):
        raise ValueError("Verification found duplicate artwork output paths.")
    inventory = {f.relative_path.casefold(): f for f in resources.file_inventory or ()}
    if output_files:
        if resources.file_inventory is None:
            raise ValueError(
                "Artwork output verification requires the captured file inventory."
            )
        old_paths = {
            artwork_path(location.file_name).casefold()
            for item in old_index.items
            for location in item.locations
        }
        for path, file_data in output_files.items():
            original_file = inventory.get(path)
            if original_file is None:
                if path in old_paths:
                    raise ValueError(
                        f"Artwork output would overwrite an uncaptured retained file: {path}"
                    )
                continue
            if (
                len(file_data) < original_file.size
                or content_sha256(file_data, length=original_file.size)
                != original_file.sha256
            ):
                raise ValueError(
                    f"Verification found changed retained artwork file bytes: {path}"
                )
    for item in new_index.items:
        if item.image_id not in changed_artwork_ids:
            continue
        if not item.locations:
            raise ValueError("Changed artwork has no usable image ranges.")
        for location in item.locations:
            path = artwork_path(location.file_name).casefold()
            data = output_files.get(path)
            source = inventory.get(path)
            length = len(data) if data is not None else source.size if source else None
            if length is None or location.offset + location.byte_length > length:
                raise ValueError(
                    "Changed artwork references a missing or out-of-bounds image range."
                )
