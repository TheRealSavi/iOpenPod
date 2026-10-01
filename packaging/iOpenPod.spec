"""One native build per OS/architecture; invoked by scripts/package_app.py."""

import os
import hashlib
import json
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

root = Path(SPECPATH).parent
generated = root / "build" / "packaging"
config = tomllib.loads((root / "pyproject.toml").read_text())
version = config["project"]["version"]
datas = [(str(generated / "licenses"), "licenses")]
for package in ("iOpenPod", "device_registry", "iPodDB", "storage", "tzdata"):
    datas += collect_data_files(package)
datas += copy_metadata("iOpenPod")
# librosa/lazy_loader need their on-disk stubs, even when code lives in PYZ.
datas += collect_data_files(
    "librosa", include_py_files=True,
    excludes=["**/__pycache__/**", "**/*.pyc", "**/*.nbc", "**/*.nbi"],
)
binaries = collect_dynamic_libs("wasmtime")
# zoneinfo loads tzdata's geographical resource packages dynamically on Windows.
hiddenimports = collect_submodules("librosa") + collect_submodules("tzdata") + [
    "iOpenPod.app.synesthesia.dsp",
    "iOpenPod.app.synesthesia.enrichment",
]
if sys.platform == "win32":
    # Media-key adapters intentionally load OS bindings only when needed.
    hiddenimports += collect_submodules("winrt") + [
        "msvcrt",
        "winrt.windows.media",
        "winrt.windows.media.interop",
        "winrt.windows.foundation.collections",
        "winrt.windows.storage.streams",
    ]
    binaries += collect_dynamic_libs("winrt")
elif sys.platform == "darwin":
    hiddenimports += ["MediaPlayer", "AppKit", "Foundation", "objc", "fcntl"]
else:
    hiddenimports += ["fcntl"]
a = Analysis(
    [str(root / "src/iOpenPod/__main__.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(root / "packaging/hooks")],
    runtime_hooks=[],
    excludes=[
        "torch", "torchaudio", "demucs", "pytest", "mypy",
        "tkinter", "_tkinter", "sklearn.datasets",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
if sys.platform == "win32":
    # SoundFile's upstream wheel has an unpinned static codec build. Use our
    # documented PCM-only build; the app already decodes media through FFmpeg.
    sndfile = root / "build/native-libs/sndfile/libsndfile_x64.dll"
    build_record = json.loads(
        (sndfile.parent / "build-record.json").read_text(encoding="utf-8")
    )
    with sndfile.open("rb") as stream:
        sndfile_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if sndfile_hash != build_record["sha256"]:
        raise ValueError("The source-built libsndfile differs from its build record")
    replaced = False
    for index, (destination, source, kind) in enumerate(a.binaries):
        if Path(destination).name.lower() == "libsndfile_x64.dll":
            a.binaries[index] = (destination, str(sndfile), kind)
            replaced = True
    if not replaced:
        raise ValueError("The expected SoundFile native library was not collected")
    a.datas += [("licenses/libsndfile-build-record.json", str(sndfile.parent / "build-record.json"), "DATA")]
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="iOpenPod",
    console=sys.platform == "linux",
    upx=False,
    strip=False,
    argv_emulation=False,
    icon=str(root / "src/iOpenPod/assets/icons/icon.ico") if sys.platform == "win32" else None,
    version=str(generated / "windows-version.txt") if sys.platform == "win32" else None,
    manifest=str(root / "packaging/windows/iOpenPod.manifest.xml") if sys.platform == "win32" else None,
    codesign_identity=os.environ.get("IOPENPOD_CODESIGN_IDENTITY"),
    entitlements_file=os.environ.get("IOPENPOD_ENTITLEMENTS"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="iOpenPod", upx=False, strip=False)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="iOpenPod.app",
        icon=str(generated / "iOpenPod.icns"),
        bundle_identifier="com.iopenpod.app",
        info_plist={
            "CFBundleDisplayName": "iOpenPod",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": os.environ.get("IOPENPOD_BUILD_NUMBER", version),
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": config["tool"]["iopenpod"]["packaging"][
                "macos-minimum-version"
            ],
            "NSRemovableVolumesUsageDescription": "Manage the media library on your selected iPod.",
        },
    )
