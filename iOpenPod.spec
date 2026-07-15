# -*- mode: python ; coding: utf-8 -*-
import sys
import platform as _platform
import subprocess as _subprocess
from pathlib import Path as _Path
from PyInstaller.utils.hooks import copy_metadata

# Read version from pyproject.toml so it stays in sync
_version = "0.0.0"
try:
    import tomllib
    with open("pyproject.toml", "rb") as _f:
        _version = tomllib.load(_f)["project"]["version"]
except Exception:
    pass

# Collect wasmtime native library (needed for HASHAB on Nano 6G/7G)
_wasmtime_binaries = []
try:
    import importlib.util as _iu
    _ws = _iu.find_spec('wasmtime')
    if _ws and _ws.submodule_search_locations:
        _wpkg = _Path(list(_ws.submodule_search_locations)[0])
        _machine = _platform.machine()
        if _machine == 'AMD64':
            _machine = 'x86_64'
        elif _machine in ('arm64', 'ARM64'):
            _machine = 'aarch64'
        _wplat = _wpkg / f'{sys.platform}-{_machine}'
        if _wplat.is_dir():
            _wasmtime_binaries = [
                (str(f), f'wasmtime/{_wplat.name}')
                for f in _wplat.iterdir() if f.is_file()
            ]
except Exception:
    pass

_linux_qt_xcb_binaries = []
if sys.platform == 'linux':
    # Qt's xcb platform plugin loads these small utility libraries from the
    # host unless we copy them into the frozen bundle.
    _linux_qt_xcb_sonames = (
        'libxcb-cursor.so.0',
        'libxcb-icccm.so.4',
        'libxcb-image.so.0',
        'libxcb-keysyms.so.1',
        'libxcb-render-util.so.0',
        'libxcb-util.so.1',
        'libxcb-xkb.so.1',
        'libxkbcommon.so.0',
        'libxkbcommon-x11.so.0',
    )

    def _ldconfig_paths():
        try:
            output = _subprocess.check_output(
                ['ldconfig', '-p'],
                stderr=_subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            return {}

        paths = {}
        for line in output.splitlines():
            if '=>' not in line:
                continue
            left, right = line.split('=>', 1)
            name = left.strip().split()[0]
            paths[name] = right.strip()
        return paths

    _ldconfig_cache = _ldconfig_paths()
    _library_dirs = (
        _Path('/lib'),
        _Path('/usr/lib'),
        _Path('/lib/x86_64-linux-gnu'),
        _Path('/usr/lib/x86_64-linux-gnu'),
        _Path('/lib/aarch64-linux-gnu'),
        _Path('/usr/lib/aarch64-linux-gnu'),
    )
    for _soname in _linux_qt_xcb_sonames:
        _path = _ldconfig_cache.get(_soname)
        if not _path:
            for _directory in _library_dirs:
                _candidate = _directory / _soname
                if _candidate.exists():
                    _path = str(_candidate)
                    break
        if _path:
            _linux_qt_xcb_binaries.append((_path, '.'))

a = Analysis(
    ['src/iopenpod/__main__.py'],
    pathex=[],
    binaries=[*_wasmtime_binaries, *_linux_qt_xcb_binaries],
    datas=[
        ('src/iopenpod/assets', 'iopenpod/assets'),
        ('src/iopenpod/itunesdb_writer/wasm', 'iopenpod/itunesdb_writer/wasm'),
        *copy_metadata('iopenpod'),
    ],
    hiddenimports=[
        'usb.backend.libusb1',
        'packaging.version',
        'wasmtime',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_macos_nsapp.py'] if sys.platform == 'darwin' else [],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# ── Linux: exclude Qt platform input-context plugins ──────────────────────
# PyInstaller bundles platforminputcontexts plugins (fcitx, ibus, compose)
# compiled against the build machine's Qt.  At runtime these often ABI-clash
# with the host's input-method framework, causing a SIGSEGV on any keypress.
# Excluding them lets Qt fall back to the system's own plugins or to no
# input method (fine for an app that doesn't need CJK/IME composition).
if sys.platform == 'linux':
    a.binaries = [
        b for b in a.binaries
        if 'platforminputcontexts' not in b[0]
    ]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='iOpenPod',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='entitlements.plist' if sys.platform == 'darwin' else None,
    icon='src/iopenpod/assets/icons/icon.ico' if sys.platform == 'win32' else 'src/iopenpod/assets/icons/icon-256.png',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='iOpenPod',
)

# macOS: wrap COLLECT output into an .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='iOpenPod.app',
        icon='src/iopenpod/assets/icons/icon-256.png',
        bundle_identifier='com.iopenpod.app',
        info_plist={
            'CFBundleShortVersionString': _version,
            'CFBundleVersion': _version,
            'NSPrincipalClass': 'NSApplication',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.15',
            'NSRequiresAquaSystemAppearance': False,
        },
    )
