"""Report test modules that cannot share pytest's default import namespace.

Under the default ``prepend`` import mode a test module is imported by the dotted
path that remains once the walk up from its directory leaves the package chain.
A directory is part of that chain only while it holds an ``__init__.py``:

    tests/iPodDB/library/test_genius_browse.py          -> test_genius_browse
    tests/iOpenPod/app/services/test_genius_browse.py   -> test_genius_browse

Two modules with the same import name are the same module. Collection then aborts
with ``import file mismatch`` and nothing in the suite runs, which is why the names
are checked here instead of being left to whichever file pytest reaches second.

The rule belongs to ``prepend`` alone. ``importlib`` mode imports each module by
path and allows repeated names, so the check stands aside there rather than
imposing a naming rule the suite has not chosen.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

_TESTS = Path(__file__).parent


def _import_name(module: Path, root: Path) -> str:
    """Return the name pytest imports one test module by under prepend mode."""

    parts = [module.stem]
    directory = module.parent
    while directory != root and (directory / "__init__.py").is_file():
        parts.append(directory.name)
        directory = directory.parent
    return ".".join(reversed(parts))


def _collisions(root: Path) -> list[str]:
    """List every import name claimed by more than one test module."""

    names = Counter(
        _import_name(path, root)
        for path in root.rglob("test_*.py")
        if "__pycache__" not in path.parts
    )
    return sorted(name for name, count in names.items() if count > 1)


def test_test_modules_have_unique_import_names(pytestconfig: pytest.Config) -> None:
    """Name every collision at once, rather than the pair pytest happens to reach."""

    if pytestconfig.getoption("importmode") != "prepend":
        pytest.skip("Import-by-path mode gives each test module its own namespace")

    collisions = _collisions(_TESTS)

    assert collisions == [], (
        "These import names belong to more than one test module, so collection "
        "aborts before any test runs: " + ", ".join(collisions)
    )


def test_collision_detection_follows_the_prepend_rule(tmp_path: Path) -> None:
    """Prove the rule itself: packages qualify a name, bare directories do not."""

    bare = tmp_path / "bare"
    for directory in ("alpha", "beta"):
        (bare / directory).mkdir(parents=True)
        (bare / directory / "test_same.py").write_text("", encoding="utf-8")
    assert _collisions(bare) == ["test_same"]

    packaged = tmp_path / "packaged"
    for directory in ("alpha", "beta"):
        (packaged / directory).mkdir(parents=True)
        (packaged / directory / "__init__.py").write_text("", encoding="utf-8")
        (packaged / directory / "test_same.py").write_text("", encoding="utf-8")
    assert _collisions(packaged) == []
