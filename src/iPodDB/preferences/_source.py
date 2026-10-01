"""Capture binary inputs at the runtime validation boundary."""


def capture_source(value: object) -> bytes:
    """Validate before copying: bytes(integer) would silently invent a buffer."""

    if not isinstance(value, bytes | bytearray):
        raise TypeError("Preferences input must be bytes or bytearray.")
    return bytes(value)
