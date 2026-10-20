"""Pure results from recovering readable text in one demuxed subtitle packet."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConvertedText:
    text: str
    warnings: tuple[str, ...] = ()
