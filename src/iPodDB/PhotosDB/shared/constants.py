"""Typed identifiers used by the iPod Photo Database Chunk grammar."""

from enum import IntEnum

from iPodDB.ArtworkDB.shared.constants import (
    ArtworkDatasetType,
    ArtworkMhodType,
    MhodPayloadKind,
)


class PhotosDatasetType(IntEnum):
    """Known MHSD datasets in a Photo Database."""

    IMAGE_LIST = int(ArtworkDatasetType.IMAGE_LIST)
    PHOTO_ALBUM_LIST = int(ArtworkDatasetType.PHOTO_ALBUM_LIST)
    FILE_LIST = int(ArtworkDatasetType.FILE_LIST)


class PhotosMhodType(IntEnum):
    """Known typed data objects in a Photo Database."""

    ALBUM_NAME = int(ArtworkMhodType.ALBUM_NAME)
    THUMBNAIL_IMAGE = int(ArtworkMhodType.THUMBNAIL_IMAGE)
    FILE_NAME = int(ArtworkMhodType.FILE_NAME)
    UNKNOWN_4 = int(ArtworkMhodType.UNKNOWN_4)
    FULL_RES_IMAGE = int(ArtworkMhodType.FULL_RES_IMAGE)
    UNKNOWN_CONTAINER_6 = int(ArtworkMhodType.UNKNOWN_CONTAINER_6)


__all__ = ["MhodPayloadKind", "PhotosDatasetType", "PhotosMhodType"]
