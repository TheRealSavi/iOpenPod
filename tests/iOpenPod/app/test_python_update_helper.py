"""Python installation starts only after authorized shutdown and exclusive use."""

# The helper's request validation and handoff are deliberately tested at their seams.
# pyright: strict, reportPrivateUsage=false

import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from threading import Event, Thread
from zipfile import ZipFile

import pytest
from tests.iOpenPod.app.test_python_installation import (
    python_installation_fixture as python_installation_fixture,
)
from tests.iOpenPod.app.version_fixtures import CURRENT_VERSION, PREVIOUS_VERSION

from iOpenPod.app.updates import python_helper as helper
from iOpenPod.app.updates.processes import ParentProcess
from iOpenPod.app.updates.pypi import PythonWheel
from iOpenPod.app.updates.python_installation import (
    PythonInstallation,
    _uv_tool_scope,
    install_command,
    run_command,
    update_environment,
)
from storage.host_usage import HostInstallationLease


@pytest.fixture
def operation(
    tmp_path: Path,
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, PythonWheel]:
    directory = tmp_path / "python-update-test"
    directory.mkdir()
    wheel = PythonWheel(
        CURRENT_VERSION,
        f"iopenpod-{CURRENT_VERSION}-py3-none-any.whl",
        f"https://files.pythonhosted.org/packages/iopenpod-{CURRENT_VERSION}-py3-none-any.whl",
        5,
        hashlib.sha256(b"wheel").hexdigest(),
    )
    (directory / wheel.filename).write_bytes(b"wheel")

    def manager(_installation: PythonInstallation) -> tuple[str, ...]:
        return ("/tools/uv",)

    monkeypatch.setattr(helper, "installer_command", manager)
    (directory / "request.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "nonce": "a" * 32,
                "parent": 42,
                "installation": helper._identity(installed_python),
                "manager": ["/tools/uv"],
                "wheel": asdict(wheel),
            }
        )
    )
    return directory, wheel


def test_request_is_bound_to_current_interpreter_and_installed_version(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
) -> None:
    directory, wheel = operation
    installation, selected, manager, nonce, parent = helper._request(directory)
    assert installation == installed_python and selected == wheel
    assert manager == ("/tools/uv",) and nonce == "a" * 32 and parent == 42
    data = json.loads((directory / "request.json").read_bytes())
    data["installation"]["interpreter"] = "another-python"
    (directory / "request.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="interpreter"):
        helper._request(directory)


def test_changed_wheel_never_reaches_a_package_manager(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, wheel = operation
    calls: list[list[str]] = []

    def record(arguments: list[str], *_args: object, **_kwargs: object) -> None:
        calls.append(arguments)

    monkeypatch.setattr(helper, "run_command", record)
    (directory / wheel.filename).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        helper.perform_update(installed_python, wheel, ("/tools/uv",), directory)
    assert not calls


def test_other_app_instance_blocks_replacement(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, wheel = operation
    calls: list[list[str]] = []

    def record(arguments: list[str], *_args: object, **_kwargs: object) -> None:
        calls.append(arguments)

    monkeypatch.setattr(helper, "run_command", record)
    with HostInstallationLease(installed_python.packages), pytest.raises(OSError):
        helper.perform_update(installed_python, wheel, ("/tools/uv",), directory)
    assert not calls


def test_installed_version_and_smoke_check_follow_package_manager_success(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, wheel = operation
    calls: list[list[str]] = []

    def run(
        arguments: list[str],
        _log: Path,
        _cancel: Event,
        *,
        timeout: float = 1800,
        environment: dict[str, str] | None = None,
    ) -> None:
        with pytest.raises(OSError), HostInstallationLease(installed_python.packages):
            pytest.fail("Installer lost exclusive ownership")
        calls.append(arguments)

    monkeypatch.setattr(helper, "run_command", run)
    helper.perform_update(installed_python, wheel, ("/tools/uv",), directory)
    assert len(calls) == 3
    assert calls[0][-1].endswith("#sha256=" + wheel.sha256)
    assert calls[1][-1] == CURRENT_VERSION
    assert calls[2][-3:] == ["-m", "iOpenPod", "--smoke-test"]
    with HostInstallationLease(installed_python.packages):
        pass


def test_install_failure_cannot_run_success_verification(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fail(
        arguments: list[str],
        _log: Path,
        _cancel: Event,
        *,
        timeout: float = 1800,
        environment: dict[str, str] | None = None,
    ) -> None:
        calls.append(arguments)
        raise RuntimeError("package manager refused")

    monkeypatch.setattr(helper, "run_command", fail)
    with pytest.raises(RuntimeError, match="refused"):
        helper.perform_update(
            installed_python, operation[1], ("/tools/uv",), operation[0]
        )
    assert len(calls) == 1


@pytest.mark.parametrize("authorized", [True, False])
def test_actual_parent_exit_requires_explicit_authorization(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
    authorized: bool,
) -> None:
    directory, _ = operation
    states = iter([False, True])
    closed: list[bool] = []

    class Parent:
        def __init__(self, pid: int, executable: Path) -> None:
            assert pid == 42 and executable == installed_python.interpreter

        def exited(self) -> bool:
            return next(states)

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(helper, "ParentProcess", Parent)

    def no_sleep(_seconds: float) -> None:
        pass

    monkeypatch.setattr(time, "sleep", no_sleep)
    if authorized:
        (directory / "authorized").write_text("a" * 32)
        helper._wait_for_shutdown(directory, "a" * 32, 42, installed_python.interpreter)
    else:
        with pytest.raises(ValueError, match="without authorizing"):
            helper._wait_for_shutdown(
                directory, "a" * 32, 42, installed_python.interpreter
            )
    assert closed == [True]
    assert (directory / "ready").read_text() == "a" * 32


@pytest.mark.parametrize("failure", [False, True])
def test_helper_records_terminal_result_and_relaunches_after_releasing_ownership(
    operation: tuple[Path, PythonWheel],
    installed_python: PythonInstallation,
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    directory, _ = operation
    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["python_helper", str(directory)])
    monkeypatch.setattr(
        PythonInstallation,
        "result_path",
        property(lambda _self: directory / "result.json"),
    )

    def shutdown(*_args: object) -> None:
        calls.append("shutdown")

    monkeypatch.setattr(helper, "_wait_for_shutdown", shutdown)

    def perform(*_args: object) -> None:
        calls.append("install")
        if failure:
            raise RuntimeError("Package replacement failed")

    def spawn(arguments: list[str], _log: Path) -> None:
        calls.append("relaunch")
        assert arguments == [*installed_python.launch, "-m", "iOpenPod"]

    monkeypatch.setattr(helper, "perform_update", perform)
    monkeypatch.setattr(helper, "_spawn", spawn)
    assert helper.main() == (1 if failure else 0)
    result = json.loads(installed_python.result_path.read_bytes())
    assert result["outcome"] == ("failed" if failure else "completed")
    assert calls == ["shutdown", "install", "relaunch"]


def _wheel(directory: Path, version: str) -> Path:
    path = directory / f"iopenpod-{version}-py3-none-any.whl"
    info = f"iopenpod-{version}.dist-info"
    files = {
        "iOpenPod/__init__.py": "",
        "iOpenPod/__main__.py": "import sys\nassert sys.argv[1:] == ['--smoke-test']\n",
        f"{info}/METADATA": f"Metadata-Version: 2.4\nName: iOpenPod\nVersion: {version}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/entry_points.txt": "[gui_scripts]\niopenpod = iOpenPod:main\n",
    }
    files[f"{info}/RECORD"] = "".join(
        f"{name},,\n" for name in [*files, f"{info}/RECORD"]
    )
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


@pytest.mark.parametrize("tool", [False, True])
def test_real_package_replacement_in_a_disposable_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: bool,
) -> None:
    """Exercise the installed-version and smoke checks against a real UV upgrade."""
    uv = shutil.which("uv")
    assert uv is not None
    prefix = tmp_path / "tools/iopenpod" if tool else tmp_path / "environment"
    if not tool:
        subprocess.run(
            [uv, "venv", "--no-config", "--python", sys.executable, str(prefix)],
            check=True,
            capture_output=True,
        )
    executable = prefix / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    old = _wheel(tmp_path, PREVIOUS_VERSION)
    if tool:
        environment = update_environment()
        environment.update(
            UV_TOOL_DIR=str(prefix.parent), UV_TOOL_BIN_DIR=str(tmp_path / "bin")
        )
        subprocess.run(
            [
                uv,
                "--no-config",
                "tool",
                "install",
                "iopenpod",
                "--python",
                sys.executable,
                "--no-index",
                "--find-links",
                str(tmp_path),
            ],
            env=environment,
            check=True,
            capture_output=True,
        )
        # Fixture wheels are found offline; remove that fixture-only option to
        # exercise the same receipt policy as a standard public index install.
        receipt = prefix / "uv-receipt.toml"
        receipt.write_text(receipt.read_text().split("[tool.options]")[0])
    else:
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(executable),
                "--no-index",
                "--no-deps",
                str(old),
            ],
            check=True,
            capture_output=True,
        )
    packages = Path(
        subprocess.check_output(
            [
                str(executable),
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            text=True,
        ).strip()
    )
    metadata = packages / f"iopenpod-{PREVIOUS_VERSION}.dist-info/METADATA"
    installation = PythonInstallation(
        PREVIOUS_VERSION,
        executable,
        prefix,
        packages,
        metadata,
        hashlib.sha256(metadata.read_bytes()).hexdigest(),
        tool_directory=str(prefix.parent) if tool else "",
        tool_bin=str(tmp_path / "bin") if tool else "",
        tool_receipt_sha256=_uv_tool_scope(prefix)[2] if tool else "",
    )
    directory = tmp_path / "python-update-real"
    directory.mkdir()
    new = _wheel(directory, CURRENT_VERSION)
    wheel = PythonWheel(
        CURRENT_VERSION,
        new.name,
        "https://files.pythonhosted.org/unused",
        new.stat().st_size,
        hashlib.sha256(new.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(helper, "running_python_installation", lambda: installation)

    # Production command construction is separately checked for the exact public
    # URL/hash and interpreter. Here the real manager consumes an offline fixture.
    def offline_command(*_args: object) -> list[str]:
        if tool:
            return install_command(installation, (uv,), new.as_uri(), wheel.sha256)
        return [
            uv,
            "pip",
            "install",
            "--python",
            str(executable),
            "--no-index",
            "--no-deps",
            str(new),
        ]

    monkeypatch.setattr(helper, "install_command", offline_command)
    helper.perform_update(installation, wheel, (uv,), directory)
    assert (packages / f"iopenpod-{CURRENT_VERSION}.dist-info/METADATA").is_file()
    assert not metadata.exists()
    assert (directory / "installer.log").is_file()
    if tool:
        assert _uv_tool_scope(prefix)[:2] == (str(prefix.parent), str(tmp_path / "bin"))


def test_real_python_parent_handoff_waits_for_authorized_exit(tmp_path: Path) -> None:
    """Catch venv launcher/base-interpreter identity differences on Windows."""
    child = """
import sys
from pathlib import Path
from iOpenPod.app.updates.python_helper import _wait_for_shutdown, _process_executable
assert not any(name.startswith(('Crypto.', 'PySide6.', 'numpy.')) for name in sys.modules)
directory = Path(sys.argv[1])
_wait_for_shutdown(directory, 'a' * 32, int(sys.argv[2]), _process_executable())
(directory / 'finished').write_text('parent exited')
"""
    parent = """
import os, subprocess, sys, time
from pathlib import Path
directory = Path(sys.argv[1])
with (directory / 'child.log').open('wb') as log:
    child = subprocess.Popen([sys.executable, '-c', sys.argv[2], str(directory),
                              str(os.getpid())], stdout=log, stderr=log)
    deadline = time.monotonic() + 10
    while not (directory / 'ready').exists():
        if child.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError('Helper did not become ready')
        time.sleep(0.01)
    assert not (directory / 'finished').exists()
    (directory / 'authorized').write_text('a' * 32)
"""
    result = subprocess.run(
        [sys.executable, "-c", parent, str(tmp_path), child],
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        result.stderr.decode(),
        (tmp_path / "child.log").read_text(),
    )
    deadline = time.monotonic() + 10
    while not (tmp_path / "finished").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (tmp_path / "finished").read_text() == "parent exited"


@pytest.mark.skipif(
    sys.platform not in {"win32", "linux"}, reason="Native process handle observation"
)
def test_cancel_stops_package_command_and_its_descendants(tmp_path: Path) -> None:
    marker = tmp_path / "descendant.pid"
    log = tmp_path / "installer.log"
    cancel = Event()
    handles: list[ParentProcess] = []
    errors: list[Exception] = []
    descendant = (
        "import os,sys,time; from pathlib import Path; "
        "print('started',flush=True); Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    command = "import subprocess,sys; subprocess.run([sys.executable,'-c',sys.argv[1],sys.argv[2]])"

    def observe() -> None:
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            handles.append(
                ParentProcess(int(marker.read_text()), helper._process_executable())
            )
        except Exception as error:
            errors.append(error)
        finally:
            cancel.set()

    observer = Thread(target=observe)
    observer.start()
    try:
        with pytest.raises(InterruptedError, match="canceled"):
            run_command(
                [sys.executable, "-c", command, descendant, str(marker)],
                log,
                cancel,
                timeout=15,
            )
        observer.join(timeout=15)
        assert not errors and len(handles) == 1
        deadline = time.monotonic() + 5
        while not handles[0].exited() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert handles[0].exited()
        assert "started" in log.read_text()
    finally:
        observer.join(timeout=15)
        for handle in handles:
            handle.close()
