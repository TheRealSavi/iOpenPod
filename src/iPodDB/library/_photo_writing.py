"""Reconcile supported Photo Library edits over one retained PhotosDB document."""

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from iPodDB.library._document_edit import rebuild
from iPodDB.library.photos import (
    Photo,
    PhotoAlbum,
    PhotoLibrary,
    PhotoRepresentationKind,
)
from iPodDB.library.writing import WriteTarget
from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_auxiliary_mhod,
    new_container_mhod,
    new_photos_chunk,
    new_PhotosDB,
    new_string_mhod,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhba import DEFINITION as MHBA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhif import DEFINITION as MHIF_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.PhotosDB.shared.constants import PhotosDatasetType, PhotosMhodType
from iPodDB.shared.chunk import ChunkHeader, DatabaseDocument, ParsedChunk


def reconcile_photos(
    document: DatabaseDocument[MhfdHeader] | None,
    original: PhotoLibrary | None,
    desired: PhotoLibrary,
    persistent_track_ids: Mapping[int, int],
    target: WriteTarget,
) -> DatabaseDocument[MhfdHeader]:
    """Apply only the Photo edits admitted by analysis to retained Chunks."""

    if document is None:
        if target.photos_root_value is None:
            raise ValueError(
                "Creating PhotosDB requires the Device Profile's explicit root policy."
            )
        document = new_PhotosDB(
            next_mhii_id=100, unk_mhfd_0x10=target.photos_root_value
        )
    original = original or PhotoLibrary()
    previous_photos = {photo.photo_id: photo for photo in original.photos}
    wanted_photos = {photo.photo_id: photo for photo in desired.photos}
    previous_albums = {album.album_id: album for album in original.albums}
    wanted_albums = {album.album_id: album for album in desired.albums}
    replacements: dict[int, ParsedChunk[ChunkHeader] | None] = {}

    for image_selection in document.find_chunks(MhiiHeader):
        photo_id = image_selection.chunk.header.image_id
        prior = previous_photos[photo_id]
        wanted = wanted_photos.get(photo_id)
        if wanted is None:
            replacements[id(image_selection.chunk)] = None
        elif wanted != prior:
            replacements[id(image_selection.chunk)] = replace(
                image_selection.chunk,
                header=replace(
                    image_selection.chunk.header,
                    rating=wanted.rating,
                    original_date=wanted.original_date,
                    exif_taken_date=wanted.taken_date,
                    source_image_size=wanted.source_size_bytes,
                ),
                children=(
                    _photo_representations(wanted)
                    + tuple(
                        child
                        for child in image_selection.chunk.children
                        if not isinstance(child.header, MhodHeader)
                        or child.header.mhod_type
                        not in (
                            PhotosMhodType.THUMBNAIL_IMAGE,
                            PhotosMhodType.FULL_RES_IMAGE,
                        )
                    )
                    if wanted.representations != prior.representations
                    else image_selection.chunk.children
                ),
            )

    photo_additions = tuple(
        photo for photo in desired.photos if photo.photo_id not in previous_photos
    )
    if photo_additions:
        image_dataset = next(
            selection
            for selection in document.find_chunks(MhsdHeader)
            if selection.chunk.header.dataset_type == PhotosDatasetType.IMAGE_LIST
        )
        container = rebuild(image_dataset.chunk.children[0], replacements)
        for photo in photo_additions:
            container = container.append_child(
                new_photos_chunk(
                    MHII_DEFINITION,
                    MhiiHeader(
                        image_id=photo.photo_id,
                        rating=photo.rating,
                        original_date=photo.original_date,
                        exif_taken_date=photo.taken_date,
                        source_image_size=photo.source_size_bytes,
                    ),
                    children=(*_photo_representations(photo), new_auxiliary_mhod()),
                )
            )
        replacements[id(image_dataset.chunk)] = replace(
            image_dataset.chunk, children=(container, *image_dataset.chunk.children[1:])
        )

    known_formats = {item.format_id for item in original.formats}
    format_additions = tuple(
        item for item in desired.formats if item.format_id not in known_formats
    )
    if format_additions:
        file_dataset = next(
            selection
            for selection in document.find_chunks(MhsdHeader)
            if selection.chunk.header.dataset_type == PhotosDatasetType.FILE_LIST
        )
        container = file_dataset.chunk.children[0]
        for item in format_additions:
            container = container.append_child(
                new_photos_chunk(
                    MHIF_DEFINITION,
                    MhifHeader(
                        format_id=item.format_id, image_size=item.image_size_bytes
                    ),
                )
            )
        replacements[id(file_dataset.chunk)] = replace(
            file_dataset.chunk, children=(container, *file_dataset.chunk.children[1:])
        )

    for album_selection in document.find_chunks(MhbaHeader):
        album_id = album_selection.chunk.header.album_id
        prior_album = previous_albums[album_id]
        wanted_album = wanted_albums.get(album_id)
        if wanted_album is None:
            replacements[id(album_selection.chunk)] = None
        elif wanted_album != prior_album:
            replacements[id(album_selection.chunk)] = cast(
                "ParsedChunk[ChunkHeader]",
                _edit_album(
                    album_selection.chunk,
                    prior_album,
                    wanted_album,
                    persistent_track_ids,
                ),
            )

    additions = tuple(
        album for album in desired.albums if album.album_id not in previous_albums
    )
    if additions:
        album_dataset = next(
            selection
            for selection in document.find_chunks(MhsdHeader)
            if selection.chunk.header.dataset_type == PhotosDatasetType.PHOTO_ALBUM_LIST
        )
        container = rebuild(album_dataset.chunk.children[0], replacements)
        for album in additions:
            container = container.append_child(_new_album(album, persistent_track_ids))
        replacements[id(album_dataset.chunk)] = replace(
            album_dataset.chunk,
            children=(container, *album_dataset.chunk.children[1:]),
        )

    result = rebuild(document, replacements)
    if photo_additions:
        next_identity = (
            max((photo.photo_id for photo in desired.photos), default=99)
            + len(desired.albums)
            + 1
        )
        if next_identity > 0xFFFFFFFF:
            raise ValueError("The Photo identity space is exhausted.")
        result = replace(
            result,
            header=replace(
                result.header,
                next_mhii_id=max(result.header.next_mhii_id, next_identity),
            ),
        )
    return result


def _photo_representations(photo: Photo) -> tuple[ParsedChunk[ChunkHeader], ...]:
    return tuple(
        new_container_mhod(
            PhotosMhodType.FULL_RES_IMAGE
            if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
            else PhotosMhodType.THUMBNAIL_IMAGE,
            new_photos_chunk(
                MHNI_DEFINITION,
                MhniHeader(
                    format_id=representation.format_id,
                    ithmb_offset=representation.offset,
                    image_size=representation.size_bytes,
                    image_size_2=representation.size_bytes,
                    image_width=representation.width,
                    image_height=representation.height,
                    horizontal_padding=representation.horizontal_padding,
                    vertical_padding=representation.vertical_padding,
                ),
                children=(
                    new_string_mhod(
                        PhotosMhodType.FILE_NAME,
                        ":"
                        + representation.relative_path.removeprefix("Photos/").replace(
                            "/", ":"
                        ),
                    ),
                ),
            ),
        )
        for representation in photo.representations
    )


def _new_album(
    album: PhotoAlbum,
    persistent_track_ids: Mapping[int, int],
) -> ParsedChunk[MhbaHeader]:
    details = album.ipod
    if details is None:
        raise ValueError("A new Photo Album requires iPod creation details.")
    music_db_track_id = (
        0
        if album.music_track_id is None
        else persistent_track_ids[album.music_track_id]
    )
    return new_photos_chunk(
        MHBA_DEFINITION,
        MhbaHeader(
            album_id=album.album_id,
            album_type=details.album_type,
            play_music=int(album.play_music),
            repeat=int(album.repeat),
            random=int(album.random),
            show_titles=int(album.show_titles),
            transition_direction=details.transition_direction,
            slide_duration=album.slide_duration_ms,
            transition_duration=album.transition_duration_ms,
            db_track_id_ref=music_db_track_id,
            previous_album_id=details.previous_album_id,
        ),
        children=(
            new_string_mhod(PhotosMhodType.ALBUM_NAME, album.name),
            *(
                cast(
                    "ParsedChunk[ChunkHeader]",
                    new_photos_chunk(
                        MHIA_DEFINITION,
                        MhiaHeader(image_id=photo_id),
                    ),
                )
                for photo_id in album.photo_ids
            ),
        ),
    )


def _edit_album(
    chunk: ParsedChunk[MhbaHeader],
    original: PhotoAlbum,
    desired: PhotoAlbum,
    persistent_track_ids: Mapping[int, int],
) -> ParsedChunk[MhbaHeader]:
    music_db_track_id = chunk.header.db_track_id_ref
    if desired.music_track_id != original.music_track_id:
        music_db_track_id = (
            0
            if desired.music_track_id is None
            else persistent_track_ids[desired.music_track_id]
        )
    header = replace(
        chunk.header,
        play_music=int(desired.play_music),
        repeat=int(desired.repeat),
        random=int(desired.random),
        show_titles=int(desired.show_titles),
        slide_duration=desired.slide_duration_ms,
        transition_duration=desired.transition_duration_ms,
        db_track_id_ref=music_db_track_id,
    )
    children = chunk.children
    if desired.name != original.name:
        children = _replace_album_name(children, desired.name)
    if desired.photo_ids != original.photo_ids:
        children = _replace_membership(children, desired.photo_ids)
    return replace(chunk, header=header, children=children)


def _replace_album_name(
    children: tuple[ParsedChunk[ChunkHeader], ...],
    name: str,
) -> tuple[ParsedChunk[ChunkHeader], ...]:
    result = list(children)
    for index, child in enumerate(result):
        if (
            isinstance(child.header, MhodHeader)
            and isinstance(child.payload, MhodStringPayload)
            and child.header.mhod_type
            in (
                PhotosMhodType.ALBUM_NAME,
                PhotosMhodType.THUMBNAIL_IMAGE,
            )
        ):
            result[index] = child.edit_payload(
                MhodStringPayload,
                lambda payload: replace(payload, value=name),
            )
            return tuple(result)
    first_membership = next(
        (
            index
            for index, child in enumerate(result)
            if isinstance(child.header, MhiaHeader)
        ),
        len(result),
    )
    result.insert(
        first_membership,
        new_string_mhod(PhotosMhodType.ALBUM_NAME, name),
    )
    return tuple(result)


def _replace_membership(
    children: tuple[ParsedChunk[ChunkHeader], ...],
    photo_ids: tuple[int, ...],
) -> tuple[ParsedChunk[ChunkHeader], ...]:
    retained: defaultdict[int, deque[ParsedChunk[ChunkHeader]]] = defaultdict(deque)
    metadata: list[ParsedChunk[ChunkHeader]] = []
    for child in children:
        if isinstance(child.header, MhiaHeader):
            retained[child.header.image_id].append(child)
        else:
            metadata.append(child)
    membership = tuple(
        retained[photo_id].popleft()
        if retained[photo_id]
        else cast(
            "ParsedChunk[ChunkHeader]",
            new_photos_chunk(MHIA_DEFINITION, MhiaHeader(image_id=photo_id)),
        )
        for photo_id in photo_ids
    )
    return (*metadata, *membership)


__all__ = ["reconcile_photos"]
