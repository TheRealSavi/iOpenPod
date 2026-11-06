"""Keep the Whenever sentinel overlay narrow, owned, and useful to consumers."""

import ast
import os
import subprocess
from importlib.metadata import PathDistribution, distribution
from pathlib import Path

import pytest
from scripts import prepare_whenever_typing as typing_setup


def _installed_source() -> str:
    installed = distribution("whenever")
    if installed.version != typing_setup.SUPPORTED_VERSION:
        pytest.skip("The reviewed overlay only applies to Whenever 0.11.0")
    source = Path(str(installed.locate_file("whenever/__init__.pyi")))
    return source.read_text(encoding="utf-8")


@pytest.fixture
def installed_whenever(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Use the real public stub and license without touching installed files."""
    original = distribution("whenever")
    source = _installed_source()
    site = tmp_path / "site-packages"
    metadata = site / "whenever-0.11.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Name: whenever\nVersion: 0.11.0\n", encoding="utf-8"
    )
    package = site / "whenever"
    package.mkdir()
    (package / "__init__.pyi").write_text(source, encoding="utf-8")
    (package / "__init__.py").write_text("runtime: str = 'unchanged'\n")
    (package / "_whenever.pyd").write_bytes(b"unchanged native runtime")
    (package / "py.typed").touch()
    records = ["whenever/__init__.pyi,,", "whenever/py.typed,,"]
    assert original.files is not None
    for path in original.files:
        if ".dist-info/licenses/" in str(path):
            destination = metadata / "licenses" / path.name
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(Path(str(original.locate_file(path))).read_bytes())
            records.append(f"{metadata.name}/licenses/{path.name},,")
    (metadata / "RECORD").write_text("\n".join(records) + "\n", encoding="utf-8")

    def installed_distribution(name: str) -> PathDistribution:
        assert name == "whenever"
        return PathDistribution(metadata)

    monkeypatch.setattr(typing_setup, "distribution", installed_distribution)
    return metadata


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_patch_real_stub_preserves_all_other_public_api() -> None:
    source = _installed_source()
    result = typing_setup.patch_stub(source)
    module = ast.parse(result)
    private_types = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "_SystemTimezone"
    ]
    assert len(private_types) == 1
    private_type = private_types[0]
    assert {ast.unparse(node) for node in private_type.decorator_list} == {
        "final",
        "type_check_only",
    }
    constants = [
        node
        for node in module.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "SYSTEM_TZ"
    ]
    assert len(constants) == 1
    assert ast.unparse(constants[0].annotation) == "Final[_SystemTimezone]"
    assert "sentinel(" not in result
    assert "str | SYSTEM_TZ" not in result
    assert result.count("str | _SystemTimezone") == source.count("str | SYSTEM_TZ")

    # Remove only the new declaration and undo its annotation substitutions.
    # Every other nonblank line, including comments and overloads, must survive.
    removed: set[int] = set()
    for node in (private_type, constants[0]):
        start = node.lineno
        if isinstance(node, ast.ClassDef):
            start = min(start, *(item.lineno for item in node.decorator_list))
        assert node.end_lineno is not None
        removed.update(range(start, node.end_lineno + 1))
    retained = "\n".join(
        line
        for index, line in enumerate(result.splitlines(), 1)
        if index not in removed
    ).replace("str | _SystemTimezone", "str | SYSTEM_TZ")
    expected = source.replace(
        "from typing_extensions import Self, deprecated, sentinel",
        "from typing_extensions import Self, deprecated",
    ).replace('SYSTEM_TZ = sentinel("SYSTEM_TZ")', "")
    assert [line for line in retained.splitlines() if line.strip()] == [
        line for line in expected.splitlines() if line.strip()
    ]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            "from typing_extensions import Self, deprecated, sentinel",
            "from typing_extensions import Self, deprecated",
        ),
        ('SYSTEM_TZ = sentinel("SYSTEM_TZ")', "SYSTEM_TZ = object()"),
        ("str | SYSTEM_TZ", "str | object"),
        (
            'SYSTEM_TZ = sentinel("SYSTEM_TZ")',
            'SYSTEM_TZ = sentinel("SYSTEM_TZ")\nSYSTEM_TZ = sentinel("SYSTEM_TZ")',
        ),
    ],
)
def test_patch_rejects_drift_in_reviewed_sentinel_contract(
    before: str, after: str
) -> None:
    source = _installed_source()
    assert before in source
    with pytest.raises(ValueError):
        typing_setup.patch_stub(source.replace(before, after, 1))


def test_prepare_is_reproducible_and_never_copies_or_changes_runtime(
    tmp_path: Path, installed_whenever: Path
) -> None:
    source = installed_whenever.parent / "whenever"
    source_before = _files(source)
    assert typing_setup.prepare_whenever_typing(tmp_path)
    target = tmp_path / "typings/whenever"
    first = _files(target)
    assert (target / typing_setup.MARKER).is_file()
    assert (target / "__init__.pyi").read_text(encoding="utf-8") == (
        typing_setup.patch_stub((source / "__init__.pyi").read_text(encoding="utf-8"))
    )
    assert (installed_whenever / "licenses/LICENSE").read_bytes() in first.values()
    assert not (target / "__init__.py").exists()
    assert not (target / "_whenever.pyd").exists()
    assert typing_setup.prepare_whenever_typing(tmp_path)
    assert _files(target) == first
    assert _files(source) == source_before


def test_unsupported_version_removes_only_recognized_generated_output(
    tmp_path: Path, installed_whenever: Path
) -> None:
    assert typing_setup.prepare_whenever_typing(tmp_path)
    other = tmp_path / "typings/other"
    other.mkdir()
    (other / "keep.pyi").write_text("keep: str\n")
    (installed_whenever / "METADATA").write_text(
        "Name: whenever\nVersion: 0.11.1\n", encoding="utf-8"
    )
    assert not typing_setup.prepare_whenever_typing(tmp_path)
    assert not (tmp_path / "typings/whenever").exists()
    assert (other / "keep.pyi").read_text() == "keep: str\n"
    assert not typing_setup.prepare_whenever_typing(tmp_path)


@pytest.mark.parametrize("version", ["0.11.0", "0.11.1"])
@pytest.mark.parametrize("ownership", ["unmarked", "wrong-marker", "extra-file"])
def test_prepare_preserves_unowned_or_unexpected_output(
    tmp_path: Path, installed_whenever: Path, version: str, ownership: str
) -> None:
    target = tmp_path / "typings/whenever"
    if ownership == "unmarked":
        target.mkdir(parents=True)
        (target / "custom.pyi").write_text("keep: str\n")
    else:
        assert typing_setup.prepare_whenever_typing(tmp_path)
        if ownership == "wrong-marker":
            (target / typing_setup.MARKER).write_text("not this generator\n")
        else:
            (target / "custom.pyi").write_text("keep: str\n")
    before = _files(target)
    (installed_whenever / "METADATA").write_text(
        f"Name: whenever\nVersion: {version}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        typing_setup.prepare_whenever_typing(tmp_path)
    assert _files(target) == before


def test_drift_does_not_destroy_an_existing_generated_overlay(
    tmp_path: Path, installed_whenever: Path
) -> None:
    assert typing_setup.prepare_whenever_typing(tmp_path)
    target = tmp_path / "typings/whenever"
    before = _files(target)
    source = installed_whenever.parent / "whenever/__init__.pyi"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            'SYSTEM_TZ = sentinel("SYSTEM_TZ")', "SYSTEM_TZ = object()"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        typing_setup.prepare_whenever_typing(tmp_path)
    assert _files(target) == before


def test_mypy_accepts_system_timezone_and_rejects_arbitrary_values(
    tmp_path: Path,
) -> None:
    if not typing_setup.prepare_whenever_typing(tmp_path):
        pytest.skip("This Whenever version uses its bundled type information")
    sample = tmp_path / "whenever_contract.py"
    valid = """from typing import assert_type
from whenever import SYSTEM_TZ, Date, Instant, PlainDateTime, ZonedDateTime

instant = Instant.from_utc(2026, 11, 6)
wall = PlainDateTime(2026, 11, 1, 1, 30)
assert_type(Date.today(SYSTEM_TZ), Date)
assert_type(instant.to_tz(SYSTEM_TZ), ZonedDateTime)
assert_type(instant.to_tz("America/New_York"), ZonedDateTime)
assert_type(wall.assume_tz(SYSTEM_TZ, disambiguation="compatible"), ZonedDateTime)
assert_type(ZonedDateTime.now(SYSTEM_TZ), ZonedDateTime)
"""
    sample.write_text(valid, encoding="utf-8")
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
    sample.write_text(
        valid + "\nDate.today(42)\ninstant.to_tz(object())\nZonedDateTime.now(None)\n",
        encoding="utf-8",
    )
    bad = subprocess.run(
        command,
        cwd=typing_setup.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert bad.stdout.count("[arg-type]") == 3, bad.stdout + bad.stderr
    assert bad.stdout.count(": error:") == 3, bad.stdout + bad.stderr
