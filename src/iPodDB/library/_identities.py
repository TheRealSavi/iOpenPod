"""Collision-free native identity allocation without source-record renumbering."""

from collections.abc import Iterable


class IdentityAllocator:
    def __init__(self, existing: Iterable[int], bits: int) -> None:
        self.used = set(existing)
        self.limit = 1 << bits
        self.bits = bits
        self.cursor = max(self.used, default=0) + 1

    def take(self) -> int:
        if self.cursor >= self.limit:
            self.cursor = 1
        start = self.cursor
        while self.cursor in self.used:
            self.cursor += 1
            if self.cursor >= self.limit:
                self.cursor = 1
            if self.cursor == start:
                raise ValueError(f"No unused {self.bits}-bit identities remain.")
        result = self.cursor
        self.used.add(result)
        self.cursor += 1
        return result


def allocate(
    existing: Iterable[int], requested: Iterable[int], bits: int
) -> dict[int, int]:
    original_ids = set(existing)
    allocator = IdentityAllocator(original_ids, bits)
    result: dict[int, int] = {}
    for identity in requested:
        if identity in original_ids:
            result[identity] = identity
            continue
        result[identity] = allocator.take()
    return result
