from enum import IntEnum, StrEnum


class ArtworkDatasetType(IntEnum):
    IMAGE_LIST = 1
    PHOTO_ALBUM_LIST = 2
    FILE_LIST = 3


class ArtworkMhodType(IntEnum):
    ALBUM_NAME = 1
    THUMBNAIL_IMAGE = 2
    FILE_NAME = 3
    UNKNOWN_4 = 4
    FULL_RES_IMAGE = 5
    UNKNOWN_CONTAINER_6 = 6


class MhodPayloadKind(StrEnum):
    OPAQUE = "opaque"
    STRING = "string"
    CONTAINER = "container"
    CONTEXTUAL_THUMBNAIL = "contextual_thumbnail"
    CONTEXTUAL_AUXILIARY = "contextual_auxiliary"
