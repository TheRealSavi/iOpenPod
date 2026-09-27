"""Reject native bundle slices that cannot load at the declared macOS minimum.

Read Mach-O deployment commands directly, including both slices of universal
files. Wheel tags and Info.plist alone do not establish binary compatibility.
This does not prove that every imported system symbol exists on the target OS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import plistlib
import struct
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_THIN_MAGICS = {
    b"\xce\xfa\xed\xfe": ("<", 28),
    b"\xcf\xfa\xed\xfe": ("<", 32),
    b"\xfe\xed\xfa\xce": (">", 28),
    b"\xfe\xed\xfa\xcf": (">", 32),
}
_FAT_MAGICS = {
    b"\xca\xfe\xba\xbe": (">", False),
    b"\xbe\xba\xfe\xca": ("<", False),
    b"\xca\xfe\xba\xbf": (">", True),
    b"\xbf\xba\xfe\xca": ("<", True),
}
_ARCHITECTURES = {0x01000007: "x86_64", 0x0100000C: "arm64"}


@dataclass(frozen=True)
class MachOSlice:
    architecture: str
    minimum: tuple[int, int, int]
    sdk: tuple[int, int, int]
    platform: int


def _version(value: int) -> tuple[int, int, int]:
    return value >> 16, (value >> 8) & 255, value & 255


def _version_text(value: tuple[int, int, int]) -> str:
    return ".".join(map(str, value))


def _thin_slice(data: bytes) -> MachOSlice:
    layout = _THIN_MAGICS.get(data[:4])
    if layout is None:
        raise ValueError("Universal entry does not contain a thin Mach-O file")
    endian, header_size = layout
    if len(data) < header_size:
        raise ValueError("Truncated Mach-O header")
    cpu = struct.unpack_from(endian + "I", data, 4)[0]
    architecture = _ARCHITECTURES.get(cpu, f"unknown-{cpu:#x}")
    count, commands_size = struct.unpack_from(endian + "II", data, 16)
    end = header_size + commands_size
    if end > len(data) or count > commands_size // 8:
        raise ValueError("Invalid Mach-O load-command table")
    position = header_size
    deployment: MachOSlice | None = None
    for _ in range(count):
        if position + 8 > end:
            raise ValueError("Truncated Mach-O load command")
        command, size = struct.unpack_from(endian + "II", data, position)
        if size < 8 or position + size > end:
            raise ValueError("Invalid Mach-O load-command size")
        if command in {0x24, 0x32}:  # LC_VERSION_MIN_MACOSX, LC_BUILD_VERSION
            if deployment is not None:
                raise ValueError("Multiple Mach-O deployment declarations")
            if command == 0x24:
                if size < 16:
                    raise ValueError("Truncated LC_VERSION_MIN_MACOSX")
                minimum, sdk = struct.unpack_from(endian + "II", data, position + 8)
                target_platform = 1
            else:
                if size < 24:
                    raise ValueError("Truncated LC_BUILD_VERSION")
                target_platform, minimum, sdk, tools = struct.unpack_from(
                    endian + "IIII", data, position + 8
                )
                if 24 + tools * 8 > size:
                    raise ValueError("Truncated LC_BUILD_VERSION tool table")
            deployment = MachOSlice(
                architecture, _version(minimum), _version(sdk), target_platform
            )
        position += size
    if position != end:
        raise ValueError("Mach-O load-command sizes do not match the header")
    if deployment is None or deployment.minimum == (0, 0, 0):
        raise ValueError("Mach-O slice has no minimum OS declaration")
    return deployment


def macho_slices(data: bytes) -> tuple[MachOSlice, ...]:
    """Read a native file; return no slices for ordinary resources."""
    magic = data[:4]
    if magic in _THIN_MAGICS:
        return (_thin_slice(data),)
    layout = _FAT_MAGICS.get(magic)
    if layout is None:
        return ()
    endian, fat64 = layout
    if len(data) < 8:
        raise ValueError("Truncated universal header")
    count = struct.unpack_from(endian + "I", data, 4)[0]
    entry_size = 32 if fat64 else 20
    table_end = 8 + count * entry_size
    if not 1 <= count <= 128 or table_end > len(data):
        raise ValueError("Invalid universal architecture table")
    slices: list[MachOSlice] = []
    ranges: list[tuple[int, int]] = []
    for index in range(count):
        position = 8 + index * entry_size
        cpu = struct.unpack_from(endian + "I", data, position)[0]
        offset, size = struct.unpack_from(
            endian + ("QQ" if fat64 else "II"), data, position + 8
        )
        end = offset + size
        if offset < table_end or size < 4 or end > len(data):
            raise ValueError("Universal slice is outside the file")
        if any(offset < previous_end and start < end for start, previous_end in ranges):
            raise ValueError("Universal slices overlap")
        ranges.append((offset, end))
        native_slice = _thin_slice(data[offset:end])
        if native_slice.architecture != _ARCHITECTURES.get(cpu, f"unknown-{cpu:#x}"):
            raise ValueError("Universal and thin architecture declarations disagree")
        slices.append(native_slice)
    if len({item.architecture for item in slices}) != len(slices):
        raise ValueError("Universal file repeats an architecture")
    return tuple(slices)


def check_macos_bundle(bundle: Path, architecture: str) -> dict[str, object]:
    """Check metadata and every unique native file without changing the bundle."""
    if architecture not in _ARCHITECTURES.values():
        raise ValueError(f"Unsupported bundle architecture: {architecture}")
    with (ROOT / "pyproject.toml").open("rb") as stream:
        minimum_text = str(
            tomllib.load(stream)["tool"]["iopenpod"]["packaging"][
                "macos-minimum-version"
            ]
        )
    components = tuple(map(int, minimum_text.split(".")))
    if len(components) not in {2, 3}:
        raise ValueError("Expected major.minor[.patch] macOS minimum")
    minimum = (*components, 0) if len(components) == 2 else components
    with (bundle / "Contents/Info.plist").open("rb") as stream:
        plist = plistlib.load(stream)
    issues: list[str] = []
    if plist.get("LSMinimumSystemVersion") != minimum_text:
        issues.append("Info.plist minimum differs from the packaging target")
    if not (bundle / "Contents/MacOS/iOpenPod").is_file():
        issues.append("Application executable is missing")
    seen: set[Path] = set()
    native_paths: set[Path] = set()
    files: list[dict[str, object]] = []
    resolved_bundle = bundle.resolve()
    for path in sorted(bundle.rglob("*")):
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_bundle):
            issues.append(f"Bundle link escapes the app: {path.relative_to(bundle)}")
            continue
        if path.is_symlink() and not path.exists():
            issues.append(f"Broken bundle link: {path.relative_to(bundle)}")
        if not path.is_file() or resolved in seen:
            continue
        seen.add(resolved)
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic not in _THIN_MAGICS and magic not in _FAT_MAGICS:
            continue
        relative = path.relative_to(bundle).as_posix()
        data = path.read_bytes()
        try:
            slices = macho_slices(data)
        except ValueError as error:
            issues.append(f"{relative}: {error}")
            continue
        native_paths.add(resolved)
        if architecture not in {item.architecture for item in slices}:
            issues.append(f"{relative}: no {architecture} slice")
        for item in slices:
            if item.architecture not in _ARCHITECTURES.values():
                issues.append(f"{relative}: unsupported slice {item.architecture}")
            if item.platform != 1:
                issues.append(f"{relative}: platform {item.platform} is not macOS")
            if item.minimum > minimum:
                issues.append(
                    f"{relative} ({item.architecture}) requires "
                    f"{_version_text(item.minimum)}, above {minimum_text}"
                )
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "slices": [
                    {
                        "architecture": item.architecture,
                        "minimum": _version_text(item.minimum),
                        "sdk": _version_text(item.sdk),
                        "platform": item.platform,
                    }
                    for item in slices
                ],
            }
        )
    if not files:
        issues.append("Bundle contains no native Mach-O files")
    if (bundle / "Contents/MacOS/iOpenPod").resolve() not in native_paths:
        issues.append("Application executable is not a valid native Mach-O file")
    if issues:
        raise ValueError("macOS bundle checks failed:\n" + "\n".join(issues))
    return {
        "minimum_macos": minimum_text,
        "architecture": architecture,
        "native_files": files,
        "target_os_execution": "pending",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/iOpenPod.app")
    parser.add_argument(
        "--architecture", choices=("arm64", "x86_64"), default=platform.machine()
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "build/packaging/macos-compatibility.json"
    )
    arguments = parser.parse_args()
    report = check_macos_bundle(arguments.bundle, arguments.architecture)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"macOS metadata and deployment checks passed: {arguments.report}")
