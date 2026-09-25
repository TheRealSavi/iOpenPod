"""Application-facing requests and immutable decoded artwork."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtworkRequest:
    """Ask for one artwork image near a physical-pixel display target."""

    artwork_id: int
    target_px: int

    def __post_init__(self) -> None:
        if self.artwork_id <= 0:
            raise ValueError("An Artwork Request requires a positive artwork ID")
        if self.target_px <= 0:
            raise ValueError("An Artwork Request requires a positive pixel target")


@dataclass(frozen=True, slots=True)
class ArtworkImage:
    """Owned RGB888 pixels decoded for one Active iPod generation."""

    cache_key: str
    artwork_id: int
    format_id: int
    width: int
    height: int
    rgb888: bytes

    def __post_init__(self) -> None:
        if not self.cache_key:
            raise ValueError("An Artwork Image requires a cache key")
        if self.artwork_id <= 0 or self.format_id <= 0:
            raise ValueError("Artwork and format IDs must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Artwork dimensions must be positive")
        expected = self.width * self.height * 3
        if len(self.rgb888) != expected:
            raise ValueError(
                f"Artwork has {len(self.rgb888)} RGB bytes; expected {expected}"
            )

    @property
    def byte_count(self) -> int:
        return len(self.rgb888)


__all__ = ["ArtworkImage", "ArtworkRequest"]
