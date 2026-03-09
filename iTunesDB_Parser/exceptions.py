"""
Custom exception hierarchy for iTunesDB parsing.

All exceptions inherit from :class:`ITunesDBParseError` so callers can catch
a single base class for any parsing failure.
"""


class ITunesDBParseError(Exception):
    """Base exception for all iTunesDB parsing failures."""


class CorruptHeaderError(ITunesDBParseError):
    """Raised when a chunk header contains invalid or unrecognizable data.

    Attributes:
        offset: Byte offset in the data buffer where the header was found.
        detail: Human-readable description of what went wrong.
    """

    def __init__(self, offset: int, detail: str) -> None:
        self.offset = offset
        self.detail = detail
        super().__init__(f"Corrupt header at offset 0x{offset:X}: {detail}")


class UnknownChunkTypeError(ITunesDBParseError):
    """Raised when an unrecognized 4-byte chunk identifier is encountered.

    Attributes:
        offset: Byte offset where the unknown chunk starts.
        chunk_type: The 4-byte ASCII identifier that was not recognized.
    """

    def __init__(self, offset: int, chunk_type: str) -> None:
        self.offset = offset
        self.chunk_type = chunk_type
        super().__init__(
            f"Unknown chunk type {chunk_type!r} at offset 0x{offset:X}"
        )


class InsufficientDataError(ITunesDBParseError):
    """Raised when the data buffer is too short for the expected read.

    Attributes:
        offset: Byte offset where the read was attempted.
        needed: Number of bytes required.
        available: Number of bytes actually available.
    """

    def __init__(self, offset: int, needed: int, available: int) -> None:
        self.offset = offset
        self.needed = needed
        self.available = available
        super().__init__(
            f"Insufficient data at offset 0x{offset:X}: "
            f"need {needed} bytes, only {available} available"
        )
