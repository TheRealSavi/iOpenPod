"""New package installs become visible without changing global PATH."""

import os
import platform
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from storage import host_tools


def test_path_takes_precedence_over_package_locations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def which(name: str) -> str:
        return "C:/custom/" + name

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(host_tools, "executable_directories", lambda: ())
    assert host_tools.find_host_executable("ffmpeg") is not None


@pytest.mark.parametrize("system", ["win32", "darwin", "linux"])
def test_package_locations_are_found_without_path_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    def which(_name: str) -> None:
        return None

    original_path = os.environ.get("PATH")
    executable = tmp_path / ("ffmpeg.exe" if system == "win32" else "ffmpeg")
    executable.write_bytes(b"test executable")
    executable.chmod(0o755)
    monkeypatch.setattr(host_tools, "sys", SimpleNamespace(platform=system))
    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(host_tools, "executable_directories", lambda: (tmp_path,))
    assert host_tools.find_host_executable("ffmpeg") == str(executable)
    assert host_tools.find_host_executable("fpcalc") is None
    assert os.environ.get("PATH") == original_path


@pytest.mark.parametrize("name", ["", "..", "../ffmpeg", r"bin\ffmpeg"])
def test_discovery_accepts_only_executable_names(name: str) -> None:
    with pytest.raises(ValueError):
        host_tools.find_host_executable(name)


def test_windows_package_aliases_are_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(host_tools, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert tmp_path / "Microsoft/WinGet/Links" in host_tools.executable_directories()


@pytest.mark.parametrize(
    ("machine", "prefix"), [("arm64", "/opt/homebrew"), ("x86_64", "/usr/local")]
)
def test_mac_gui_searches_native_homebrew_first(
    monkeypatch: pytest.MonkeyPatch, machine: str, prefix: str
) -> None:
    monkeypatch.setattr(host_tools, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert host_tools.executable_directories()[0] == Path(prefix) / "bin"


@pytest.mark.parametrize(
    ("machine", "installed", "selected", "architecture"),
    [
        ("arm64", {"/opt/homebrew/bin/brew"}, "/opt/homebrew/bin/brew", "arm64"),
        ("x86_64", {"/usr/local/bin/brew"}, "/usr/local/bin/brew", "x86_64"),
        (
            "x86_64",
            {"/opt/homebrew/bin/brew", "/usr/local/bin/brew"},
            "/opt/homebrew/bin/brew",
            "arm64",
        ),
    ],
)
def test_mac_environment_observes_native_brew_even_under_rosetta(
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
    installed: set[str],
    selected: str,
    architecture: str,
) -> None:
    def is_file(path: Path) -> bool:
        return path.as_posix() in installed

    def access(_path: Path, _mode: int) -> bool:
        return True

    monkeypatch.setattr(host_tools, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(os, "access", access)
    host = host_tools.inspect_tool_environment()
    assert host.executable("brew") == str(Path(selected))
    assert host.architecture == architecture


def test_linux_observations_keep_distribution_and_confinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def find_executable(name: str) -> str:
        return "/usr/bin/" + name

    monkeypatch.setattr(host_tools, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        platform,
        "freedesktop_os_release",
        lambda: {"ID": "mint", "ID_LIKE": "ubuntu debian"},
    )
    monkeypatch.setattr(host_tools, "find_host_executable", find_executable)
    monkeypatch.setenv("FLATPAK_ID", "test.application")
    host = host_tools.inspect_tool_environment()
    assert host.distribution_ids == frozenset({"mint", "ubuntu", "debian"})
    assert host.confined
    assert host.executable("apt-get") == "/usr/bin/apt-get"
