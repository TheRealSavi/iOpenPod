# -*- mode: python ; coding: utf-8 -*-
import sys
import subprocess as _subprocess
from pathlib import Path as _Path

_spec_root = _Path(SPECPATH).resolve()
if str(_spec_root) not in sys.path:
    sys.path.insert(0, str(_spec_root))

from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from scripts.pyinstaller_helpers import wasmtime_binaries

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
        import platform as _platform
        _wasmtime_binaries = wasmtime_binaries(
            _wpkg,
            platform=sys.platform,
            machine=_platform.machine(),
        )
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

_libusb_binaries = []
try:
    import libusb_package

    _libusb_path = libusb_package.get_library_path()
    if _libusb_path:
        _libusb_binaries.append((str(_libusb_path), 'libusb_package'))
except Exception:
    pass

a = Analysis(
    ['src/iopenpod/__main__.py'],
    pathex=[],
    binaries=[*_wasmtime_binaries, *_linux_qt_xcb_binaries, *_libusb_binaries],
    datas=[
        ('src/iopenpod/assets', 'iopenpod/assets'),
        ('src/iopenpod/themes', 'iopenpod/themes'),
        ('src/iopenpod/itunesdb_writer/wasm', 'iopenpod/itunesdb_writer/wasm'),
        *collect_data_files('tzdata'),
        *copy_metadata('iopenpod'),
    ],
    hiddenimports=[
        'libusb_package',
        'usb.backend.libusb1',
        'packaging.version',
        'tzdata',
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

_use_upx = sys.platform != 'linux'

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='iOpenPod',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=_use_upx,
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
    upx=_use_upx,
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
