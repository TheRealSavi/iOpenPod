"""Qualified Classic firmware disk layout and mod RAM limits.

The firmware partition and music filesystem are not repartitioned. Only the
OS slot grows; the original AUPD/hash tail moves intact within that partition.
RAM is reserved for the linked payload, up to MOD_MEMORY_BYTES, not for unused
disk-slot capacity.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassicFirmwareLayout:
    osos: int
    aupd: int
    hash_record: int
    end: int

    @property
    def os_slot_bytes(self) -> int:
        return self.aupd - self.osos


STOCK_LAYOUT = ClassicFirmwareLayout(0x5007000, 0x5A2D000, 0x5B4B000, 0x5B4D000)
EXPANDED_LAYOUT = ClassicFirmwareLayout(0x5007000, 0x6007000, 0x6125000, 0x6127000)
OS_HEADER_BYTES = 0x800
MAX_OS_BODY_BYTES = EXPANDED_LAYOUT.os_slot_bytes - OS_HEADER_BYTES
MOD_BASE = 0x08B3C000
MOD_MEMORY_BYTES = 4 * 1024 * 1024
MINIMUM_BOOTLOADER_VERSION = "2.1.0"
