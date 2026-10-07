"""Build and check an unsigned Windows MSIX from the locked packaging environment.

Run with ``uv run --locked --no-dev --group packaging python -m scripts.build_msix``.
Installed-package and Certification Kit checks require signing and a test machine;
see ``packaging/windows/test-installed-package.ps1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree

from scripts import build_windows_sndfile, package_app
from scripts.check_windows_bundle import check_windows_bundle

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAMESPACE = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"


def find_makeappx(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"MakeAppx.exe was not found: {explicit}")
        return explicit.resolve()
    on_path = shutil.which("MakeAppx.exe")
    if on_path is not None:
        return Path(on_path).resolve()
    candidates: list[Path] = []
    for program_files in (
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
    ):
        if program_files:
            sdk = Path(program_files) / "Windows Kits/10/bin"
            candidates.extend(sdk.glob("*/x64/makeappx.exe"))
            candidates.extend(sdk.glob("x64/makeappx.exe"))
    if candidates:

        def sdk_version(path: Path) -> tuple[int, ...]:
            parts = path.parent.parent.name.split(".")
            return (
                tuple(map(int, parts))
                if all(part.isdecimal() for part in parts)
                else ()
            )

        return max(candidates, key=sdk_version).resolve()
    raise FileNotFoundError(
        "MakeAppx.exe was not found. Install Windows SDK Build Tools or pass --makeappx."
    )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_embedded_build(executable: Path, version: str) -> None:
    """Check the exact frozen payload extracted from the MSIX."""
    check_windows_bundle(executable)
    reader = import_module("PyInstaller.archive.readers").CArchiveReader(
        str(executable)
    )
    embedded = {name.replace("\\", "/"): name for name in reader.toc}
    identity_name = embedded.get("updates/installation.json")
    if identity_name is None:
        raise ValueError("Packaged executable is missing its build identity")
    identity = json.loads(reader.extract(identity_name))
    if identity.get("version") != version or identity.get("target") != "windows-x86_64":
        raise ValueError("Packaged executable has the wrong build version or target")
    notices = ROOT / "build/packaging/licenses"
    expected = {
        "licenses/" + path.relative_to(notices).as_posix(): path
        for path in notices.rglob("*")
        if path.is_file()
    }
    # The PyInstaller spec adds this record after collecting the license tree.
    expected["licenses/libsndfile-build-record.json"] = (
        ROOT / "build/native-libs/sndfile/build-record.json"
    )
    if not expected or {
        name for name in embedded if name.startswith("licenses/")
    } != set(expected):
        raise ValueError("Packaged license inventory differs from the build")
    for name, source in expected.items():
        if hashlib.sha256(reader.extract(embedded[name])).hexdigest() != sha256(source):
            raise ValueError(
                f"Packaged license material differs from the build: {name}"
            )


def check_msix(package: Path, executable: Path, version: str) -> None:
    """Validate package members, identity, integrity, and the frozen app."""
    name, publisher, display_name = package_app.windows_store_identity()
    with zipfile.ZipFile(package) as archive:
        if bad_member := archive.testzip():
            raise ValueError(f"MSIX contains a corrupt member: {bad_member}")
        members = archive.namelist()
        if len(members) != len({member.casefold() for member in members}):
            raise ValueError("MSIX contains duplicate member names")
        required = {
            "AppxManifest.xml",
            "app/iOpenPod.exe",
            "Assets/StoreLogo.png",
            "Assets/Square44x44Logo.png",
            "Assets/Square150x150Logo.png",
            "AppxBlockMap.xml",
        }
        if not required.issubset(members):
            raise ValueError(
                f"MSIX is missing members: {sorted(required - set(members))}"
            )
        manifest = ElementTree.fromstring(archive.read("AppxManifest.xml"))
        identity = manifest.find(MANIFEST_NAMESPACE + "Identity")
        expected_identity = {
            "Name": name,
            "Publisher": publisher,
            "Version": version + ".0",
            "ProcessorArchitecture": "x64",
        }
        if identity is None or any(
            identity.get(key) != value for key, value in expected_identity.items()
        ):
            raise ValueError("MSIX identity, version, or architecture is incorrect")
        display = manifest.findtext(
            MANIFEST_NAMESPACE
            + "Properties/"
            + MANIFEST_NAMESPACE
            + "PublisherDisplayName"
        )
        if display != display_name:
            raise ValueError("MSIX publisher display name is incorrect")
        applications = manifest.findall(
            MANIFEST_NAMESPACE + "Applications/" + MANIFEST_NAMESPACE + "Application"
        )
        if (
            len(applications) != 1
            or applications[0].get("Executable") != "app\\iOpenPod.exe"
        ):
            raise ValueError("MSIX does not launch the packaged iOpenPod executable")
        with tempfile.TemporaryDirectory(prefix="iopenpod-msix-check-") as directory:
            packaged_executable = Path(directory) / "iOpenPod.exe"
            with (
                archive.open("app/iOpenPod.exe") as source,
                packaged_executable.open("wb") as destination,
            ):
                shutil.copyfileobj(source, destination)
            if sha256(packaged_executable) != sha256(executable):
                raise ValueError(
                    "MSIX executable differs from the checked Windows bundle"
                )
            check_embedded_build(packaged_executable, version)
            report = Path(directory) / "smoke.txt"
            subprocess.run(
                [
                    str(packaged_executable),
                    "--smoke-test",
                    "--smoke-test-report",
                    str(report),
                ],
                cwd=directory,
                check=True,
                timeout=180,
            )
            if not report.is_file() or report.read_text(encoding="utf-8").strip() != (
                "iOpenPod packaged runtime check passed."
            ):
                raise ValueError(
                    "Packaged executable did not pass its runtime smoke test"
                )


def build_msix(makeappx: Path, output: Path, *, reuse_bundle: bool = False) -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("Build this MSIX on Windows x64")
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to replace an existing MSIX: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    version = package_app.project_version()
    executable = ROOT / "dist/iOpenPod.exe"
    if reuse_bundle:
        if not executable.is_file():
            raise FileNotFoundError(f"Windows executable was not found: {executable}")
        print(f"Using the existing Windows executable: {executable}", flush=True)
    else:
        print("Building the audited Windows audio library...", flush=True)
        build_windows_sndfile.main()
        print("Freezing the Windows executable...", flush=True)
        package_app.freeze()
    check_windows_bundle(executable)
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="msix-work-", dir=ROOT / "build"
    ) as directory:
        name, publisher, display_name = package_app.windows_store_identity()
        staged = package_app.stage_msix(
            name, publisher, display_name, destination=Path(directory) / "stage"
        )
        print(f"Packing {output}...", flush=True)
        try:
            subprocess.run(
                [str(makeappx), "pack", "/d", str(staged), "/p", str(output)],
                cwd=ROOT,
                check=True,
            )
            check_msix(output, executable, version)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    digest = sha256(output)
    output.with_name(output.name + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8"
    )
    print(f"MSIX checks passed: {output}\nSHA-256: {digest}")
    print("Installed-app and Certification Kit checks require a signed test package.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makeappx", type=Path, help="Path to MakeAppx.exe")
    parser.add_argument(
        "--output", type=Path, help="New MSIX path; existing files are preserved"
    )
    parser.add_argument(
        "--reuse-bundle",
        action="store_true",
        help="Package the existing dist/iOpenPod.exe without rebuilding it",
    )
    args = parser.parse_args()
    version = package_app.project_version()
    output = args.output or ROOT / f"dist/iOpenPod-{version}-Windows-x64.msix"
    build_msix(find_makeappx(args.makeappx), output, reuse_bundle=args.reuse_bundle)


if __name__ == "__main__":
    main()
