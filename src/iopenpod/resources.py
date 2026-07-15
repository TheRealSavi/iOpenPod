"""Access bundled application resources from the installed package."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def resource_path(*parts: str) -> Path:
    """Return a filesystem path for a resource bundled under ``iopenpod``."""

    return Path(str(files("iopenpod").joinpath(*parts)))

