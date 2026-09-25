"""Build the Windows internal-codec libsndfile with a pinned portable toolchain.

Run from the repository root with ``uv run python -m scripts.build_windows_sndfile``.
No packages are installed into the project environment and no system tools change.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from scripts.prepare_release_sources import fetch, read_manifest, verify

ROOT = Path(__file__).resolve().parents[1]
THIRD_PARTY = ROOT / "packaging" / "third-party"
WORK = ROOT / "build" / "native-libs" / "sndfile"
TOOLS = ROOT / "build" / "native-libs" / "tools"


def _extract_zip(archive: Path, destination: Path) -> None:
    """Validate member destinations before unpacking even hash-pinned tools."""
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if not (root / member.filename).resolve().is_relative_to(root):
                raise ValueError(f"Unsafe archive member: {member.filename}")
        bundle.extractall(root)


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This build recipe targets Windows x64.")
    if any(character in str(ROOT) for character in '%"\n\r'):
        raise SystemExit("Build from a path without cmd expansion characters.")
    TOOLS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    tool_records = read_manifest(THIRD_PARTY / "native-build-tools.json")
    for tool in tool_records:
        archive = fetch(tool, TOOLS)
        output = TOOLS if tool.name == "zig" else TOOLS / tool.name
        executable = "zig.exe" if tool.name == "zig" else tool.name + ".exe"
        if not tuple(output.rglob(executable)):
            _extract_zip(archive, output)

    source = next(
        record
        for record in read_manifest(THIRD_PARTY / "sources.json")
        if record.name == "libsndfile"
    )
    archives = ROOT / "build" / "release-sources"
    archives.mkdir(parents=True, exist_ok=True)
    archive = fetch(source, archives)
    source_root = WORK / f"libsndfile-{source.version}"
    if not source_root.exists():
        with tarfile.open(archive) as source_tar:
            source_tar.extractall(WORK, filter="data")

    # This is the exact change documented by the distributed patch. Resource
    # metadata is cosmetic; avoiding an SDK resource compiler keeps the native
    # build self-contained. sf_version_string still reports the library version.
    cmake_lists = source_root / "CMakeLists.txt"
    before = "\t\ttarget_sources (sndfile PRIVATE ${PROJECT_BINARY_DIR}/src/version-metadata.rc)"
    after = "\t\t# iOpenPod portable build: omit cosmetic VERSIONINFO resource."
    content = cmake_lists.read_text(encoding="utf-8")
    if before in content:
        cmake_lists.write_text(content.replace(before, after), encoding="utf-8")
    elif after not in content:
        raise ValueError(
            "Unexpected libsndfile CMakeLists: cannot apply recorded patch"
        )

    zig = TOOLS / "zig-x86_64-windows-0.14.1" / "zig.exe"
    cmake = TOOLS / "cmake" / "cmake" / "data" / "bin" / "cmake.exe"
    ninja = TOOLS / "ninja" / "ninja-1.13.0.data" / "scripts" / "ninja.exe"
    for language, filename in (("cc", "zig-cc.cmd"), ("c++", "zig-cpp.cmd")):
        (WORK / filename).write_text(
            f'@echo off\n"{zig}" {language} -target x86_64-windows-gnu %*\n',
            encoding="utf-8",
        )
    config = {
        "CMAKE_BUILD_TYPE": "Release",
        "BUILD_SHARED_LIBS": "ON",
        "ENABLE_EXTERNAL_LIBS": "OFF",
        "ENABLE_MPEG": "OFF",
        "BUILD_TESTING": "OFF",
        "BUILD_PROGRAMS": "OFF",
        "BUILD_EXAMPLES": "OFF",
        "ENABLE_CPACK": "OFF",
        "INSTALL_MANPAGES": "OFF",
        "ENABLE_STATIC_RUNTIME": "OFF",
        "CMAKE_POLICY_VERSION_MINIMUM": "3.5",
    }
    command = [
        str(cmake),
        "-S",
        str(source_root),
        "-B",
        str(WORK / "build"),
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={ninja}",
        f"-DCMAKE_C_COMPILER={WORK / 'zig-cc.cmd'}",
        f"-DCMAKE_CXX_COMPILER={WORK / 'zig-cpp.cmd'}",
    ]
    command.extend(f"-D{key}={value}" for key, value in config.items())
    environment = os.environ.copy()
    environment["ZIG_GLOBAL_CACHE_DIR"] = str(
        ROOT / "build" / "native-libs" / "zig-cache"
    )
    subprocess.run(command, check=True, env=environment)
    subprocess.run(
        [str(cmake), "--build", str(WORK / "build"), "--parallel", "2"],
        check=True,
        env=environment,
    )
    destination = WORK / "libsndfile_x64.dll"
    shutil.copy2(WORK / "build" / "libsndfile.dll", destination)
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    patch = THIRD_PARTY / "libsndfile-no-version-resource.patch"
    record = {
        "name": "libsndfile",
        "version": source.version,
        "sha256": digest,
        "size": destination.stat().st_size,
        "compiler": "Zig 0.14.1 (Clang 19.1.7), x86_64-windows-gnu",
        "cmake": "4.1.3",
        "ninja": "1.13.0",
        "config": config,
        "source": source.filename,
        "source_sha256": source.sha256,
        "patch": patch.relative_to(ROOT).as_posix(),
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "tools": [
            {"name": item.name, "version": item.version, "sha256": item.sha256}
            for item in tool_records
        ],
    }
    verify(source, archives)
    (WORK / "build-record.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Built {destination}: {digest}")


if __name__ == "__main__":
    main()
