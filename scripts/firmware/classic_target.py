"""Pinned prepared Apple 2.0.5 input and its initialized runtime mappings.

These describe the maintainer input, not the larger composed OS or a device's
NOR image. Disk-slot and mod-RAM budgets remain in app.firmware.classic_layout.
"""

INPUT_SHA = "660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e"
INPUT_BYTES = 10_634_496
HEADER_BYTES = 0x800
IRAM_BASE = 0x22000000
IRAM_END = 0x2200AF98
DRAM_BASE = 0x08000000
DRAM_END = 0x08A18D64
DRAM_FILE = 0xB798
