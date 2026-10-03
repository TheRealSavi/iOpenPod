"""Build native bundles and stage store packages using the locked UV environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from importlib import metadata
from pathlib import Path
from xml.sax.saxutils import escape

from packaging.requirements import Requirement
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "build/packaging"
APP_ID = "io.github.therealsavi.iOpenPod"


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        value = str(tomllib.load(stream)["project"]["version"])
    if re.fullmatch(r"\d+\.\d+\.\d+", value) is None:
        raise ValueError(
            "Native packaging requires a numeric major.minor.patch version"
        )
    if any(int(part) > 65535 for part in value.split(".")):
        raise ValueError("Version components must fit the MSIX 16-bit fields")
    return value


def generate_assets() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    icons = ROOT / "src/iOpenPod/assets/icons"
    with Image.open(icons / "icon-256.png") as source:
        image = source.convert("RGBA")
        image.resize((1024, 1024), Image.Resampling.LANCZOS).save(
            GENERATED / "iOpenPod.icns", format="ICNS"
        )
        tiles = GENERATED / "Assets"
        tiles.mkdir(exist_ok=True)
        for name, size in (
            ("StoreLogo", 50),
            ("Square44x44Logo", 44),
            ("Square150x150Logo", 150),
        ):
            image.resize((size, size), Image.Resampling.LANCZOS).save(
                tiles / f"{name}.png"
            )
    version = project_version()
    fields = (*map(int, version.split(".")), 0)
    (GENERATED / "windows-version.txt").write_text(
        "VSVersionInfo(ffi=FixedFileInfo("
        f"filevers={fields!r}, prodvers={fields!r}, mask=0x3f, flags=0, "
        "OS=0x40004, fileType=1, subtype=0, date=(0, 0)), kids=["
        "StringFileInfo([StringTable('040904B0', ["
        "StringStruct('ProductName', 'iOpenPod'), "
        "StringStruct('FileDescription', 'iOpenPod'), "
        f"StringStruct('FileVersion', '{version}.0'), "
        f"StringStruct('ProductVersion', '{version}')"
        "])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n",
        encoding="utf-8",
    )


def collect_notices() -> None:
    """Collect the installed runtime dependency closure, excluding build tools."""
    target = GENERATED / "licenses"
    if target.exists():
        if target.resolve().parent != GENERATED.resolve():
            raise ValueError(
                "Refusing to replace a notices directory outside the build"
            )
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    upstream = ROOT / "packaging/third-party"
    # Wheels can omit native-library and open-source Qt license texts. The
    # reviewed upstream notices supplement, rather than replace, wheel notices.
    shutil.copytree(upstream, target / "upstream")
    shutil.copy2(ROOT / "LICENSE", target / "iOpenPod-LICENSE.txt")
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    for pattern in project["license-files"]:
        for source in ROOT.glob(pattern):
            destination = target / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    shutil.copy2(
        ROOT / "src/iPodDB/iTunesDB/writer/calcHashAB.NOTICE",
        target / "calcHashAB.NOTICE",
    )
    pending = ["iOpenPod"]
    seen: set[str] = set()
    inventory: list[dict[str, object]] = []
    while pending:
        dist = metadata.distribution(pending.pop())
        name = dist.metadata["Name"]
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        seen.add(key)
        directory = target / key
        directory.mkdir(exist_ok=True)
        copied: list[str] = []
        for path in dist.files or ():
            # PyObjC ships copying tests and their dSYM files. Matching that
            # word alone would turn native test/debug binaries into notices.
            if path.suffix.lower() in {
                ".py",
                ".pyc",
                ".pyo",
                ".pyi",
                ".so",
                ".dylib",
                ".dll",
                ".pyd",
                ".o",
                ".obj",
                ".a",
                ".lib",
            } or any(part.lower().endswith(".dsym") for part in path.parts):
                continue
            if not any(
                word in path.name.lower()
                for word in ("license", "licence", "copying", "notice")
            ):
                continue
            source = Path(str(dist.locate_file(path)))
            if source.is_file():
                destination = directory / str(path).replace("/", "_").replace("\\", "_")
                shutil.copy2(source, destination)
                copied.append(destination.name)
        inventory.append(
            {
                "name": name,
                "version": dist.version,
                "license": dist.metadata.get("License-Expression")
                or dist.metadata.get("License", ""),
                "license_files": copied,
            }
        )
        for dependency in dist.requires or ():
            requirement = Requirement(dependency)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    (target / "inventory.json").write_text(
        json.dumps(sorted(inventory, key=lambda item: str(item["name"])), indent=2)
        + "\n",
        encoding="utf-8",
    )


def freeze() -> None:
    """Build the app; command-line media tools are installed by the user."""
    from scripts.package_updates import embed_sparkle, write_build_identity

    environment = dict(os.environ)
    if sys.platform == "darwin":
        with (ROOT / "pyproject.toml").open("rb") as stream:
            config = tomllib.load(stream)["tool"]["iopenpod"]["packaging"]
        environment["MACOSX_DEPLOYMENT_TARGET"] = config["macos-minimum-version"]
    if sys.platform == "win32":
        # Native dependency discovery must not import DLLs from unrelated Host
        # tools. In particular Poppler's icuuc.dll shadows Windows' ICU API with
        # incompatible exported symbols, preventing QtCore from loading.
        windows = Path(os.environ["SYSTEMROOT"])
        environment["PATH"] = os.pathsep.join(
            map(
                str,
                (
                    Path(sys.executable).parent,
                    Path(sys.base_prefix),
                    windows / "System32",
                    windows,
                ),
            )
        )
    generate_assets()
    collect_notices()
    write_build_identity(ROOT, GENERATED, project_version())
    if sys.platform != "darwin":
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                str(ROOT / "packaging/update-helper.spec"),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(ROOT / "packaging/iOpenPod.spec"),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    if sys.platform == "darwin":
        embed_sparkle(ROOT, GENERATED, config["macos-minimum-version"])


def windows_store_identity() -> tuple[str, str, str]:
    """Read the public package identity supplied by the listing's owner."""
    with (ROOT / "packaging/windows/store-identity.toml").open("rb") as stream:
        config = tomllib.load(stream)
    values: list[str] = []
    for field in ("name", "publisher", "publisher_display_name"):
        value: object = config.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing Windows Store identity field: {field}")
        values.append(value)
    return values[0], values[1], values[2]


def stage_msix(identity: str, publisher: str, display_name: str) -> Path:
    """Use Partner Center identity, never a fabricated signing/publisher identity."""
    if sys.platform != "win32":
        raise ValueError("Stage MSIX from the Windows build on Windows")
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,50}", identity):
        raise ValueError(
            "Identity must be the 3-50 character Partner Center package name"
        )
    if not publisher.startswith("CN=") or not display_name.strip():
        raise ValueError(
            "Provide the exact Partner Center Publisher (CN=...) and display name"
        )
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine
    )
    if arch is None:
        raise ValueError(f"Unsupported MSIX build architecture: {machine}")
    executable = ROOT / "dist/iOpenPod.exe"
    if not executable.is_file():
        raise ValueError("Build the native bundle first")
    # Re-running must not silently retain obsolete binaries or assets.
    destination = ROOT / "build/msix"
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "app").mkdir()
    shutil.copy2(executable, destination / "app/iOpenPod.exe")
    generate_assets()
    shutil.copytree(GENERATED / "Assets", destination / "Assets")
    template = (ROOT / "packaging/windows/AppxManifest.xml.in").read_text(
        encoding="utf-8"
    )
    for name, value in {
        "IDENTITY": identity,
        "PUBLISHER": publisher,
        "PUBLISHER_DISPLAY_NAME": display_name,
        "VERSION": project_version() + ".0",
        "ARCH": arch,
    }.items():
        template = template.replace(f"@{name}@", escape(value, {'"': "&quot;"}))
    (destination / "AppxManifest.xml").write_text(template, encoding="utf-8")
    return destination


def stage_linux() -> Path:
    if sys.platform != "linux":
        raise ValueError("Stage Linux packages from a native Linux build")
    bundle = ROOT / "dist/iOpenPod"
    if not (bundle / "iOpenPod").is_file():
        raise ValueError("Build the native bundle first")
    destination = ROOT / "build/linux-root"
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(bundle, destination / "lib/iopenpod", symlinks=True)
    binary = destination / "bin/iOpenPod"
    binary.parent.mkdir()
    binary.write_text(
        '#!/bin/sh\nHERE="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"\n'
        'exec "$HERE/lib/iopenpod/iOpenPod" "$@"\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    for filename, relative in (
        (f"{APP_ID}.desktop", "share/applications"),
        (f"{APP_ID}.metainfo.xml", "share/metainfo"),
    ):
        directory = destination / relative
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "packaging/linux" / filename, directory)
    icons = destination / "share/icons/hicolor/256x256/apps"
    icons.mkdir(parents=True)
    shutil.copy2(
        ROOT / "src/iOpenPod/assets/icons/icon-256.png", icons / f"{APP_ID}.png"
    )
    (destination / "version.txt").write_text(project_version() + "\n", encoding="utf-8")
    return destination


def _write_checksum(path: Path) -> None:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    path.with_name(path.name + ".sha256").write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )


def macos_dmg(app: Path, output: Path, version: str) -> Path:
    """Build a drag-to-Applications image from the signed app bundle."""
    if not app.is_dir():
        raise ValueError("Build the macOS app bundle before making a disk image")
    if output.exists():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(
        prefix="iopenpod-dmg-", dir=output.parent
    ) as staging_name:
        staging = Path(staging_name)
        subprocess.run(["ditto", str(app), str(staging / "iOpenPod.app")], check=True)
        (staging / "Applications").symlink_to("/Applications", target_is_directory=True)
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-srcfolder",
                str(staging),
                "-volname",
                f"iOpenPod {version}",
                "-format",
                "UDZO",
                "-fs",
                "HFS+",
                str(output),
            ],
            check=True,
        )
    subprocess.run(["hdiutil", "verify", str(output)], check=True)
    _write_checksum(output)
    return output


def archive() -> Path:
    from scripts.package_updates import managed_linux_archive

    version = project_version()
    system = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}[sys.platform]
    name = f"iOpenPod-{version}-{system}-{platform.machine()}"
    output = ROOT / "dist" / name
    if sys.platform == "darwin":
        path = Path(str(output) + ".zip")
        subprocess.run(
            [
                "ditto",
                "-c",
                "-k",
                "--keepParent",
                "--sequesterRsrc",
                str(ROOT / "dist/iOpenPod.app"),
                str(path),
            ],
            check=True,
        )
    elif sys.platform == "linux":
        path = Path(str(output) + ".tar.gz")
        managed_linux_archive(ROOT, path, version)
    else:
        path = Path(
            shutil.make_archive(
                str(output),
                "zip" if sys.platform == "win32" else "gztar",
                root_dir=ROOT / "dist",
                base_dir="iOpenPod.exe" if sys.platform == "win32" else "iOpenPod",
            )
        )
    _write_checksum(path)
    if sys.platform == "darwin":
        macos_dmg(ROOT / "dist/iOpenPod.app", path.with_suffix(".dmg"), version)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("assets")
    commands.add_parser("freeze")
    msix = commands.add_parser("msix-stage")
    msix.add_argument(
        "--identity", help="Override the saved Partner Center package name"
    )
    msix.add_argument("--publisher", help="Override the saved Partner Center publisher")
    msix.add_argument(
        "--publisher-display-name", help="Override the saved publisher display name"
    )
    commands.add_parser("linux-stage")
    commands.add_parser("archive")
    commands.add_parser("check-version").add_argument("tag")
    args = parser.parse_args()
    if args.command == "assets":
        generate_assets()
    elif args.command == "freeze":
        freeze()
    elif args.command == "msix-stage":
        identity, publisher, display_name = windows_store_identity()
        print(
            stage_msix(
                args.identity if args.identity is not None else identity,
                args.publisher if args.publisher is not None else publisher,
                args.publisher_display_name
                if args.publisher_display_name is not None
                else display_name,
            )
        )
    elif args.command == "linux-stage":
        print(stage_linux())
    elif args.command == "archive":
        print(archive())
    elif args.tag != f"v{project_version()}":
        parser.error(f"Tag must equal v{project_version()}")


if __name__ == "__main__":
    if not __package__:
        sys.path.insert(0, str(ROOT))
    main()
