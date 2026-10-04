"""Evidence and package-manager commands for the running Python installation.

Repository commands use UV. A deployed application can also use its interpreter's
pip when that is the package manager supplied by the user's Python installation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import site
import subprocess
import sys
import sysconfig
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from packaging.version import Version

from storage.host_files import application_cache_file
from storage.host_installation import require_plain_path

if TYPE_CHECKING:
    from threading import Event


@dataclass(frozen=True, slots=True)
class PythonInstallation:
    version: str
    interpreter: Path
    prefix: Path
    packages: Path
    metadata: Path
    metadata_sha256: str
    user_site: bool = False
    restriction: str = ""
    tool_directory: str = ""
    tool_bin: str = ""
    tool_receipt_sha256: str = ""

    @property
    def result_path(self) -> Path:
        key = hashlib.sha256(os.path.normcase(str(self.packages)).encode()).hexdigest()
        platform_name = {"win32": "windows", "darwin": "macos", "linux": "linux"}[
            sys.platform
        ]
        return application_cache_file(
            "iOpenPod", f"python-update-{key}.json", platform_name=platform_name
        )

    @property
    def launch(self) -> list[str]:
        # -P excludes the working directory; -E ignores injected Python settings.
        # Unlike -I, this also works for an ordinary pip --user installation.
        return [str(self.interpreter), "-E", "-P"]


def _index_origin(distribution: metadata.Distribution) -> bool:
    origin = distribution.read_text("direct_url.json")
    if origin is None:
        return True
    value: object = json.loads(origin)
    if not isinstance(value, dict):
        return False
    fields = cast("dict[str, object]", value)
    url = fields.get("url")
    if not isinstance(url, str) or "dir_info" in fields or "vcs_info" in fields:
        return False
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "files.pythonhosted.org"
        and parsed.port in (None, 443)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and parsed.path.endswith(".whl")
    )


def _uv_tool_scope(prefix: Path) -> tuple[str, str, str]:
    """Recognize the ordinary UV tool install documented in the README.

    Customized requirements, version pins and index options remain with the user.
    The receipt also binds upgrades to the existing tool and executable directories.
    """
    receipt = require_plain_path(prefix / "uv-receipt.toml")
    data = receipt.read_bytes()
    if len(data) > 64 * 1024 or prefix.name.lower() != "iopenpod":
        raise ValueError("Unsupported UV tool receipt")
    value = tomllib.loads(data.decode())
    raw_tool: object = value.get("tool")
    if not isinstance(raw_tool, dict):
        raise ValueError("Customized UV tool installation")
    tool = cast("dict[str, object]", raw_tool)
    update_options = {
        "no-build": True,
        "index": [
            {
                "url": "https://pypi.org/simple",
                "explicit": False,
                "default": True,
                "format": "simple",
                "authenticate": "auto",
            }
        ],
    }
    if (
        tool.get("requirements") != [{"name": "iopenpod"}]
        or set(tool) - {"requirements", "python", "entrypoints", "options"}
        or tool.get("options", {}) not in ({}, {"no-build": True}, update_options)
    ):
        raise ValueError("Customized UV tool installation")
    raw_entries = tool.get("entrypoints")
    if not isinstance(raw_entries, list):
        raise ValueError("Unsupported UV tool entry points")
    entries = cast("list[object]", raw_entries)
    if len(entries) != 1:
        raise ValueError("Unsupported UV tool entry points")
    raw_entry = entries[0]
    if not isinstance(raw_entry, dict):
        raise ValueError("Unsupported UV tool executable")
    entry = cast("dict[str, object]", raw_entry)
    if entry.get("name") != "iopenpod":
        raise ValueError("Unsupported UV tool executable")
    path = entry.get("install-path")
    if not isinstance(path, str):
        raise ValueError("Missing UV tool executable path")
    executable = Path(path)
    if not executable.is_absolute() or executable.name not in {
        "iopenpod",
        "iopenpod.exe",
    }:
        raise ValueError("Invalid UV tool executable path")
    require_plain_path(executable.parent)
    if not os.access(executable.parent, os.W_OK):
        raise ValueError("Read-only UV tool executable directory")
    return str(prefix.parent), str(executable.parent), hashlib.sha256(data).hexdigest()


def running_python_installation() -> PythonInstallation | None:
    """Reject editable/source shadows and distributions owned by other installers.

    Index installs do not record the original index URL. This establishes a Python
    package installation eligible to check official PyPI, not its historical origin.
    """
    if getattr(sys, "frozen", False):
        return None
    try:
        distribution = metadata.distribution("iOpenPod")
    except metadata.PackageNotFoundError:
        return None
    if (distribution.read_text("INSTALLER") or "").strip() not in {
        "uv",
        "pip",
    } or not _index_origin(distribution):
        return None
    records = distribution.files
    if not records:
        return None
    module = Path(__file__).resolve()
    if not any(
        entry.as_posix() == "iOpenPod/app/updates/python_installation.py"
        and Path(str(distribution.locate_file(entry))).resolve() == module
        for entry in records
    ):
        return None
    metadata_files = [
        Path(str(distribution.locate_file(entry)))
        for entry in records
        if entry.as_posix().endswith(".dist-info/METADATA")
    ]
    if len(metadata_files) != 1:
        return None
    record = metadata_files[0].absolute()
    packages = record.parent.parent
    prefix = Path(sys.prefix).absolute()
    user = packages.resolve() == Path(site.getusersitepackages()).resolve()
    if not user and packages.resolve() not in {
        Path(sysconfig.get_path(name)).resolve() for name in ("purelib", "platlib")
    }:
        return None
    Version(distribution.version)
    restriction = ""
    tool_directory = tool_bin = tool_digest = ""
    if (prefix / "uv-receipt.toml").exists():
        try:
            tool_directory, tool_bin, tool_digest = _uv_tool_scope(prefix)
        except (OSError, ValueError):
            restriction = (
                "Use UV to update this customized or read-only tool installation."
            )
    elif (prefix / "pipx_metadata.json").exists():
        restriction = (
            "Use the tool manager that owns this environment to upgrade iOpenPod."
        )
    elif (prefix / "conda-meta").is_dir():
        restriction = "Use Conda to update this managed Python environment."
    elif (
        sys.prefix == sys.base_prefix
        and (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").exists()
    ):
        restriction = (
            "This Python environment is externally managed. Use its software manager."
        )
    elif (prefix.parent / "uv.lock").exists() or (
        prefix.parent / "poetry.lock"
    ).exists():
        restriction = (
            "Update this project's dependency and lockfile through its project manager."
        )
    if not restriction:
        try:
            require_plain_path(packages)
            require_plain_path(record)
        except (OSError, ValueError):
            restriction = "This Python installation uses linked paths; update it with its package manager."
        if not os.access(packages, os.W_OK) or not os.access(record, os.W_OK):
            restriction = "This Python installation is read-only. Update it with its package manager."
    return PythonInstallation(
        distribution.version,
        Path(sys.executable).absolute(),
        prefix,
        packages,
        record,
        hashlib.sha256(record.read_bytes()).hexdigest(),
        user,
        restriction,
        tool_directory,
        tool_bin,
        tool_digest,
    )


def installer_command(installation: PythonInstallation) -> tuple[str, ...]:
    if installation.restriction:
        raise ValueError(installation.restriction)
    uv = shutil.which("uv")
    if uv and not installation.user_site:
        return (str(Path(uv).absolute()),)
    if installation.tool_directory:
        raise ValueError("UV is required to update this UV tool installation.")
    if util.find_spec("pip") is not None:
        return (*installation.launch, "-m", "pip")
    if installation.user_site:
        raise ValueError(
            "This user-site installation needs pip in its Python interpreter for automatic updates."
        )
    raise ValueError(
        "Install UV for this Python environment to enable automatic updates."
    )


def install_command(
    installation: PythonInstallation,
    manager: tuple[str, ...],
    url: str,
    digest: str,
    *,
    dry_run: bool = False,
) -> list[str]:
    requirement = f"iOpenPod @ {url}#sha256={digest}"
    if installation.tool_directory and not dry_run:
        return [
            *manager,
            "--no-config",
            "--no-python-downloads",
            "tool",
            "upgrade",
            "--default-index",
            "https://pypi.org/simple",
            "--no-build",
            requirement,
        ]
    if len(manager) == 1:
        command = [
            *manager,
            "--no-config",
            "--no-managed-python",
            "--no-python-downloads",
            "pip",
            "install",
            "--python",
            str(installation.interpreter),
            "--default-index",
            "https://pypi.org/simple",
            "--only-binary",
            ":all:",
            requirement,
        ]
    else:
        command = [
            *manager,
            "--isolated",
            "--disable-pip-version-check",
            "--no-input",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            "--only-binary=:all:",
            "--upgrade-strategy",
            "only-if-needed",
            requirement,
        ]
        if installation.user_site:
            command.append("--user")
    if dry_run:
        command.append("--dry-run")
    return command


def update_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PIP_", "UV_", "PYTHON"))
        and key not in {"VIRTUAL_ENV", "__PYVENV_LAUNCHER__"}
    }
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def run_command(
    arguments: list[str],
    log: Path,
    cancel: Event,
    *,
    timeout: float = 1800,
    environment: dict[str, str] | None = None,
) -> None:
    """Bound package-manager work without buffering arbitrary subprocess output."""
    environment = environment if environment is not None else update_environment()
    if sys.platform == "win32":
        _run_windows_command(arguments, log, cancel, environment, timeout)
        return
    with log.open("ab") as output:
        process = subprocess.Popen(
            arguments,
            cwd=log.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            start_new_session=True,
        )
        deadline = monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel.wait(0.1):
                    raise InterruptedError("Python update canceled")
                if monotonic() >= deadline:
                    raise TimeoutError("Python package update timed out")
            if process.returncode != 0:
                raise RuntimeError(
                    f"Python package command failed ({process.returncode}). See {log}"
                )
        finally:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                finally:
                    # A subprocess can outlive its parent after SIGTERM.
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)


def _run_windows_command(
    arguments: list[str],
    log: Path,
    cancel: Event,
    environment: dict[str, str],
    timeout: float,
) -> None:
    from .processes_windows import WindowsCandidateProcess

    # A venv's python.exe is itself a launcher. Own the entire tree before it can
    # start pip, so cancellation cannot leave a package installer running. This
    # tiny wrapper redirects logs without inheritable handles in the GUI process.
    wrapper = (
        "import json,os,subprocess,sys; from pathlib import Path; "
        "log=Path(sys.argv[1]); os.chdir(log.parent); "
        "output=log.open('ab'); "
        "sys.exit(subprocess.call(json.loads(sys.argv[2]), "
        "stdin=subprocess.DEVNULL, stdout=output, stderr=output, "
        "creationflags=0x08000000))"
    )
    process = WindowsCandidateProcess(
        [sys.executable, "-E", "-P", "-c", wrapper, str(log), json.dumps(arguments)],
        environment,
    )
    deadline = monotonic() + timeout
    try:
        while (code := process.poll()) is None:
            if cancel.wait(0.1):
                raise InterruptedError("Python update canceled")
            if monotonic() >= deadline:
                raise TimeoutError("Python package update timed out")
        if code != 0:
            raise RuntimeError(f"Python package command failed ({code}). See {log}")
    finally:
        # Also removes unexpected descendants after the manager has returned.
        try:
            process.stop()
        finally:
            process.release()
