"""Physical allocations remain reserved even when a thumbnail cannot display."""

from iPodDB.library._photo_extents import retained_photo_thumbnail_files
from iPodDB.PhotosDB.builder.build_PhotosDB import (
    new_container_mhod,
    new_photos_chunk,
    new_PhotosDB,
    new_string_mhod,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhni import DEFINITION as MHNI
from iPodDB.PhotosDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB


def test_retained_photo_thumbnail_files_preserve_optional_and_invalid_allocations() -> (
    None
):
    representations = (
        (
            PhotosMhodType.FULL_RES_IMAGE,
            1,
            0,
            400,
            400,
            (":Full Resolution:original.jpg",),
        ),
        (PhotosMhodType.THUMBNAIL_IMAGE, 1017, 0, 32, 0, (":Thumbs:F1017_1.ithmb",)),
        (
            PhotosMhodType.THUMBNAIL_IMAGE,
            1017,
            64,
            32,
            64,
            ("Photos/Thumbs/F1017_1.ithmb",),
        ),
        (PhotosMhodType.THUMBNAIL_IMAGE, 0, 128, 0, 0, (":Thumbs:F1017_1.ithmb",)),
        (
            PhotosMhodType.THUMBNAIL_IMAGE,
            1023,
            0xFFFFFFFF,
            32,
            64,
            (":Thumbs:F1023_1.ithmb", ":..:unsafe.ithmb"),
        ),
    )
    document = new_PhotosDB(
        next_mhii_id=101,
        unk_mhfd_0x10=6,
        image_items=(
            new_photos_chunk(
                MHII,
                MhiiHeader(image_id=100),
                children=tuple(
                    new_container_mhod(
                        kind,
                        new_photos_chunk(
                            MHNI,
                            MhniHeader(
                                format_id=format_id,
                                ithmb_offset=offset,
                                image_size=size,
                                image_size_2=allocation,
                            ),
                            children=tuple(
                                new_string_mhod(PhotosMhodType.FILE_NAME, name)
                                for name in names
                            ),
                        ),
                    )
                    for kind, format_id, offset, size, allocation, names in representations
                ),
            ),
        ),
    )
    original = write_PhotosDB(document)
    parsed = parse_PhotosDB(original)

    files = retained_photo_thumbnail_files(parsed)

    assert {file.file_name: file.ranges for file in files} == {
        "Photos/Thumbs/F1017_1.ithmb": ((0, 32), (64, 64), (128, 0)),
        "Photos/Thumbs/F1023_1.ithmb": ((0xFFFFFFFF, 64),),
        ":..:unsafe.ithmb": ((0xFFFFFFFF, 64),),
    }
    assert write_PhotosDB(parsed) == original
