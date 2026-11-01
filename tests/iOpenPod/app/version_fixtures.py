"""Version values shared by tests for the installed Python package."""

import tomllib
from pathlib import Path

from packaging.version import Version

_ROOT = Path(__file__).parents[3]
_PROJECT_VERSION = Version(
    tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
)


def patch_version(offset: int) -> str:
    """Return a version offset from the project's current patch version."""

    major, minor, patch = _PROJECT_VERSION.release
    value = patch + offset
    if value < 0:
        raise ValueError("Test version offsets require a non-negative patch version")
    return f"{major}.{minor}.{value}"


CURRENT_VERSION = str(_PROJECT_VERSION)
# Synthetic installed releases need only be stable and older than the project.
# Fixed versions keep minor/major releases with patch zero collectable.
PREVIOUS_VERSION = "0.0.2"
OLDER_VERSION = "0.0.1"
NEXT_VERSION = patch_version(1)
NEXT_MINOR_VERSION = f"{_PROJECT_VERSION.major}.{_PROJECT_VERSION.minor + 1}.0"
