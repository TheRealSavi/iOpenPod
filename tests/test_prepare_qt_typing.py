"""Keep the Qt typing overlay reproducible and its consumer checks meaningful."""

import ast
import os
import shutil
import subprocess
from importlib.metadata import PathDistribution
from pathlib import Path

import pytest
from scripts import prepare_qt_typing as typing_setup


def test_merge_preserves_unmodified_api_and_overloads() -> None:
    source = """# upstream license
class Widget(Base):
    @typing.overload
    def find(self, value: int) -> object: ...
    @typing.overload
    def find(self, value: str) -> object: ...
    def existing(self) -> int: ...
    class Nested:
        def unchanged(self) -> bool: ...
"""
    patch = """class Widget:
    label: str
    @typing.overload
    def find(self, value: int) -> int: ...
    @typing.overload
    def find(self, value: str) -> str: ...
    class Nested:
        enabled: bool
"""
    result = typing_setup.merge_stub(source, patch)
    ast.parse(result)
    assert result.startswith("# upstream license\nclass Widget(Base):")
    assert "    label: str\n" in result
    assert "        enabled: bool\n" in result
    assert "def existing(self) -> int: ..." in result
    assert "def unchanged(self) -> bool: ..." in result
    assert result.count("@typing.overload") == 2
    assert "-> object" not in result


@pytest.mark.parametrize(
    "patch",
    [
        "class Missing:\n    field: int\n",
        "class Widget:\n    def missing(self) -> None: ...\n",
        "class Widget:\n    existing: str\n",
    ],
)
def test_merge_rejects_drift_in_reviewed_source(patch: str) -> None:
    with pytest.raises(ValueError):
        typing_setup.merge_stub("class Widget:\n    existing: int\n", patch)


def test_merge_does_not_remove_intervening_members() -> None:
    source = """class Widget:
    def method(self, x: int) -> object: ...
    important: int
    def method(self, x: str) -> object: ...
"""
    with pytest.raises(ValueError, match="Non-contiguous"):
        typing_setup.merge_stub(
            source, "class Widget:\n    def method(self, x: int) -> int: ...\n"
        )


def test_prepare_uses_installed_version_and_removes_only_owned_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = tmp_path / "site-packages"
    metadata = installed / "PySide6_Essentials.dist-info"
    metadata.mkdir(parents=True)
    info = metadata / "METADATA"
    info.write_text("Name: PySide6-Essentials\nVersion: 6.9.3\n")
    source = installed / "PySide6"
    source.mkdir()
    original = "# upstream license\nclass Widget:\n    def existing(self) -> int: ...\n"
    (source / "QtWidgets.pyi").write_text(original)
    (source / "native-library.so").write_bytes(b"unchanged runtime")
    patches = tmp_path / "typings" / "patches"
    patches.mkdir(parents=True)
    (patches / "QtWidgets.pyi").write_text("class Widget:\n    field: str\n")

    def installed_distribution(_name: str) -> PathDistribution:
        return PathDistribution(metadata)

    monkeypatch.setattr(typing_setup, "distribution", installed_distribution)
    assert typing_setup.prepare_qt_typing(tmp_path)
    output = tmp_path / "typings" / "PySide6"
    first = (output / "QtWidgets.pyi").read_bytes()
    assert b"field: str" in first
    assert typing_setup.prepare_qt_typing(tmp_path)
    assert (output / "QtWidgets.pyi").read_bytes() == first
    assert not (output / "native-library.so").exists()
    assert (source / "QtWidgets.pyi").read_text() == original
    assert (source / "native-library.so").read_bytes() == b"unchanged runtime"

    # A newer Qt must never retain the old overlay.
    info.write_text("Name: PySide6-Essentials\nVersion: 6.11.2\n")
    assert not typing_setup.prepare_qt_typing(tmp_path)
    assert not output.exists()
    output.mkdir()
    custom = output / "custom.pyi"
    custom.write_text("keep: str\n")
    with pytest.raises(ValueError, match="unrecognized"):
        typing_setup.prepare_qt_typing(tmp_path)
    assert custom.read_text() == "keep: str\n"


def test_qt_types_preserve_slot_signatures_and_reject_invalid_calls(
    tmp_path: Path,
) -> None:
    shutil.copytree(
        typing_setup.ROOT / "typings" / "patches", tmp_path / "typings/patches"
    )
    prepared = typing_setup.prepare_qt_typing(tmp_path)
    if prepared:
        core = (tmp_path / "typings/PySide6/QtCore.pyi").read_text()
        assert "def beginFilterChange(" in core
        assert "def endFilterChange(" not in core
    sample = tmp_path / "qt_contract.py"
    valid = """from typing import assert_type
from PySide6.QtCore import QLocale, QObject, QRect, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QStyleOptionViewItem, QTreeWidgetItem

@Slot(int, result=str)
def format_count(value: int) -> str:
    return str(value)

assert_type(format_count(1), str)
option = QStyleOptionViewItem()
option.font = QFont()
assert_type(option.rect, QRect)
assert_type(QObject().parent(), QObject | None)
assert_type(QTreeWidgetItem().child(0), QTreeWidgetItem | None)
assert_type(QLocale().toString(1.5, 'f', 2), str)
"""
    sample.write_text(valid)
    command = [
        "uv",
        "run",
        "--no-sync",
        "mypy",
        "--config-file",
        str(typing_setup.ROOT / "pyproject.toml"),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--no-pretty",
        str(sample),
    ]
    environment = {**os.environ, "MYPYPATH": str(tmp_path / "typings")}
    good = subprocess.run(
        command,
        cwd=typing_setup.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert good.returncode == 0, good.stdout + good.stderr
    sample.write_text(valid + '\noption.font = "wrong"\nformat_count("wrong")\n')
    bad = subprocess.run(
        command,
        cwd=typing_setup.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "[assignment]" in bad.stdout
    assert "[arg-type]" in bad.stdout
    assert bad.stdout.count(": error:") == 2
