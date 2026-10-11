"""Application-facing requests and immutable decoded artwork."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ArtworkRequest:
    """Ask for one artwork image near a physical-pixel display target."""

    artwork_id: int
    target_px: int
    display_time_ms: int | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.artwork_id <= 0:
            raise ValueError("An Artwork Request requires a positive artwork ID")
        if self.target_px <= 0:
            raise ValueError("An Artwork Request requires a positive pixel target")
        if self.display_time_ms is not None:
            _validate_display_time(self.display_time_ms)


@dataclass(frozen=True, slots=True)
class ArtworkImage:
    """Owned RGB888 pixels decoded for one Active iPod generation."""

    cache_key: str
    artwork_id: int
    format_id: int
    width: int
    height: int
    rgb888: bytes
    # None identifies an ordinary cover request; an integer identifies an exact
    # time-group request. Presentation caches must not mix those requests.
    display_time_ms: int | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.cache_key:
            raise ValueError("An Artwork Image requires a cache key")
        if self.artwork_id <= 0 or self.format_id <= 0:
            raise ValueError("Artwork and format IDs must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Artwork dimensions must be positive")
        if self.display_time_ms is not None:
            _validate_display_time(self.display_time_ms)
        expected = self.width * self.height * 3
        if len(self.rgb888) != expected:
            raise ValueError(
                f"Artwork has {len(self.rgb888)} RGB bytes; expected {expected}"
            )

    @property
    def byte_count(self) -> int:
        return len(self.rgb888)


def _validate_display_time(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 0xFFFFFFFF
    ):
        raise ValueError("Artwork display time must fit an unsigned 32-bit value")


__all__ = ["ArtworkImage", "ArtworkRequest"]
