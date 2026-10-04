"""Python update authority follows the installed module and its interpreter."""

# These tests intentionally exercise internal install evidence and lease ownership.
# pyright: strict, reportPrivateUsage=false

import hashlib
import json
import os
import shutil
import site
import sys
import sysconfig
from dataclasses import replace
from importlib import metadata
from importlib.metadata import PathDistribution
from pathlib import Path

import pytest

from iOpenPod.app.updates import bootstrap, platform
from iOpenPod.app.updates import python_installation as python
from iOpenPod.app.updates.backend import InstallChannel
from iOpenPod.app.updates.pypi import PyPIBackend
from storage.host_usage import HostInstallationLease


@pytest.fixture(name="installed_python")
def python_installation_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> python.PythonInstallation:
    prefix = tmp_path / "venv"
    packages = prefix / "Lib/site-packages"
    record = packages / "iopenpod-2.0.4.dist-info"
    record.mkdir(parents=True)
    module = packages / "iOpenPod/app/updates/python_installation.py"
    module.parent.mkdir(parents=True)
    module.write_text("# installed module\n")
    (record / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: iOpenPod\nVersion: 2.0.4\n"
    )
    (record / "INSTALLER").write_text("uv\n")
    (record / "RECORD").write_text(
        "iOpenPod/app/updates/python_installation.py,,\n"
        "iopenpod-2.0.4.dist-info/METADATA,,\n"
    )
    interpreter = prefix / "python.exe"
    interpreter.write_bytes(b"interpreter")

    def distribution(_name: str) -> PathDistribution:
        return PathDistribution(record)

    def configuration_path(name: str) -> str:
        return str(packages if name in {"purelib", "platlib"} else tmp_path / "stdlib")

    monkeypatch.setattr(python, "__file__", str(module))
    monkeypatch.setattr(metadata, "distribution", distribution)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "base"))
    monkeypatch.setattr(sys, "executable", str(interpreter))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        site, "getusersitepackages", lambda: str(tmp_path / "user-site")
    )
    monkeypatch.setattr(sysconfig, "get_path", configuration_path)
    (tmp_path / "stdlib").mkdir()
    result = python.running_python_installation()
    assert result is not None and not result.restriction
    return result


def test_package_detection_uses_record_and_exact_running_module(
    installed_python: python.PythonInstallation,
) -> None:
    assert installed_python.version == "2.0.4"
    assert (
        installed_python.metadata_sha256
        == hashlib.sha256(installed_python.metadata.read_bytes()).hexdigest()
    )
    assert python.running_python_installation() == installed_python


def test_python_channel_composes_the_pypi_backend(
    installed_python: python.PythonInstallation,
) -> None:
    assert platform._unpackaged_channel() is InstallChannel.PYPI
    provider = platform._standalone_provider(InstallChannel.PYPI)
    assert isinstance(provider.backend, PyPIBackend)
    assert provider.display_name == "PyPI" and provider.staged_download
    provider.backend.close()


def test_python_launch_holds_a_shared_installation_lease(
    installed_python: python.PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "running_installation", lambda: None)
    monkeypatch.setattr(bootstrap, "_lease", None)
    try:
        bootstrap.prepare_launch(None)
        with (
            pytest.raises(OSError),
            HostInstallationLease(installed_python.packages, exclusive=True),
        ):
            pytest.fail("An updater replaced an installation still used by an app")
    finally:
        if bootstrap._lease is not None:
            bootstrap._lease.close()


@pytest.mark.parametrize(
    "origin",
    [
        {"url": "file:///checkout", "dir_info": {"editable": True}},
        {"url": "file:///downloads/iopenpod.whl", "archive_info": {}},
        {"url": "https://other.example/iopenpod.whl", "archive_info": {}},
        {"url": "https://files.pythonhosted.org.evil.test/iopenpod.whl"},
    ],
)
def test_editable_local_and_alternate_origins_are_not_pypi(
    installed_python: python.PythonInstallation,
    origin: dict[str, object],
) -> None:
    (installed_python.metadata.parent / "direct_url.json").write_text(
        json.dumps(origin)
    )
    assert python.running_python_installation() is None


def test_verified_official_direct_wheel_remains_updatable(
    installed_python: python.PythonInstallation,
) -> None:
    (installed_python.metadata.parent / "direct_url.json").write_text(
        json.dumps(
            {
                "url": "https://files.pythonhosted.org/packages/iopenpod-2.0.4-py3-none-any.whl",
                "archive_info": {"hashes": {"sha256": "a" * 64}},
            }
        )
    )
    assert python.running_python_installation() == installed_python


def test_source_shadow_cannot_mutate_an_installed_copy(
    installed_python: python.PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        python, "__file__", str(tmp_path / "checkout/python_installation.py")
    )
    assert python.running_python_installation() is None


@pytest.mark.parametrize("installer", ["", "deb", "conda", "brew"])
def test_other_installers_keep_ownership(
    installed_python: python.PythonInstallation, installer: str
) -> None:
    (installed_python.metadata.parent / "INSTALLER").write_text(installer)
    assert python.running_python_installation() is None


def test_pipx_keeps_ownership(
    installed_python: python.PythonInstallation,
) -> None:
    (installed_python.prefix / "pipx_metadata.json").write_text("managed")
    detected = python.running_python_installation()
    assert detected is not None and "tool manager" in detected.restriction
    with pytest.raises(ValueError, match="tool manager"):
        python.installer_command(detected)


def test_custom_uv_tool_receipts_get_manual_guidance(
    installed_python: python.PythonInstallation,
) -> None:
    (installed_python.prefix / "uv-receipt.toml").write_text("unrecognized receipt")
    detected = python.running_python_installation()
    assert detected is not None and "Use UV" in detected.restriction
    with pytest.raises(ValueError, match="Use UV"):
        python.installer_command(detected)


@pytest.mark.parametrize("options", ["", "[tool.options]\nno-build = true"])
def test_standard_uv_tool_scope_preserves_its_directories(
    tmp_path: Path,
    options: str,
) -> None:
    prefix, binary = tmp_path / "tools/iopenpod", tmp_path / "bin"
    prefix.mkdir(parents=True)
    binary.mkdir()
    receipt = prefix / "uv-receipt.toml"
    receipt.write_text(
        '[tool]\nrequirements = [{ name = "iopenpod" }]\n'
        'entrypoints = [{name = "iopenpod", install-path = "'
        + (binary / "iopenpod.exe").as_posix()
        + '"}]\n'
        + options
    )
    directory, executables, digest = python._uv_tool_scope(prefix)
    assert Path(directory) == prefix.parent and Path(executables) == binary
    assert digest == hashlib.sha256(receipt.read_bytes()).hexdigest()
    receipt.write_text(
        receipt.read_text().replace(
            'name = "iopenpod"', 'name = "iopenpod", specifier = "==2.0.4"', 1
        )
    )
    with pytest.raises(ValueError, match="Customized"):
        python._uv_tool_scope(prefix)


def test_uv_tool_update_uses_its_owner_and_requires_uv(
    installed_python: python.PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = replace(installed_python, tool_directory="/tools", tool_bin="/bin")
    command = python.install_command(
        installation, ("uv",), "https://files.pythonhosted.org/app.whl", "a" * 64
    )
    assert command[3:5] == ["tool", "upgrade"]
    assert "--no-build" in command and "--python" not in command
    preview = python.install_command(
        installation,
        ("uv",),
        "https://files.pythonhosted.org/app.whl",
        "a" * 64,
        dry_run=True,
    )
    assert "--dry-run" in preview and "pip" in preview

    def missing_executable(_name: str) -> None:
        return None

    monkeypatch.setattr(shutil, "which", missing_executable)
    with pytest.raises(ValueError, match="UV is required"):
        python.installer_command(installation)


def test_externally_managed_base_python_is_not_modified(
    installed_python: python.PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys, "base_prefix", sys.prefix)
    (tmp_path / "stdlib/EXTERNALLY-MANAGED").write_text("managed")
    detected = python.running_python_installation()
    assert detected is not None and "externally managed" in detected.restriction


def test_venv_does_not_inherit_base_python_management_marker(
    installed_python: python.PythonInstallation,
    tmp_path: Path,
) -> None:
    (tmp_path / "stdlib/EXTERNALLY-MANAGED").write_text("managed")
    assert python.running_python_installation() == installed_python


def test_read_only_install_has_no_automatic_installer(
    installed_python: python.PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read_only(_path: object, _mode: int) -> bool:
        return False

    monkeypatch.setattr(os, "access", read_only)
    detected = python.running_python_installation()
    assert detected is not None and "read-only" in detected.restriction


def test_uv_command_targets_this_interpreter_without_ambient_configuration(
    installed_python: python.PythonInstallation,
) -> None:
    command = python.install_command(
        installed_python,
        ("/tools/uv",),
        "https://files.pythonhosted.org/app.whl",
        "a" * 64,
    )
    assert command[command.index("--python") + 1] == str(installed_python.interpreter)
    assert "--no-config" in command and "--no-python-downloads" in command
    assert command[command.index("--default-index") + 1] == "https://pypi.org/simple"
    assert (
        command[-1]
        == "iOpenPod @ https://files.pythonhosted.org/app.whl#sha256=" + "a" * 64
    )
    assert "--system" not in command and "--break-system-packages" not in command


def test_pip_user_install_keeps_its_scope_and_exact_hash(
    installed_python: python.PythonInstallation,
) -> None:
    installation = replace(installed_python, user_site=True)
    manager = (*installation.launch, "-m", "pip")
    command = python.install_command(
        installation,
        manager,
        "https://files.pythonhosted.org/app.whl",
        "b" * 64,
        dry_run=True,
    )
    assert command[:5] == list(manager)
    assert "--isolated" in command and "--user" in command and "--dry-run" in command
    assert "--only-binary=:all:" in command


def test_update_environment_cannot_redirect_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "UV_PYTHON",
        "UV_INDEX_URL",
        "PIP_TARGET",
        "PIP_EXTRA_INDEX_URL",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ):
        monkeypatch.setenv(name, "unexpected")
    environment = python.update_environment()
    assert not any(
        name in environment
        for name in (
            "UV_PYTHON",
            "UV_INDEX_URL",
            "PIP_TARGET",
            "PIP_EXTRA_INDEX_URL",
            "PYTHONPATH",
            "VIRTUAL_ENV",
        )
    )
    assert environment["PIP_CONFIG_FILE"] == os.devnull
