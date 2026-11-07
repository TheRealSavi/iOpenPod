"""Managed setup selects platform-compatible packages and activates only health-checked installs."""

import hashlib
import io
import json
import platform
import sys
import sysconfig
import zipfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from iOpenPod.app import phase_runtime_install
from iOpenPod.app.phase_parts import PhasePartKind
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.app.phase_runtime_install import (
    PhaseRuntimeTarget,
    install_phase_runtime,
    runtime_target,
)
from iOpenPod.app.phase_worker_session import PhaseWorkerSession
from storage import HostPath
from storage.media_processing import ToolOutput


@pytest.mark.parametrize(
    "system,architecture,macos,torch,demucs",
    [
        ("win32", "AMD64", (0, 0), "2.14.0+cpu", "4.1.0"),
        ("linux", "x86_64", (0, 0), "2.14.0+cpu", "4.1.0"),
        ("darwin", "arm64", (12, 3), "2.11.0", "4.1.0"),
        ("darwin", "arm64", (14, 0), "2.14.0", "4.1.0"),
        ("darwin", "x86_64", (12, 3), "2.2.2", "4.0.1"),
    ],
)
def test_platform_profiles_keep_older_mac_compatibility(
    system: str,
    architecture: str,
    macos: tuple[int, int],
    torch: str,
    demucs: str,
) -> None:
    target = runtime_target(system, architecture, macos)
    assert f"torch=={torch}" in target.requirements
    assert f"demucs=={demucs}" in target.requirements
    assert len(target.sha256) == 64
    assert target.index == "https://download.pytorch.org/whl/cpu"


@pytest.mark.parametrize(
    "system,architecture,macos",
    [
        ("darwin", "arm64", (11, 0)),
        ("linux", "riscv64", (0, 0)),
        ("other", "x86_64", (0, 0)),
    ],
)
def test_unsupported_platforms_keep_the_acoustic_option(
    system: str,
    architecture: str,
    macos: tuple[int, int],
) -> None:
    with pytest.raises(ValueError, match="Acoustic analysis remains available"):
        runtime_target(system, architecture, macos)


@pytest.mark.parametrize("native_machine", ["AMD64", "ARM64"])
def test_windows_x64_setup_matches_the_running_app_under_emulation(
    monkeypatch: pytest.MonkeyPatch, native_machine: str
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: native_machine)
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-amd64")
    target = phase_runtime_install.host_runtime_target()
    assert target.archive == "x86_64-pc-windows-msvc.zip"
    assert target.python_key == "cpython-3.12.14-windows-x86_64-none"


def test_native_windows_arm_python_does_not_claim_an_x64_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(sysconfig, "get_platform", lambda: "win-arm64")
    with pytest.raises(ValueError, match="Acoustic analysis remains available"):
        phase_runtime_install.host_runtime_target()


@pytest.mark.parametrize("healthy", [False, True])
@pytest.mark.parametrize("gpu_failure", [None, "compile", "sync", "health", "cancel"])
def test_setup_preserves_previous_install_until_health_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    healthy: bool,
    gpu_failure: str | None,
) -> None:
    root = tmp_path / "PhaseAnalysis"
    root.mkdir()
    receipt = root / "current.json"
    receipt.write_bytes(b"previous usable installation")
    calls: list[tuple[str, ...]] = []
    attempted: list[Path] = []
    gpu_active = False
    cancelled = False
    stale = root / "python/cpython-3.12.13-test/python.exe"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"previous interpreter")
    other_architecture = (
        root / "python/cpython-3.12.14-macos-aarch64-none/bin/python3.12"
    )
    other_architecture.parent.mkdir(parents=True)
    other_architecture.write_bytes(b"another architecture")

    def checkpoint() -> None:
        if cancelled:
            raise RuntimeError("cancelled")

    def bootstrap(
        _target: object, workspace: Path, _checkpoint: Callable[[], None]
    ) -> Path:
        path = workspace / "uv"
        path.write_bytes(b"verified")
        return path

    def run(
        _executable: HostPath, args: tuple[str, ...], **_kwargs: object
    ) -> ToolOutput:
        nonlocal gpu_active, cancelled
        assert receipt.read_bytes() == b"previous usable installation"
        calls.append(args)
        if "--install-dir" in args:
            assert "--no-bin" in args and "--no-registry" in args
            directory = (
                Path(args[args.index("--install-dir") + 1])
                / args[args.index("install") + 1]
            )
            path = directory / (
                "python.exe" if sys.platform == "win32" else "bin/python3.12"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(b"python")
        elif "venv" in args:
            assert (
                "cpython-3.12.14-windows-x86_64-none"
                in args[args.index("--python") + 1]
            )
            directory = Path(args[-1])
            attempted.append(directory)
            assert all(not previous.exists() for previous in attempted[:-1])
            path = directory / (
                "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(b"python")
        elif "--output-file" in args:
            assert args[args.index("--only-binary") + 1] == ":all:"
            assert "demucs,dora-search,antlr4-python3-runtime" in args
            gpu_active = "cu130" in Path(args[args.index("compile") + 1]).read_text()
            if gpu_active and gpu_failure == "compile":
                raise RuntimeError("CUDA packages unavailable")
            Path(args[args.index("--output-file") + 1]).write_text(
                "pinned==1 --hash=sha256:test\n"
            )
        elif "sync" in args and gpu_active:
            assert args[args.index("--only-binary") + 1] == ":all:"
            if gpu_failure == "sync":
                raise RuntimeError("CUDA wheel could not install")
            if gpu_failure == "cancel":
                cancelled = True
                checkpoint()
        elif "--health" in args:
            if gpu_active and gpu_failure == "health":
                raise RuntimeError("CUDA native library could not load")
            if not healthy:
                raise RuntimeError("Model unavailable")
            return ToolOutput(b'{"protocol":1,"identity":"tested-cpu-model"}', b"")
        return ToolOutput(b"", b"")

    monkeypatch.setattr(
        phase_runtime_install,
        "host_runtime_target",
        lambda: runtime_target("win32", "AMD64"),
    )

    def preferred_target(
        target: PhaseRuntimeTarget, _checkpoint: Callable[[], None]
    ) -> PhaseRuntimeTarget:
        return (
            target
            if gpu_failure is None
            else replace(target, requirements=("torch==2.14.0+cu130",))
        )

    monkeypatch.setattr(phase_runtime_install, "_accelerated_target", preferred_target)
    monkeypatch.setattr(phase_runtime_install, "_download_uv", bootstrap)
    monkeypatch.setattr(phase_runtime_install, "run_media_tool", run)
    if healthy and gpu_failure != "cancel":
        installed = install_phase_runtime(
            root=root, checkpoint=checkpoint, progress=lambda _: None
        )
        assert installed.identity == "managed-v1:tested-cpu-model"
        selected = ManagedPhaseSources.installed(root)
        assert selected is not None and selected.python == installed.python
        assert any("--generate-hashes" in args for args in calls)
        assert any("--require-hashes" in args for args in calls)
        assert len(attempted) == (1 if gpu_failure is None else 2)
        assert list(root.glob("runtime-*")) == [installed.directory]
    else:
        with pytest.raises(
            RuntimeError,
            match="cancelled" if gpu_failure == "cancel" else "Model unavailable",
        ):
            install_phase_runtime(
                root=root, checkpoint=checkpoint, progress=lambda _: None
            )
        assert receipt.read_bytes() == b"previous usable installation"
        assert not list(root.glob("runtime-*"))
        if gpu_failure == "cancel":
            assert len(attempted) == 1
    assert stale.read_bytes() == b"previous interpreter"
    assert other_architecture.read_bytes() == b"another architecture"


@pytest.mark.parametrize(
    "directory", ["../escape", "runtime-../escape", "/outside", "runtime-short"]
)
def test_receipt_cannot_select_an_arbitrary_interpreter(
    tmp_path: Path, directory: str
) -> None:
    (tmp_path / "current.json").write_text(
        json.dumps({"protocol": 1, "directory": directory, "identity": "model"})
    )
    with pytest.raises(ValueError, match="receipt"):
        ManagedPhaseSources.installed(tmp_path)


def test_worker_result_returns_validated_parts_and_actual_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ManagedPhaseSources(tmp_path, "preferred-gpu")
    count = 1 + 22_050 // 256

    def request(_session: object, pcm: bytes, **_kwargs: object) -> tuple[Path, str]:
        assert pcm == bytes(44_100 * 2 * 4)
        output = tmp_path / "parts.npz"
        arrays = {
            f"{kind.value}_{field}": np.zeros(shape)
            for kind in PhasePartKind
            for field, shape in (
                ("bands", (3, count)),
                ("energy", (count,)),
                ("chroma", (12, count)),
                ("magnitudes", (3, count)),
            )
        }
        np.savez(output, allow_pickle=False, **arrays)
        return output, "actual-cpu"

    monkeypatch.setattr(PhaseWorkerSession, "request", request)
    try:
        parts = source.analyze(
            bytes(44_100 * 2 * 4),
            sample_rate=44_100,
            channels=2,
            checkpoint=lambda: None,
        )
    finally:
        source.close()
    assert len(parts) == 6
    assert source.identity == "managed-v1:actual-cpu"


@pytest.mark.parametrize(
    "capability,driver,accelerated",
    [("8.6", "580.10", True), ("6.1", "580.10", False), ("8.6", "550.10", False)],
)
def test_cuda_setup_requires_a_supported_gpu_and_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capability: str,
    driver: str,
    accelerated: bool,
) -> None:
    def find_executable(_name: str) -> str:
        return str(tmp_path / "nvidia-smi")

    def run(*_args: object, **_kwargs: object) -> ToolOutput:
        return ToolOutput(f"{capability}, {driver}".encode(), b"")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        phase_runtime_install,
        "find_host_executable",
        find_executable,
    )
    monkeypatch.setattr(
        phase_runtime_install,
        "run_media_tool",
        run,
    )
    target = phase_runtime_install._accelerated_target(  # pyright: ignore[reportPrivateUsage]
        runtime_target("win32", "AMD64"), lambda: None
    )
    assert ("cu130" in target.index) == accelerated


@pytest.mark.parametrize("corrupt", [False, True])
def test_bootstrap_extracts_only_after_digest_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt: bool,
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("uv.exe", b"verified executable")
        archive.writestr("../unrelated", b"must not extract")
    data = buffer.getvalue()
    target = phase_runtime_install.PhaseRuntimeTarget(
        "test.zip",
        len(data),
        "0" * 64 if corrupt else hashlib.sha256(data).hexdigest(),
        (),
        "windows-x86_64-none",
    )

    def open_archive(*_args: object, **_kwargs: object) -> io.BytesIO:
        return io.BytesIO(data)

    monkeypatch.setattr(phase_runtime_install, "urlopen", open_archive)
    if corrupt:
        with pytest.raises(ValueError, match="verification"):
            phase_runtime_install._download_uv(target, tmp_path, lambda: None)  # pyright: ignore[reportPrivateUsage]
        assert not (tmp_path / "uv.exe").exists()
    else:
        path = phase_runtime_install._download_uv(target, tmp_path, lambda: None)  # pyright: ignore[reportPrivateUsage]
        assert path.read_bytes() == b"verified executable"
    assert not (tmp_path.parent / "unrelated").exists()


def test_cancelled_setup_does_not_contact_download_hosts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cancelled() -> None:
        raise RuntimeError("cancelled")

    def download(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Cancelled setup contacted a download host")

    monkeypatch.setattr(phase_runtime_install, "urlopen", download)
    with pytest.raises(RuntimeError, match="cancelled"):
        install_phase_runtime(
            root=tmp_path / "not-created", checkpoint=cancelled, progress=lambda _: None
        )
    assert not (tmp_path / "not-created").exists()


def test_next_analysis_discovers_a_runtime_installed_after_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from iOpenPod.app.phase_analysis import PhaseAnalysisService
    from iOpenPod.app.phase_sources import DemucsPhaseSources

    monkeypatch.setattr(DemucsPhaseSources, "available", lambda: False)
    monkeypatch.setattr(ManagedPhaseSources, "installed", lambda: None)
    service = PhaseAnalysisService()
    assert service.for_analysis().identity.endswith(":acoustic:mono")
    installed = ManagedPhaseSources(tmp_path, "health-checked-model")
    monkeypatch.setattr(ManagedPhaseSources, "installed", lambda: installed)
    assert service.for_analysis().identity.endswith(
        ":managed-v1:health-checked-model:stereo"
    )
