"""Shared deterministic seeds for placeholder artwork."""


def stable_artwork_seed(value: str) -> int:
    """Return the stable 32-bit seed used by every artwork surface."""

    seed = 0
    for character in value:
        seed = ((seed * 33) + ord(character)) & 0xFFFFFFFF
    return seed


__all__ = ["stable_artwork_seed"]
