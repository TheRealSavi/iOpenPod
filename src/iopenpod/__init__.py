"""iOpenPod application package."""

from .infrastructure.version import get_version

__version__ = get_version()

__all__ = ["__version__"]
