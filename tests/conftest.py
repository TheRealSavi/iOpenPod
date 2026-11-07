"""Cross-platform pytest configuration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from storage._writer_lock import _WriterLease  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def pytest_configure() -> None:
    """Use Qt's headless platform during automated widget tests."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def isolated_storage_writer_locks(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Keep reused synthetic identities private to this test process/worker.

    Real lease acquisition and explicit lock directories stay unchanged. Avoid
    changing tempfile or its environment: path-security tests exercise those.
    """

    directory = tmp_path_factory.mktemp("storage-writer-locks")
    original_init = _WriterLease.__init__

    def initialize_test_lease(
        lease: _WriterLease,
        identity: str,
        lock_directory: Path | None,
        resource_name: str,
    ) -> None:
        original_init(
            lease,
            identity,
            directory if lock_directory is None else lock_directory,
            resource_name,
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_WriterLease, "__init__", initialize_test_lease)
        yield
