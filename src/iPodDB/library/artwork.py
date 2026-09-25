"""Byte-only cover selection and decoding for callers that own persistence."""

from dataclasses import dataclass, field

from iPodDB.ArtworkDB.ithmb import IthmbLayout, decode_ithmb
from iPodDB.ArtworkDB.ithmb import IthmbPixelFormat as CoverPixelFormat
from iPodDB.ArtworkDB.shared.artwork_index import ArtworkItem, IthmbLocation


@dataclass(frozen=True, slots=True)
class CoverFormat:
    """A caller-supplied cover capability, independent of a Device Profile."""

    format_id: int
    width: int
    height: int
    row_bytes: int
    pixel_format: CoverPixelFormat


@dataclass(frozen=True, slots=True)
class ArtworkPixels:
    """Owned RGB888 data with no database, filesystem, or GUI objects."""

    width: int
    height: int
    rgb888: bytes

    def __post_init__(self) -> None:
        if (
            not 0 < self.width <= 8192
            or not 0 < self.height <= 8192
            or self.width * self.height > 32 * 1024 * 1024
        ):
            raise ValueError("Artwork dimensions exceed the supported pixel bounds")
        if len(self.rgb888) != self.width * self.height * 3:
            raise ValueError("Artwork RGB888 byte length does not match its dimensions")


@dataclass(frozen=True, slots=True)
class ArtworkRead:
    """One relative file range to read, then decode after Storage validation."""

    format_id: int
    relative_path: str
    offset: int
    length: int
    _layout: IthmbLayout = field(repr=False)

    def decode(self, payload: bytes) -> ArtworkPixels:
        if len(payload) != self.length:
            raise ValueError("Artwork bytes do not match the requested range")
        decoded = decode_ithmb(payload, self._layout)
        return ArtworkPixels(decoded.width, decoded.height, decoded.pixels)


def select_artwork(
    item: ArtworkItem,
    formats: tuple[CoverFormat, ...],
    target_px: int,
) -> ArtworkRead | None:
    by_id = {cover.format_id: cover for cover in formats}
    candidates = tuple(
        (location, by_id[location.format_id])
        for location in item.locations
        if location.format_id in by_id
    )
    if not candidates:
        return None

    def score(candidate: tuple[IthmbLocation, CoverFormat]) -> tuple[int, int, int]:
        location, cover = candidate
        width = location.width or cover.width
        height = location.height or cover.height
        edge = max(width, height)
        area = width * height
        return (0, edge, area) if edge >= target_px else (1, -edge, -area)

    location, cover = min(candidates, key=score)
    return ArtworkRead(
        format_id=cover.format_id,
        relative_path=_artwork_path(location),
        offset=location.offset,
        length=location.byte_length,
        _layout=IthmbLayout(
            width=_visible_dimension(location.width, cover.width),
            height=_visible_dimension(location.height, cover.height),
            row_bytes=cover.row_bytes,
            pixel_format=cover.pixel_format,
            horizontal_padding=min(location.horizontal_padding, cover.width),
            vertical_padding=min(location.vertical_padding, cover.height),
        ),
    )


def _artwork_path(location: IthmbLocation) -> str:
    fallback = f"F{location.format_id}_1.ithmb"
    raw = location.file_name.strip().replace("\\", "/").replace(":", "/")
    parts = tuple(part for part in raw.split("/") if part)
    file_name = fallback
    if parts and not any(part in {".", ".."} for part in parts):
        file_name = parts[-1]
    if not file_name.casefold().endswith(".ithmb"):
        file_name = fallback
    return f"iPod_Control/Artwork/{file_name}"


def _visible_dimension(observed: int, defined: int) -> int:
    return observed if 0 < observed <= defined else defined


__all__ = ["ArtworkPixels", "ArtworkRead", "CoverFormat", "CoverPixelFormat"]
