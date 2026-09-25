"""Application-facing requests and immutable decoded Photo representations."""

from dataclasses import dataclass

# Application request selector. This is not the format ID stored in the full-
# resolution MHNI, whose original value remains in ``PhotoRepresentation``.
FULL_RESOLUTION_REQUEST_ID = 0


@dataclass(frozen=True, slots=True)
class PhotoRequest:
    """Ask for one Photo representation near a physical-pixel display target.

    Format zero names a retained full-resolution image. Positive format IDs name
    exact device thumbnail formats, while ``None`` lets the loader choose one.
    """

    photo_id: int
    target_px: int
    format_id: int | None = None

    def __post_init__(self) -> None:
        if self.photo_id <= 0:
            raise ValueError("A Photo Request requires a positive Photo ID")
        if self.target_px <= 0:
            raise ValueError("A Photo Request requires a positive pixel target")
        if self.format_id is not None and self.format_id < 0:
            raise ValueError("A requested Photo format ID must not be negative")


@dataclass(frozen=True, slots=True)
class PhotoImage:
    """Owned RGB888 pixels decoded for one Active iPod generation."""

    cache_key: str
    photo_id: int
    format_id: int
    width: int
    height: int
    rgb888: bytes

    def __post_init__(self) -> None:
        if not self.cache_key:
            raise ValueError("A Photo Image requires a cache key")
        if self.photo_id <= 0 or self.format_id < 0:
            raise ValueError(
                "A Photo ID must be positive and its format ID must not be negative"
            )
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Photo dimensions must be positive")
        expected = self.width * self.height * 3
        if len(self.rgb888) != expected:
            raise ValueError(
                f"Photo has {len(self.rgb888)} RGB bytes; expected {expected}"
            )

    @property
    def byte_count(self) -> int:
        return len(self.rgb888)


__all__ = ["FULL_RESOLUTION_REQUEST_ID", "PhotoImage", "PhotoRequest"]
