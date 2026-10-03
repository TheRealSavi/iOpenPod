"""An independent onefile helper; deliberately excludes the GUI runtime."""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / "src/iopenpod_update_helper.py")],
    pathex=[str(root / "src")],
    datas=[(str(root / "build/packaging/updates/installation.json"), "updates")],
    binaries=[],
    hiddenimports=collect_submodules("Crypto", filter=lambda name: not name.startswith("Crypto.SelfTest")) + (["msvcrt"] if sys.platform == "win32" else ["fcntl"]),
    excludes=["PySide6", "numpy", "scipy", "librosa", "torch", "pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas,
          name="iOpenPod-update", console=sys.platform != "win32", upx=False, strip=False)
