"""Configure caches for the read-only application bundle."""

import os
import sys


def configure_frozen_runtime() -> None:
    """Keep compiled analysis caches writable without changing the user's PATH."""
    if not getattr(sys, "frozen", False):
        return
    # Installed bundles may be read-only. Keep compiled analysis code in Numba's
    # per-user cache even when a developer's unpacked bundle happens to be writable.
    os.environ.setdefault("NUMBA_CACHE_LOCATOR_CLASSES", "UserWideCacheLocator")


def configure_bundled_tools() -> None:
    """Compatibility name for launchers installed before the runtime rename.

    Older editable installs imported this symbol while the application was
    renamed from its bundled-media-tools setup. Keep that launcher usable while
    the environment refreshes; the current runtime contract is the frozen-cache
    configuration above and does not add anything to ``PATH``.
    """
    configure_frozen_runtime()
