import logging
from importlib.metadata import version as package_version

logger = logging.getLogger(__name__)


def get_version() -> str:
    """Return the iOpenPod version from installed package metadata."""

    try:
        return package_version("iopenpod")
    except Exception:
        logger.debug("Failed to read installed iopenpod version", exc_info=True)
        return "2.0.9"
