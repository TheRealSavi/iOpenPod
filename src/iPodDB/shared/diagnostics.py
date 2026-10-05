"""Log bounded, content-free evidence of retained Unknown Data.

The context belongs to one parsing call, including nested readers. It is neither
application state nor a process-wide suppression cache: each read is independent.
"""

import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)
_MAX_EXAMPLES = 8


@dataclass(slots=True)
class _Diagnostics:
    artifact: str
    regions: int = 0
    byte_count: int = 0
    examples: list[str] = field(default_factory=list[str])
    example_kinds: set[str] = field(default_factory=set[str])

    def add(self, kind: str, offset: int, size: int) -> None:
        self.regions += 1
        self.byte_count += size
        if len(self.examples) < _MAX_EXAMPLES and kind not in self.example_kinds:
            self.example_kinds.add(kind)
            self.examples.append(f"{kind} at {offset:#x} ({size} bytes)")

    def log(self) -> None:
        if self.regions:
            logger.warning(
                "Retained Unknown Data: artifact=%s regions=%d bytes=%d examples=%s%s",
                self.artifact,
                self.regions,
                self.byte_count,
                "; ".join(self.examples),
                "; further regions omitted"
                if self.regions > len(self.examples)
                else "",
            )


_active: ContextVar[_Diagnostics | None] = ContextVar(
    "ipoddb_diagnostics", default=None
)


def report_unknown_data(kind: str, offset: int, size: int) -> None:
    """Record a retained region without logging its contents or interpreting it."""
    diagnostics = _active.get()
    if diagnostics is not None:
        diagnostics.add(kind, offset, size)
    else:
        standalone = _Diagnostics("record")
        standalone.add(kind, offset, size)
        standalone.log()


def retain_unknown_bytes(
    data: bytes | bytearray, start: int, end: int, kind: str
) -> bytes:
    """Retain a bounded region, reporting its location without its contents."""
    if not 0 <= start <= end <= len(data):
        raise ValueError("Unknown Data has invalid byte boundaries.")
    if start < end:
        report_unknown_data(kind, start, end - start)
    return bytes(data[start:end])


def log_unknown_data[**P, R](
    artifact: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Emit at most one warning for a complete read, even with many extensions."""

    def decorate(read: Callable[P, R]) -> Callable[P, R]:
        @wraps(read)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            if _active.get() is not None:
                return read(*args, **kwargs)
            diagnostics = _Diagnostics(artifact)
            token = _active.set(diagnostics)
            try:
                result = read(*args, **kwargs)
            finally:
                _active.reset(token)
            diagnostics.log()
            return result

        return wrapped

    return decorate
