"""Check the built Windows executable and payload before creating an MSIX."""

import sys
import xml.etree.ElementTree as ET
from importlib import import_module
from pathlib import Path


def check_windows_bundle(bundle: Path) -> None:
    if sys.platform != "win32":
        raise ValueError("Check the Windows bundle on Windows")
    # Use the locked build tool's resource reader, without executing the app.
    reader = import_module("PyInstaller.utils.win32.winmanifest")
    manifest_xml: object = reader.read_manifest_from_executable(
        str(bundle / "iOpenPod.exe")
    )
    if not isinstance(manifest_xml, bytes):
        raise ValueError("Executable manifest reader did not return XML bytes")
    manifest = ET.fromstring(manifest_xml)
    settings = "http://schemas.microsoft.com/SMI/2016/WindowsSettings"
    issues: list[str] = []
    if manifest.findtext(f".//{{{settings}}}dpiAwareness") != "PerMonitorV2":
        issues.append("Executable does not declare PerMonitorV2 DPI awareness")
    level = manifest.find(
        ".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel"
    )
    if level is None or level.get("level") != "asInvoker":
        issues.append("Executable must run as the current user without elevation")
    payload = bundle / "_internal"
    if (payload / "sklearn/datasets").exists():
        issues.append("Unused scikit-learn sample datasets are bundled")
    if any((payload / "sklearn").rglob("tests")):
        issues.append("Scikit-learn test fixtures are bundled")
    if (payload / "_tcl_data").exists() or (payload / "_tkinter.pyd").exists():
        issues.append("Unused Tcl/Tk runtime is bundled")
    external_tools = {"ffmpeg.exe", "ffprobe.exe", "fpcalc.exe"}
    issues.extend(
        f"User-installed media tool is bundled: {path.relative_to(bundle)}"
        for path in bundle.rglob("*")
        if path.is_file() and path.name.lower() in external_tools
    )
    if (payload / "media-tools").exists():
        issues.append("Obsolete bundled media-tools directory is present")
    unused_qt = {
        "qt6pdf.dll",
        "qpdf.dll",
        "qt6virtualkeyboard.dll",
        "qtvirtualkeyboardplugin.dll",
    }
    issues.extend(
        f"Unused Qt component is bundled: {path.relative_to(bundle)}"
        for path in (payload / "PySide6").rglob("*.dll")
        if path.name.lower() in unused_qt
    )
    if issues:
        raise ValueError("Windows bundle checks failed:\n" + "\n".join(issues))


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    check_windows_bundle(root / "dist/iOpenPod")
    print("Windows executable manifest and payload checks passed.")
