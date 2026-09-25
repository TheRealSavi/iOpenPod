from pathlib import Path

from scripts.pyinstaller_helpers import wasmtime_binaries


def test_x64_windows_wasmtime_is_available_at_windows_on_arm_lookup_path(
    tmp_path: Path,
) -> None:
    wasmtime_package = tmp_path / "wasmtime"
    runtime_dir = wasmtime_package / "win32-x86_64"
    runtime_dir.mkdir(parents=True)
    runtime_dll = runtime_dir / "_wasmtime.dll"
    runtime_dll.write_bytes(b"wasmtime")

    binaries = wasmtime_binaries(
        wasmtime_package,
        platform="win32",
        machine="AMD64",
    )

    assert binaries == [
        (str(runtime_dll), "wasmtime/win32-x86_64"),
        (str(runtime_dll), "wasmtime/win32-aarch64"),
    ]


def test_arm64_windows_wasmtime_is_not_aliased(tmp_path: Path) -> None:
    wasmtime_package = tmp_path / "wasmtime"
    runtime_dir = wasmtime_package / "win32-aarch64"
    runtime_dir.mkdir(parents=True)
    runtime_dll = runtime_dir / "_wasmtime.dll"
    runtime_dll.write_bytes(b"wasmtime")

    binaries = wasmtime_binaries(
        wasmtime_package,
        platform="win32",
        machine="ARM64",
    )

    assert binaries == [(str(runtime_dll), "wasmtime/win32-aarch64")]
