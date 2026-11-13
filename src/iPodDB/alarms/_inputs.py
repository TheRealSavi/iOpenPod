"""Runtime input validation shared by the Alarm codecs."""


def capture_bytes(value: object, *, label: str) -> bytes:
    """Reject invalid objects before bytes(integer) can invent a source buffer."""
    if not isinstance(value, bytes | bytearray):
        raise TypeError(f"{label} must be bytes or bytearray.")
    return bytes(value)
