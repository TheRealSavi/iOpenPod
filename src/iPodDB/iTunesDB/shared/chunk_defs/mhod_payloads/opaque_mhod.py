"""Opaque MHOD payload definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload


@dataclass(frozen=True, slots=True)
class MhodOpaquePayload(MhodPayload):
    data: bytes
