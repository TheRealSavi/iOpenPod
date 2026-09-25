"""Helpers shared by the PyInstaller specification and its regression tests."""

from __future__ import annotations

from pathlib import Path


def wasmtime_binaries(
    wasmtime_package: Path,
    *,
    platform: str,
    machine: str,
) -> list[tuple[str, str]]:
    """Return Wasmtime native libraries for the current frozen application.

    An x64 application running under Windows-on-ARM emulation has an x64 DLL,
    but ``platform.machine()`` reports the ARM64 host.  Wasmtime therefore
    looks in ``win32-aarch64`` despite needing the x64 DLL.  Include the x64
    DLL at that lookup path as an alias; it remains loaded only by the x64
    application that the x64 PyInstaller build produced.
    """
    normalized_machine = {
        "AMD64": "x86_64",
        "arm64": "aarch64",
        "ARM64": "aarch64",
    }.get(machine, machine)
    runtime_dir = wasmtime_package / f"{platform}-{normalized_machine}"
    if not runtime_dir.is_dir():
        return []

    destinations = [f"wasmtime/{runtime_dir.name}"]
    if platform == "win32" and normalized_machine == "x86_64":
        destinations.append("wasmtime/win32-aarch64")

    return [
        (str(runtime_file), destination)
        for runtime_file in runtime_dir.iterdir()
        if runtime_file.is_file()
        for destination in destinations
    ]
