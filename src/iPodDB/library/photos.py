"""Source-neutral Photo Library records and lazy thumbnail read plans."""

from dataclasses import dataclass, field
from enum import StrEnum

from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPaddingMode,
    decode_ithmb,
)
from iPodDB.ArtworkDB.ithmb import IthmbPixelFormat as PhotoPixelFormat
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb


class PhotoRepresentationKind(StrEnum):
    """Semantic role of one stored representation of a Photo."""

    FULL_RESOLUTION = "full_resolution"
    THUMBNAIL = "thumbnail"


class PhotoAlbumKind(StrEnum):
    """Source-neutral Photo Album roles understood by iOpenPod."""

    MASTER = "master"
    ALBUM = "album"


@dataclass(frozen=True, slots=True)
class PhotoRepresentation:
    """One retained image location, expressed without filesystem authority."""

    kind: PhotoRepresentationKind
    format_id: int
    relative_path: str
    offset: int
    size_bytes: int
    width: int
    height: int
    horizontal_padding: int = 0
    vertical_padding: int = 0


@dataclass(frozen=True, slots=True)
class Photo:
    """One Photo and its available full-resolution or thumbnail representations."""

    photo_id: int
    rating: int = 0
    original_date: int = 0
    taken_date: int = 0
    source_size_bytes: int = 0
    representations: tuple[PhotoRepresentation, ...] = ()


@dataclass(frozen=True, slots=True)
class IPodPhotoAlbumDetails:
    """Retained iPod diagnostics that do not belong to the common Photo contract."""

    album_type: int = 0
    transition_direction: int = 0
    music_db_track_id: int = 0
    previous_album_id: int = 0


@dataclass(frozen=True, slots=True)
class PhotoAlbum:
    """One ordered Photo Album with semantic slideshow preferences."""

    album_id: int
    name: str
    photo_ids: tuple[int, ...] = ()
    kind: PhotoAlbumKind = PhotoAlbumKind.ALBUM
    play_music: bool = False
    repeat: bool = False
    random: bool = False
    show_titles: bool = False
    slide_duration_ms: int = 0
    transition_duration_ms: int = 0
    music_track_id: int | None = None
    ipod: IPodPhotoAlbumDetails | None = None


@dataclass(frozen=True, slots=True)
class PhotoFileFormat:
    """One PhotosDB file-format declaration retained for inspection."""

    format_id: int
    image_size_bytes: int
    relative_path: str = ""


@dataclass(frozen=True, slots=True)
class PhotoLibrary:
    """Ordered immutable Photos, Albums, and file formats from one source."""

    photos: tuple[Photo, ...] = ()
    albums: tuple[PhotoAlbum, ...] = ()
    formats: tuple[PhotoFileFormat, ...] = ()

    def __post_init__(self) -> None:
        for label, identities in (
            ("Photo", (photo.photo_id for photo in self.photos)),
            ("Photo Album", (album.album_id for album in self.albums)),
            ("Photo format", (item.format_id for item in self.formats)),
        ):
            values = tuple(identities)
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label} identity in Photo Library")


@dataclass(frozen=True, slots=True)
class PhotoThumbnailFormat:
    """Caller-supplied device capability for decoding Photo thumbnails."""

    format_id: int
    width: int
    height: int
    row_bytes: int
    pixel_format: PhotoPixelFormat


@dataclass(frozen=True, slots=True)
class PhotoPixels:
    """Owned RGB888 Photo pixels with no database, filesystem, or GUI objects."""

    width: int
    height: int
    rgb888: bytes

    def __post_init__(self) -> None:
        if (
            not 0 < self.width <= 8192
            or not 0 < self.height <= 8192
            or self.width * self.height > 32 * 1024 * 1024
        ):
            raise ValueError("Photo dimensions exceed the supported pixel bounds")
        if len(self.rgb888) != self.width * self.height * 3:
            raise ValueError("Photo RGB888 byte length does not match its dimensions")


@dataclass(frozen=True, slots=True)
class PhotoRead:
    """One relative thumbnail range to read and decode through Storage."""

    photo_id: int
    format_id: int
    relative_path: str
    offset: int
    length: int
    _layout: IthmbLayout = field(repr=False)

    def decode(self, payload: bytes) -> PhotoPixels:
        if len(payload) != self.length:
            raise ValueError("Photo bytes do not match the requested range")
        decoded = decode_ithmb(payload, self._layout)
        return PhotoPixels(decoded.width, decoded.height, decoded.pixels)


def encode_photo_thumbnail(
    pixels: PhotoPixels,
    image_format: PhotoThumbnailFormat,
    *,
    horizontal_padding: int = 0,
    vertical_padding: int = 0,
) -> bytes:
    """Encode and independently decode a device thumbnail through the public contract.

    The caller supplies semantic pixels and Device Profile capabilities; packed
    iTHMB layout details and codec verification remain inside iPodDB. Padding is
    the symmetric PhotosDB margin on one side of the stored raster.
    """
    if horizontal_padding < 0 or vertical_padding < 0:
        raise ValueError("Photo thumbnail padding must not be negative")
    if horizontal_padding * 2 >= image_format.width or vertical_padding * 2 >= (
        image_format.height
    ):
        raise ValueError("Photo thumbnail padding leaves no visible raster")
    symmetric = bool(horizontal_padding or vertical_padding)
    layout = IthmbLayout(
        image_format.width - horizontal_padding if symmetric else image_format.width,
        image_format.height - vertical_padding if symmetric else image_format.height,
        image_format.row_bytes,
        image_format.pixel_format,
        horizontal_padding=horizontal_padding,
        vertical_padding=vertical_padding,
        padding_mode=(
            IthmbPaddingMode.SYMMETRIC if symmetric else IthmbPaddingMode.TRAILING
        ),
    )
    encoded = encode_ithmb(
        DecodedImage(pixels.width, pixels.height, pixels.rgb888), layout
    )
    checked = decode_ithmb(encoded, layout)
    expected_size = (
        image_format.width - 2 * horizontal_padding
        if symmetric
        else image_format.width,
        image_format.height - 2 * vertical_padding
        if symmetric
        else image_format.height,
    )
    if (checked.width, checked.height) != expected_size:
        raise ValueError("Photo thumbnail verification returned unexpected dimensions.")
    return encoded


def select_photo_thumbnail(
    photo: Photo,
    formats: tuple[PhotoThumbnailFormat, ...],
    target_px: int,
    *,
    format_id: int | None = None,
) -> PhotoRead | None:
    """Choose an exact or smallest suitable retained thumbnail representation."""

    by_id = {item.format_id: item for item in formats}
    candidates = tuple(
        (representation, by_id[representation.format_id])
        for representation in photo.representations
        if representation.kind is PhotoRepresentationKind.THUMBNAIL
        and representation.format_id in by_id
        and (format_id is None or representation.format_id == format_id)
        and representation.relative_path
        and representation.size_bytes > 0
    )
    if target_px <= 0 or not candidates:
        return None

    def score(
        candidate: tuple[PhotoRepresentation, PhotoThumbnailFormat],
    ) -> tuple[int, int, int]:
        representation, image_format = candidate
        width = representation.width or image_format.width
        height = representation.height or image_format.height
        edge = max(width, height)
        area = width * height
        return (0, edge, area) if edge >= target_px else (1, -edge, -area)

    representation, image_format = min(candidates, key=score)
    horizontal_padding = min(
        representation.horizontal_padding,
        max(0, image_format.width - 1),
    )
    vertical_padding = min(
        representation.vertical_padding,
        max(0, image_format.height - 1),
    )
    return PhotoRead(
        photo_id=photo.photo_id,
        format_id=representation.format_id,
        relative_path=representation.relative_path,
        offset=representation.offset,
        length=representation.size_bytes,
        _layout=IthmbLayout(
            # Plane and field offsets come from the Device Profile's physical
            # raster. MHNI padding is a crop applied only after decoding.
            width=image_format.width - horizontal_padding,
            height=image_format.height - vertical_padding,
            row_bytes=image_format.row_bytes,
            pixel_format=image_format.pixel_format,
            horizontal_padding=horizontal_padding,
            vertical_padding=vertical_padding,
            padding_mode=IthmbPaddingMode.SYMMETRIC,
        ),
    )


__all__ = [
    "IPodPhotoAlbumDetails",
    "Photo",
    "PhotoAlbum",
    "PhotoAlbumKind",
    "PhotoFileFormat",
    "PhotoLibrary",
    "PhotoPixelFormat",
    "PhotoPixels",
    "PhotoRead",
    "PhotoRepresentation",
    "PhotoRepresentationKind",
    "PhotoThumbnailFormat",
    "encode_photo_thumbnail",
    "select_photo_thumbnail",
]
