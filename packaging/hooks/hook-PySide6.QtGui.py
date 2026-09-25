"""Collect GUI runtime plugins without unused PDF and virtual-keyboard modules."""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
excluded_plugins = {"qpdf", "qtvirtualkeyboardplugin"}
binaries = [
    (source, target)
    for source, target in binaries
    if Path(source).name.lower().removeprefix("lib").split(".")[0]
    not in excluded_plugins
]
