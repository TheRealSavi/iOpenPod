"""Compile the small native Storage helper using the builder's MSVC and SDK."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build/packaging/storage-access"


def check_helper(data: bytes) -> None:
    """Reject an elevated helper that needs libraries outside Windows itself."""
    pefile = import_module("pefile")  # Already supplied by the locked PyInstaller.
    with pefile.PE(data=data) as executable:
        imports = {entry.dll.lower() for entry in executable.DIRECTORY_ENTRY_IMPORT}
        if imports != {b"kernel32.dll", b"advapi32.dll"}:
            raise ValueError("The Storage helper must import only Windows system DLLs")
        if executable.DIRECTORY_ENTRY_LOAD_CONFIG.struct.DependentLoadFlags != 0x800:
            raise ValueError("The Storage helper requires system-only DLL resolution")
        if executable.FILE_HEADER.Machine != 0x8664:
            raise ValueError("The Storage helper must match the Windows x64 release")


def build() -> Path:
    if sys.platform != "win32":
        raise ValueError("Build the Windows access helper on Windows")
    installer = (
        Path(os.environ["PROGRAMFILES(X86)"]) / "Microsoft Visual Studio/Installer"
    )
    installation = subprocess.run(
        [
            str(installer / "vswhere.exe"),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not installation:
        raise ValueError("Install Visual Studio C++ Build Tools on the Windows builder")
    setup = Path(installation) / "VC/Auxiliary/Build/vcvars64.bat"
    if any(character in str(setup) for character in '%"\r\n'):
        raise ValueError("Unsupported Visual Studio installation path")
    # Only the known setup path enters cmd syntax; compiler arguments use argv.
    initialized = subprocess.run(
        f'"{Path(os.environ["SYSTEMROOT"]) / "System32/cmd.exe"}" /d /s /c ""{setup}" >nul && set"',
        capture_output=True,
        text=True,
        check=True,
    )
    environment = dict(os.environ)
    for line in initialized.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            key, value = line.split("=", 1)
            environment[key] = value
    environment = {key.upper(): value for key, value in environment.items()}
    compiler = shutil.which("cl.exe", path=environment["PATH"])
    if compiler is None:
        raise ValueError("The Visual Studio environment has no C compiler")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    executable = OUTPUT / "iOpenPod-storage-access.exe"
    subprocess.run(
        [
            compiler,
            "/nologo",
            "/W4",
            "/WX",
            "/O2",
            "/MT",
            "/guard:cf",
            str(ROOT / "src/storage/platform/native/windows_volume_access.c"),
            f"/Fo{OUTPUT / 'windows_volume_access.obj'}",
            f"/Fe{executable}",
            "/link",
            "advapi32.lib",
            "/DYNAMICBASE",
            "/NXCOMPAT",
            "/DEPENDENTLOADFLAG:0x800",
            "/MANIFEST:EMBED",
            "/MANIFESTUAC:level='asInvoker' uiAccess='false'",
        ],
        cwd=OUTPUT,
        env=environment,
        check=True,
    )
    subprocess.run([str(executable), "--self-test"], check=True, timeout=10)
    check_helper(executable.read_bytes())
    from scripts.sign_windows import sign

    sign(executable, environment)
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    (OUTPUT / "_iopenpod_storage_helper.py").write_text(
        f'SHA256 = "{digest}"\n', encoding="utf-8"
    )
    return executable


if __name__ == "__main__":
    print(build())
