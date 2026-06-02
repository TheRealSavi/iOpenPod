"""ArtworkDB binary constants shared by parser and writer code."""

from __future__ import annotations

from enum import IntEnum


class ArtworkDatasetType(IntEnum):
    IMAGE_LIST = 1
    PHOTO_ALBUM_LIST = 2
    FILE_LIST = 3


class ArtworkMhodType(IntEnum):
    ALBUM_NAME = 1
    THUMBNAIL_IMAGE = 2
    FILE_NAME = 3
    FULL_RES_IMAGE = 5
    UNKNOWN_CONTAINER_6 = 6


CHUNK_TYPE_MAP = {
    ArtworkDatasetType.IMAGE_LIST: "mhli",
    ArtworkDatasetType.PHOTO_ALBUM_LIST: "mhla",
    ArtworkDatasetType.FILE_LIST: "mhlf",
}

IDENTIFIER_READABLE_MAP = {
    "mhfd": "Data File",
    "mhsd": "Data Set",
    "mhli": "Image List",
    "mhii": "Image Item",
    "mhni": "Image Name",
    "mhla": "Photo Album List",
    "mhba": "Photo Album",
    "mhia": "Photo Album Item",
    "mhlf": "File List",
    "mhif": "File List Item",
    "mhod": "Data Object",
}

MHOD_TYPE_MAP = {
    ArtworkMhodType.ALBUM_NAME: {"type": "String", "name": "Album Name"},
    ArtworkMhodType.THUMBNAIL_IMAGE: {"type": "Container", "name": "Thumbnail Image"},
    ArtworkMhodType.FILE_NAME: {"type": "String", "name": "File Name"},
    ArtworkMhodType.FULL_RES_IMAGE: {"type": "Container", "name": "Full Res Image"},
    ArtworkMhodType.UNKNOWN_CONTAINER_6: {"type": "Container", "name": "UNK MHOD 6"},
}

IMAGE_CONTAINER_MHOD_TYPES = frozenset(
    {
        ArtworkMhodType.THUMBNAIL_IMAGE,
        ArtworkMhodType.FULL_RES_IMAGE,
        ArtworkMhodType.UNKNOWN_CONTAINER_6,
    }
)

IMAGE_CONTAINER_NAMES = (
    MHOD_TYPE_MAP[ArtworkMhodType.FULL_RES_IMAGE]["name"],
    MHOD_TYPE_MAP[ArtworkMhodType.THUMBNAIL_IMAGE]["name"],
    MHOD_TYPE_MAP[ArtworkMhodType.UNKNOWN_CONTAINER_6]["name"],
)

MHFD_HEADER_SIZE = 132
MHSD_HEADER_SIZE = 96
MHLI_HEADER_SIZE = 92
MHLA_HEADER_SIZE = 92
MHLF_HEADER_SIZE = 92
MHII_HEADER_SIZE = 152
MHOD_HEADER_SIZE = 24
MHNI_HEADER_SIZE = 76
MHIF_HEADER_SIZE = 124
