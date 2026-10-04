"""Acknowledge Python update handoff, wait for shutdown, install, and relaunch.

The helper loads its code before the parent exits. Package replacement happens in
a separate package-manager process, with no Qt or device operations in this helper.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

from storage.host_files import AtomicHostFile
from storage.host_installation import (
    durable_write,
    file_identity,
    private_directory,
    require_plain_path,
)
from storage.host_usage import HostInstallationLease

from .processes import ParentProcess
from .pypi import PythonWheel, select_release
from .python_installation import (
    PythonInstallation,
    install_command,
    installer_command,
    run_command,
    running_python_installation,
    update_environment,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .transport import UpdateTransport


def _identity(installation: PythonInstallation) -> dict[str, str | bool]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(installation).items()
    }


def _matches(directory: Path, name: str, nonce: str) -> bool:
    path = require_plain_path(directory / name)
    return path.is_file() and path.stat().st_size < 128 and path.read_text() == nonce


def _spawn(arguments: list[str], log: Path) -> subprocess.Popen[bytes]:
    with log.open("ab") as output:
        return subprocess.Popen(
            arguments,
            env=update_environment(),
            cwd=log.parent,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            start_new_session=sys.platform != "win32",
        )


class PythonInstaller:
    def __init__(self, installation: PythonInstallation) -> None:
        self.installation = installation
        self._manager = installer_command(installation)
        self._directory: Path | None = None
        self._wheel: PythonWheel | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._nonce = uuid.uuid4().hex
        self._authorized = False
        self._cancel: Event | None = None

    def stage(
        self,
        wheel: PythonWheel,
        transport: UpdateTransport,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None:
        self._cancel = cancel
        parent = self.installation.result_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        directory = private_directory(parent, "python-update-")
        self._directory = directory
        transport.download(wheel, directory / wheel.filename, cancel, progress)
        # Resolve and prepare packages while the app is still usable. No mutation.
        run_command(
            install_command(
                self.installation, self._manager, wheel.url, wheel.sha256, dry_run=True
            ),
            directory / "installer.log",
            cancel,
            timeout=300,
        )
        self._wheel = wheel

    def install(self, wheel: PythonWheel) -> None:
        directory = self._directory
        if directory is None or self._wheel != wheel or self._cancel is None:
            raise RuntimeError("Download and verify the Python update first")
        if self._cancel.is_set():
            raise InterruptedError("Python update canceled")
        if running_python_installation() != self.installation:
            raise ValueError("The Python installation changed after download")
        _verify_wheel(directory, wheel)
        durable_write(
            directory / "request.json",
            json.dumps(
                {
                    "schema": 1,
                    "nonce": self._nonce,
                    "parent": os.getpid(),
                    "installation": _identity(self.installation),
                    "manager": list(self._manager),
                    "wheel": asdict(wheel),
                }
            ).encode(),
        )
        self._process = _spawn(
            [
                *self.installation.launch,
                "-m",
                "iOpenPod.app.updates.python_helper",
                str(directory),
            ],
            directory / "helper.log",
        )
        deadline = time.monotonic() + 30
        while not _matches(directory, "ready", self._nonce):
            if self._cancel.wait(0.05):
                raise InterruptedError("Python update canceled")
            if self._process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Python update helper did not become ready. See {directory / 'helper.log'}"
                )

    def complete_handoff(self) -> None:
        if (
            self._directory is None
            or self._process is None
            or self._process.poll() is not None
        ):
            raise RuntimeError("The Python installer is no longer available")
        durable_write(self._directory / "authorized", self._nonce.encode())
        self._authorized = True

    def close(self) -> None:
        if self._directory is not None and not self._authorized:
            durable_write(self._directory / "canceled", self._nonce.encode())


def _verify_wheel(directory: Path, wheel: PythonWheel) -> None:
    identity = file_identity(directory / wheel.filename)
    if identity.size != wheel.size or identity.sha256 != wheel.sha256:
        raise ValueError("The retained Python wheel changed after download")


def _request(
    directory: Path,
) -> tuple[PythonInstallation, PythonWheel, tuple[str, ...], str, int]:
    require_plain_path(directory)
    if not directory.name.startswith("python-update-"):
        raise ValueError("Invalid Python update operation directory")
    path = require_plain_path(directory / "request.json")
    if path.stat().st_size > 16 * 1024:
        raise ValueError("Invalid Python update request size")
    raw: object = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise ValueError("Invalid Python update request")
    value = cast("dict[str, object]", raw)
    installation = running_python_installation()
    if installation is None or value.get("installation") != _identity(installation):
        raise ValueError(
            "The requested Python installation is not this interpreter's installed application"
        )
    manager = installer_command(installation)
    if value.get("schema") != 1 or value.get("manager") != list(manager):
        raise ValueError("The Python package manager changed")
    nonce, parent = value.get("nonce"), value.get("parent")
    if (
        not isinstance(nonce, str)
        or len(nonce) != 32
        or any(character not in "0123456789abcdef" for character in nonce)
        or type(parent) is not int
        or parent <= 0
    ):
        raise ValueError("Invalid Python update handoff identity")
    wheel_data = value.get("wheel")
    if not isinstance(wheel_data, dict):
        raise ValueError("Missing Python update wheel")
    fields = cast("dict[str, object]", wheel_data)
    selected = select_release(
        json.dumps(
            {
                "name": "iopenpod",
                "meta": {"api-version": "1.0"},
                "files": [
                    {
                        "filename": fields.get("filename"),
                        "url": fields.get("url"),
                        "size": fields.get("size"),
                        "hashes": {"sha256": fields.get("sha256")},
                        "yanked": False,
                    }
                ],
            }
        ).encode()
    ).wheel
    if selected is None or fields != asdict(selected):
        raise ValueError("Invalid selected Python wheel")
    from packaging.version import Version

    if Version(selected.version) <= Version(installation.version):
        raise ValueError(
            "Python updates cannot downgrade or reinstall the running version"
        )
    _verify_wheel(directory, selected)
    return installation, selected, manager, nonce, parent


def _wait_for_shutdown(
    directory: Path, nonce: str, parent: int, interpreter: Path
) -> None:
    # A POSIX child stays attached to the same actual parent lifetime until it is
    # reparented on exit. Windows needs a retained OS handle to avoid PID reuse.
    handle: ParentProcess | None = None
    if sys.platform == "win32":
        handle = ParentProcess(parent, interpreter)
    elif os.getppid() != parent:
        raise ValueError("The installer was not launched by the requesting application")
    try:
        durable_write(directory / "ready", nonce.encode())
        deadline = time.monotonic() + 120
        while True:
            if _matches(directory, "canceled", nonce):
                raise InterruptedError("Python update handoff canceled")
            exited = handle.exited() if handle else os.getppid() != parent
            if exited:
                if not _matches(directory, "authorized", nonce):
                    raise ValueError(
                        "The application exited without authorizing the update"
                    )
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "The application did not close; no Python packages were changed"
                )
            time.sleep(0.1)
    finally:
        if handle:
            handle.close()


def _process_executable() -> Path:
    # Windows venv launchers execute the base interpreter. UV can also expose it
    # through a version-independent junction, while Windows reports its real path.
    executable = (
        getattr(sys, "_base_executable", sys.executable)
        if sys.platform == "win32"
        else sys.executable
    )
    return Path(executable).resolve()


def perform_update(
    installation: PythonInstallation,
    wheel: PythonWheel,
    manager: tuple[str, ...],
    directory: Path,
) -> None:
    """After shutdown, exclude other app instances and delegate package replacement."""
    log = directory / "installer.log"
    with HostInstallationLease(installation.packages, exclusive=True):
        if running_python_installation() != installation:
            raise ValueError("The Python installation changed before replacement")
        _verify_wheel(directory, wheel)
        environment = update_environment()
        if installation.tool_directory:
            environment["UV_TOOL_DIR"] = installation.tool_directory
            environment["UV_TOOL_BIN_DIR"] = installation.tool_bin
        run_command(
            install_command(installation, manager, wheel.url, wheel.sha256),
            log,
            Event(),
            environment=environment,
        )
        # A separate interpreter must see the selected version and pass the
        # device-free runtime check before the GUI is relaunched.
        run_command(
            [
                *installation.launch,
                "-c",
                "from importlib.metadata import version; import sys; "
                "sys.exit(0 if version('iOpenPod') == sys.argv[1] else 1)",
                wheel.version,
            ],
            log,
            Event(),
            timeout=60,
        )
        run_command(
            [*installation.launch, "-m", "iOpenPod", "--smoke-test"],
            log,
            Event(),
            timeout=120,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    directory = parser.parse_args().directory
    installation, wheel, manager, nonce, parent = _request(directory)
    _wait_for_shutdown(directory, nonce, parent, _process_executable())
    try:
        perform_update(installation, wheel, manager, directory)
    except Exception as error:
        outcome, detail = "failed", f"Python update failed: {error}. Logs: {directory}"
    else:
        outcome, detail = "completed", f"Installed iOpenPod {wheel.version}"
    # Failure to persist a notification must not strand the user after shutdown.
    # The parent's redirected helper.log still retains the diagnostic.
    try:
        AtomicHostFile(installation.result_path).replace_bytes(
            json.dumps(
                {
                    "outcome": outcome,
                    "detail": detail,
                    "version": wheel.version,
                    "reported": False,
                }
            ).encode()
        )
    except OSError as error:
        print(f"Could not retain update result: {error}. {detail}", file=sys.stderr)
    _spawn([*installation.launch, "-m", "iOpenPod"], directory / "relaunch.log")
    return 0 if outcome == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
