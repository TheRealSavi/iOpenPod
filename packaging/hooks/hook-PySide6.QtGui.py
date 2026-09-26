"""Collect GUI runtime plugins without unused PDF and virtual-keyboard modules."""

from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class _QtHooks(Protocol):
    def add_qt6_dependencies(
        self, hook_file: str
    ) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]]]: ...


# PyInstaller's Qt helpers have no type stubs; keep their API typed at this boundary.
qt_hooks = cast("_QtHooks", import_module("PyInstaller.utils.hooks.qt"))
hiddenimports, binaries, datas = qt_hooks.add_qt6_dependencies(__file__)
excluded_plugins = {"qpdf", "qtvirtualkeyboardplugin"}
binaries = [
    (source, target)
    for source, target in binaries
    if Path(source).name.lower().removeprefix("lib").split(".")[0]
    not in excluded_plugins
]
