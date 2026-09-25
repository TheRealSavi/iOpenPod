"""Errors raised while decoding iPod database Chunks."""


class iPodDBParseError(ValueError):  # noqa: N801
    """Base class for structurally invalid iPod database data."""


class TruncatedChunkError(iPodDBParseError):
    """A Chunk extends beyond the available bytes."""


class InvalidChunkLengthError(iPodDBParseError):
    """A Chunk declares internally inconsistent lengths."""


class InvalidChunkDataError(iPodDBParseError):
    """Known Chunk data violates its registered binary definition."""


class UnexpectedHeaderMarkerError(iPodDBParseError):
    """A Chunk does not have the Header Marker required at its position."""


class iPodDBWriteError(ValueError):  # noqa: N801
    """A structured iPod database cannot be serialized without data loss."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "binary.invalid_value",
        field: str = "",
        chunk_path: tuple[int, ...] = (),
        offset: int | None = None,
        marker: bytes = b"",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.chunk_path = chunk_path
        self.offset = offset
        self.marker = marker
