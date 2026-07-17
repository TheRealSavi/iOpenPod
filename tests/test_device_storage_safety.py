from __future__ import annotations

import pytest

from iopenpod.device.storage_safety import (
    FileSizeLimitError,
    allocated_size,
    effective_max_file_size_bytes,
    require_file_size_supported,
)


def test_allocated_size_rounds_each_file_up_to_an_allocation_unit() -> None:
    assert allocated_size(0, 4096) == 0
    assert allocated_size(1, 4096) == 4096
    assert allocated_size(4097, 4096) == 8192


def test_effective_file_limit_uses_the_stricter_known_limit() -> None:
    assert effective_max_file_size_bytes(4_000, 3_000) == 3_000
    assert effective_max_file_size_bytes(4_000, None) == 4_000
    assert effective_max_file_size_bytes(None, None) is None


def test_file_size_limit_reports_the_file_and_detected_limit() -> None:
    with pytest.raises(FileSizeLimitError, match="album.flac.*4.0 GB"):
        require_file_size_supported(
            5 * 1024**3,
            max_file_size_bytes=4 * 1024**3 - 1,
            display_name="album.flac",
        )
