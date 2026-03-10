# -*- mode: python ; coding: utf-8 -*-
import sys
import platform as _platform
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

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[*_wasmtime_binaries],
    datas=[
        ('assets', 'assets'),
        ('iTunesDB_Writer/wasm', 'iTunesDB_Writer/wasm'),
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
    icon='assets/icons/icon.ico' if sys.platform == 'win32' else 'assets/icons/icon-256.png',
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
        icon='assets/icons/icon-256.png',
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
