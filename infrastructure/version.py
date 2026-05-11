"""Installed application version lookup."""

from __future__ import annotations

import logging
from importlib.metadata import version as package_version

logger = logging.getLogger(__name__)


def get_version() -> str:
    """Return the app version from installed package metadata."""

    try:
        return package_version("iopenpod")
    except Exception:
        logger.debug("Failed to read installed iopenpod version", exc_info=True)
        return "1.0.51"
