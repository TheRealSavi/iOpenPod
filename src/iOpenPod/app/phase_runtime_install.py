"""Explicit, isolated optional analysis setup; activation follows real inference."""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import shutil
import ssl
import sys
import sysconfig
import tarfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast
from urllib.request import urlopen
from uuid import uuid4

import certifi

from iOpenPod.app.display_text import source_text
from iOpenPod.app.phase_runtime import (
    ManagedPhaseSources,
    runtime_directory,
    worker_path,
)
from storage import HostPath
from storage.host_files import AtomicHostFile, lock_host_file
from storage.host_installation import require_plain_path
from storage.host_tools import find_host_executable
from storage.media_processing import run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_UV = "https://github.com/astral-sh/uv/releases/download/0.12.7/uv-"
_CPU = "https://download.pytorch.org/whl/cpu"
_CUDA = "https://download.pytorch.org/whl/cu130"
_PYPI = "https://pypi.org/simple"
_PYTHON = "3.12.14"
# These pure-Python projects publish source archives. Native dependencies must
# have compatible wheels; setup must never require a compiler on the user's Host.
_PACKAGE_FORMATS = (
    "--only-binary",
    ":all:",
    "--no-binary",
    "demucs,dora-search,antlr4-python3-runtime",
)


@contextmanager
def _unpublished_environment(root: Path) -> Generator[Path]:
    directory = root / f"runtime-{uuid4().hex}"
    try:
        yield directory
    except BaseException:
        # This is an app-owned, unique directory. Check the resolved parent
        # before recursive cleanup; never follow a replaced root or junction.
        if directory.exists() and directory.resolve().parent == root.resolve():
            try:
                require_plain_path(directory)
                shutil.rmtree(directory)
            except OSError:
                logging.getLogger(__name__).warning(
                    "Could not remove incomplete Phase runtime %s",
                    directory,
                    exc_info=True,
                )
        raise


@dataclass(frozen=True, slots=True)
class PhaseRuntimeTarget:
    archive: str
    size: int
    sha256: str
    requirements: tuple[str, ...]
    python_platform: str
    index: str = _CPU

    @property
    def python_key(self) -> str:
        return f"cpython-{_PYTHON}-{self.python_platform}"


def runtime_target(
    system: str, architecture: str, macos: tuple[int, int] = (0, 0)
) -> PhaseRuntimeTarget:
    architecture = architecture.lower()
    if architecture == "amd64":
        architecture = "x86_64"
    if architecture == "aarch64":
        architecture = "arm64"
    common = ("librosa==0.11.0", "numpy==2.3.5", "demucs==4.1.0", "torchaudio==2.11.0")
    if system == "win32" and architecture == "x86_64":
        return PhaseRuntimeTarget(
            "x86_64-pc-windows-msvc.zip",
            16979508,
            "bf1518af459a3915511a11fdc6e2f43ef9a2afa138b9d498eeb9642fe9d85218",
            (*common, "torch==2.14.0+cpu"),
            "windows-x86_64-none",
        )
    if system == "linux" and architecture == "x86_64":
        return PhaseRuntimeTarget(
            "x86_64-unknown-linux-gnu.tar.gz",
            19419908,
            "788f18abea7c5f55d6216e4f5613fd89d4d59b631efeec117b2b07fe72f1da21",
            (*common, "torch==2.14.0+cpu"),
            "linux-x86_64-gnu",
        )
    if system == "darwin" and macos >= (12, 3):
        if architecture == "arm64":
            torch = "2.14.0" if macos >= (14, 0) else "2.11.0"
            return PhaseRuntimeTarget(
                "aarch64-apple-darwin.tar.gz",
                16611578,
                "127ebdda7ad953cdf198e964b570ea5771b85467ea93eb7cb6d6f8e6f55408f3",
                (*common, f"torch=={torch}"),
                "macos-aarch64-none",
            )
        if architecture == "x86_64":
            return PhaseRuntimeTarget(
                "x86_64-apple-darwin.tar.gz",
                19938013,
                "06b8ae1da8c2661c5434507a66f8c2b0b835933bf955b5958a9ac357a37d1959",
                (
                    "librosa==0.11.0",
                    "numpy==1.26.4",
                    "numba==0.62.1",
                    "demucs==4.0.1",
                    "torch==2.2.2",
                    "torchaudio==2.2.2",
                ),
                "macos-x86_64-none",
            )
    raise ValueError(
        "Optional instrument analysis is unavailable on this platform. Acoustic analysis remains available."
    )


def host_runtime_target() -> PhaseRuntimeTarget:
    """Describe optional setup support without downloading or probing a GPU."""
    version = (
        platform.mac_ver()[0].split(".") if sys.platform == "darwin" else ["0", "0"]
    )
    macos = tuple(int(value) for value in [*version, "0", "0"][:2])
    # Windows platform.machine() describes the native CPU, even when this x64
    # application runs under ARM64 emulation. Match the running interpreter so
    # its verified x64 setup tool and private Python use the same emulation path.
    architecture = (
        sysconfig.get_platform().removeprefix("win-")
        if sys.platform == "win32"
        else platform.machine()
    )
    return runtime_target(sys.platform, architecture, (macos[0], macos[1]))


def _accelerated_target(
    target: PhaseRuntimeTarget, checkpoint: Callable[[], None]
) -> PhaseRuntimeTarget:
    if sys.platform not in {"win32", "linux"}:
        return target
    executable = find_host_executable("nvidia-smi")
    if executable is None:
        return target
    # CUDA 13 needs Turing or newer and an R580-family driver. Driver presence
    # alone is insufficient: old NVIDIA cards otherwise select unusable wheels.
    try:
        result = run_media_tool(
            HostPath(executable),
            ("--query-gpu=compute_cap,driver_version", "--format=csv,noheader"),
            checkpoint=checkpoint,
            timeout_seconds=10,
            max_output_bytes=4096,
        )
    except Exception:
        checkpoint()
        return target
    for row in result.stdout.decode("utf-8", errors="replace").splitlines():
        fields = row.split(",")
        try:
            compatible = (
                len(fields) == 2
                and float(fields[0]) >= 7.5
                and int(fields[1].strip().split(".")[0]) >= 580
            )
        except ValueError:
            continue
        if compatible:
            requirements = tuple(
                "torch==2.14.0+cu130"
                if value.startswith("torch==")
                else "torchaudio==2.11.0+cu130"
                if value.startswith("torchaudio==")
                else value
                for value in target.requirements
            )
            return replace(target, requirements=requirements, index=_CUDA)
    return target


def _download_uv(
    target: PhaseRuntimeTarget, directory: Path, checkpoint: Callable[[], None]
) -> Path:
    checkpoint()
    archive = directory / target.archive
    digest = hashlib.sha256()
    size = 0
    with (
        urlopen(
            _UV + target.archive,
            timeout=30,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response,
        archive.open("wb") as output,
    ):
        while block := response.read(1024 * 1024):
            checkpoint()
            size += len(block)
            if size > target.size:
                raise ValueError("Phase setup download exceeds its pinned size")
            digest.update(block)
            output.write(block)
    if size != target.size or digest.hexdigest() != target.sha256:
        raise ValueError("Phase setup download failed verification")
    executable = directory / ("uv.exe" if target.archive.endswith(".zip") else "uv")
    # Extract only the verified executable, never paths or links from the archive.
    if target.archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            members = [
                item
                for item in bundle.infolist()
                if Path(item.filename).name == "uv.exe"
            ]
            if len(members) != 1 or members[0].file_size > 64 * 1024 * 1024:
                raise ValueError("Invalid Phase setup archive")
            data = bundle.read(members[0])
    else:
        with tarfile.open(archive) as bundle:
            tar_members = [
                item
                for item in bundle.getmembers()
                if Path(item.name).name == "uv" and item.isfile()
            ]
            if len(tar_members) != 1 or tar_members[0].size > 64 * 1024 * 1024:
                raise ValueError("Invalid Phase setup archive")
            stream = bundle.extractfile(tar_members[0])
            if stream is None:
                raise ValueError("Phase setup executable is missing")
            with stream:
                data = stream.read()
    executable.write_bytes(data)
    executable.chmod(0o700)
    return executable


@dataclass(frozen=True, slots=True)
class _SetupTool:
    executable: Path
    root: Path
    checkpoint: Callable[[], None]

    def __call__(self, *args: str) -> bytes:
        self.checkpoint()
        return run_media_tool(
            HostPath(self.executable),
            (
                "--no-config",
                "--no-progress",
                "--cache-dir",
                str(self.root / "cache"),
                *args,
            ),
            checkpoint=self.checkpoint,
            timeout_seconds=3600,
            max_output_bytes=1024 * 1024,
            max_stderr_bytes=1024 * 1024,
        ).stdout


def install_phase_runtime(
    *,
    checkpoint: Callable[[], None],
    progress: Callable[[str], None],
    root: Path | None = None,
) -> ManagedPhaseSources:
    checkpoint()
    root = root or runtime_directory()
    baseline = host_runtime_target()
    preferred = _accelerated_target(baseline, checkpoint)
    root.mkdir(parents=True, exist_ok=True)
    require_plain_path(root)
    with (
        lock_host_file(root / "install.lock"),
        TemporaryDirectory(prefix="setup-", dir=root) as temporary,
    ):
        workspace = Path(temporary)
        progress(source_text("Downloading the verified setup tool…"))
        command = _SetupTool(
            _download_uv(baseline, workspace, checkpoint), root, checkpoint
        )

        progress(source_text("Installing a private Python runtime…"))
        python_root = root / "python"
        command(
            "python",
            "install",
            baseline.python_key,
            "--install-dir",
            str(python_root),
            "--no-bin",
            "--no-registry",
        )
        base_python = (
            python_root
            / baseline.python_key
            / ("python.exe" if sys.platform == "win32" else "bin/python3.12")
        ).resolve()
        if not base_python.is_file():
            raise ValueError("Phase setup could not identify its private Python")
        if not base_python.is_relative_to(python_root.resolve()):
            raise ValueError("Phase setup Python is outside its private directory")
        targets = (preferred, baseline) if preferred != baseline else (baseline,)
        for target in targets:
            try:
                installed = _install_environment(
                    command, target, base_python, workspace, progress
                )
            except Exception:
                # Cancellation always wins over an optional CPU retry. A failed
                # candidate is removed before another isolated environment starts.
                checkpoint()
                if target == baseline:
                    raise
                logging.getLogger(__name__).warning(
                    "Accelerated Phase setup failed; retrying CPU analysis",
                    exc_info=True,
                )
                progress(
                    source_text(
                        "GPU setup could not finish. Retrying with CPU analysis…"
                    )
                )
            else:
                progress(
                    source_text(
                        "Instrument analysis is ready. Acoustic analysis remains available as a fallback."
                    )
                )
                return installed
    raise AssertionError("Phase setup exhausted its installation candidates")


def _install_environment(
    command: _SetupTool,
    target: PhaseRuntimeTarget,
    base_python: Path,
    workspace: Path,
    progress: Callable[[str], None],
) -> ManagedPhaseSources:
    root, checkpoint = command.root, command.checkpoint
    with _unpublished_environment(root) as staging:
        command("venv", "--python", str(base_python), str(staging))
        python = staging / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        requirements = workspace / "requirements.in"
        requirements.write_text("\n".join(target.requirements) + "\n", encoding="utf-8")
        lock = workspace / "requirements.txt"
        indexes = ("--default-index", _PYPI, "--index", target.index)
        progress(source_text("Downloading and installing the analysis libraries…"))
        command(
            "pip",
            "compile",
            str(requirements),
            "--python",
            str(python),
            "--generate-hashes",
            "--output-file",
            str(lock),
            *_PACKAGE_FORMATS,
            *indexes,
        )
        command(
            "pip",
            "sync",
            str(lock),
            "--python",
            str(python),
            "--require-hashes",
            *_PACKAGE_FORMATS,
            *indexes,
        )
        shutil.copyfile(lock, staging / "iopenpod-requirements.txt")
        checkpoint()
        # Nothing refers to this directory until health succeeds. Existing usable
        # installations stay active throughout setup, including on cancellation.
        pending = ManagedPhaseSources(staging, "pending")
        progress(source_text("Downloading the model and testing instrument analysis…"))
        output = run_media_tool(
            HostPath(pending.python),
            ("-I", str(worker_path()), "--models", str(root / "models"), "--health"),
            checkpoint=checkpoint,
            timeout_seconds=1800,
            max_output_bytes=4096,
            max_stderr_bytes=65536,
            low_priority=True,
        )
        decoded: object = json.loads(output.stdout)
        if not isinstance(decoded, dict):
            raise ValueError("Phase runtime health check failed")
        data = cast("dict[str, object]", decoded)
        identity = data.get("identity")
        if (
            data.get("protocol") != 1
            or not isinstance(identity, str)
            or not 0 < len(identity) <= 512
        ):
            raise ValueError("Phase runtime health check failed")
        checkpoint()
        AtomicHostFile(root / "current.json").replace_bytes(
            json.dumps(
                {
                    "protocol": 1,
                    "directory": staging.name,
                    "identity": identity,
                }
            ).encode()
        )
        return ManagedPhaseSources(staging, identity)
