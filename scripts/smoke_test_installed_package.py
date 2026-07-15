"""Validate the contents and entry point of an isolated wheel installation."""

from __future__ import annotations

import importlib.util
from importlib.metadata import entry_points
from pathlib import Path

import iopenpod
from iopenpod.resources import resource_path

LEGACY_NAMESPACES = (
    "ArtworkDB_Parser",
    "ArtworkDB_Writer",
    "GUI",
    "PodcastManager",
    "SyncEngine",
    "app_core",
    "infrastructure",
    "ipod_device",
    "iTunesDB_Parser",
    "iTunesDB_Writer",
)
REQUIRED_RESOURCES = (
    ("assets", "fonts", "NotoSans-Regular.ttf"),
    ("assets", "glyphs", "music.svg"),
    ("assets", "icons", "icon-256.png"),
    ("assets", "ipod_images", "iPodGeneric.png"),
    ("itunesdb_writer", "wasm", "calcHashAB.wasm"),
)


def main() -> None:
    """Fail if the installed distribution is incomplete or leaks old namespaces."""

    package_path = Path(iopenpod.__file__).resolve()
    source_package = Path(__file__).resolve().parents[1] / "src" / "iopenpod"
    if package_path.is_relative_to(source_package):
        raise SystemExit(f"Imported source tree instead of installed wheel: {package_path}")

    missing_namespaces = [
        name for name in LEGACY_NAMESPACES if importlib.util.find_spec(name) is not None
    ]
    if missing_namespaces:
        raise SystemExit(f"Legacy namespaces remain importable: {missing_namespaces}")

    missing_resources = [
        "/".join(parts) for parts in REQUIRED_RESOURCES if not resource_path(*parts).is_file()
    ]
    if missing_resources:
        raise SystemExit(f"Wheel is missing resources: {missing_resources}")

    scripts = tuple(entry_points(group="console_scripts", name="iopenpod"))
    if len(scripts) != 1 or not callable(scripts[0].load()):
        raise SystemExit("Installed iopenpod console entry point is missing or invalid")

    print(f"Installed package smoke test passed: {package_path}")


if __name__ == "__main__":
    main()
