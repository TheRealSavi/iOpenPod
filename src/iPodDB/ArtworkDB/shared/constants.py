from enum import IntEnum, StrEnum


class ArtworkDatasetType(IntEnum):
    IMAGE_LIST = 1
    PHOTO_ALBUM_LIST = 2
    FILE_LIST = 3


class ArtworkMhodType(IntEnum):
    ALBUM_NAME = 1
    THUMBNAIL_IMAGE = 2
    FILE_NAME = 3
    # Classic 120GB 2.0.1's per-image ArtworkDB importer (0x08074c2c)
    # skips non-type-2 children. That does not identify type 4's purpose.
    UNKNOWN_4 = 4
    FULL_RES_IMAGE = 5
    # The retained MHNI container shape is known; its semantic role is not.
    # Being skipped on the above path does not make type 6 padding/unused,
    # nor prove it represents chapter artwork or full-resolution images.
    # See docs/research/unknown-field-reconciliation.md.
    UNKNOWN_CONTAINER_6 = 6


class MhodPayloadKind(StrEnum):
    OPAQUE = "opaque"
    STRING = "string"
    CONTAINER = "container"
    CONTEXTUAL_THUMBNAIL = "contextual_thumbnail"
    CONTEXTUAL_AUXILIARY = "contextual_auxiliary"
