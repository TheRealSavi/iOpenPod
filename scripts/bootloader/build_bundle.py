"""Rebuild a distributable Classic delta and parameterized RAM writer offline.

Requires ARM GNU 13.3.rel1 and the qualified research inputs, never USB access.
The installed application needs neither these inputs nor the compiler.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from scripts.bootloader.profiles import PROFILES, SHARED_PROFILE

from iOpenPod.app.firmware.classic_layout import MINIMUM_BOOTLOADER_VERSION

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("native")
ROM = "69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4"


def digest(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"Unqualified build input: {path}")
    return data


def delta(before: bytes, after: bytes) -> bytes:
    """A bounded list of replacement runs, compressed without external libraries."""
    runs = bytearray()
    start = 0
    while start < len(before):
        if before[start] == after[start]:
            start += 1
            continue
        end = start + 1
        while end < len(before) and before[end] != after[end]:
            end += 1
        runs.extend(struct.pack("<II", start, end - start))
        runs.extend(after[start:end])
        start = end
    return zlib.compress(runs, level=9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--family", type=int, choices=PROFILES)
    selection.add_argument("--shared", action="store_true")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Shared migration input FAMILY=stock-loader.bin (24,33,35; --stock supplies 38)",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--previous-shared", type=Path)
    for name in ("stock", "loader", "bootrom", "toolchain", "mkdfu-source"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    profile = SHARED_PROFILE if args.shared else PROFILES[args.family or 33]
    assets = args.output_dir or ROOT / (
        "src/iOpenPod/assets/bootloader/classic-shared"
        if profile.shared
        else f"src/iOpenPod/assets/bootloader/classic{profile.family}"
    )
    marker_offset = profile.marker_offset
    gap_start = marker_offset + 64
    tail_bytes = 0x1F800 - profile.seccore_offset
    packed_size = gap_start + tail_bytes
    stock = checked(args.stock, profile.stock_sha256)
    legacy = checked(args.loader, profile.unmarked_sha256)
    rom = checked(args.bootrom, ROM)
    shared_v2 = None
    if profile.shared:
        if args.previous_shared is None:
            raise ValueError("Shared bundle requires the previous 2.0.0 body")
        shared_v2 = checked(
            args.previous_shared,
            "9cb983b4bc8b5707074cdc06ce4a3634a78694ddea3449adb7727c6c4449100c",
        )
    target = bytearray(legacy)
    # PAD FFS: 24-byte header, no payload checksum (attributes == 0).
    if legacy[marker_offset - 6 : marker_offset - 4] != b"\xf0\x00":
        raise ValueError("Unexpected PAD FFS attributes")
    if legacy[marker_offset : profile.seccore_offset] != b"\xff" * (
        profile.seccore_offset - marker_offset
    ):
        raise ValueError("Marker region is not unused PAD payload")
    marker = b"iOpenPod-Bootloader-v1\0".ljust(32, b"\0")
    marker += (
        struct.pack("<IIII", 2, 2, 0x43534C43, 0xF)
        if profile.shared
        else struct.pack("<IIII", 1, 1, profile.family, profile.hardware)
    )
    version = MINIMUM_BOOTLOADER_VERSION if profile.shared else "1.0.0"
    marker += (version.encode() + b"\0").ljust(16, b"\0")
    target[marker_offset:gap_start] = marker
    assets.mkdir(parents=True, exist_ok=True)

    def tool(name: str, *arguments: str | Path) -> bytes:
        executable = args.toolchain / f"arm-none-eabi-{name}.exe"
        if not executable.exists():
            executable = args.toolchain / f"arm-none-eabi-{name}"
        return subprocess.check_output(
            [str(executable), *map(str, arguments)], cwd=SOURCE
        )

    with tempfile.TemporaryDirectory(prefix="iopenpod-loader-") as temporary:
        work = Path(temporary)
        tool(
            "gcc",
            "-mcpu=arm926ej-s",
            "-marm",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-nostdlib",
            "-Ivendor",
            "-Wl,-T,vendor/return.lds",
            "vendor/return.S",
            "vendor/return.c",
            "-o",
            work / "return.elf",
        )
        tool("objcopy", "-O", "binary", work / "return.elf", work / "return.bin")
        trampoline = bytearray((work / "return.bin").read_bytes())
        position = trampoline.index(b"\xfe\xff\xff\xeaREPRISE-ROM\0")
        cold = bytearray(1024)
        pool = 0x284 - 0xC0 + 4
        for address in range(0xC0, 0x284, 4):
            instruction = struct.unpack_from("<I", rom, address)[0]
            offset = address - 0xC0
            if instruction & 0xFFFF0000 == 0xE59F0000:
                literal = address + 8 + (instruction & 0xFFF)
                cold[pool : pool + 4] = rom[literal : literal + 4]
                instruction = (instruction & ~0xFFF) | (pool - offset - 8)
                pool += 4
            struct.pack_into("<I", cold, offset, instruction)
        struct.pack_into(
            "<I", cold, 0x284 - 0xC0, 0xEA000000 | ((1024 - (0x284 - 0xC0) - 8) // 4)
        )
        trampoline[position : position + 1024] = cold
        (work / "return-patched.bin").write_bytes(trampoline)
        sizes: dict[str, int] = dict.fromkeys(
            (
                "expected_after_full",
                "expected_target",
                "expected_outside",
                "expected_syscfg",
                "expected_original_boot",
                "expected_original_full",
            ),
            32,
        )
        sizes["run_nonce"] = 16
        config = f"#define MODE 1\n#define ROLLBACK 0\n#define WRITE_ENABLED 1\n#define EXPECTED_JEDEC 0xbf258eu\n#define ROLLBACK_ENCRYPTED 0\n#define GAP_START {gap_start}u\n#define PACKED_BYTES {packed_size}u\n#define SECCORE_OFFSET {profile.seccore_offset}u\n#define SECCORE_BYTES {tail_bytes}u\n"
        for name, size in sizes.items():
            placeholder = hashlib.sha256(name.encode()).digest()[:size]
            config += (
                f"static const unsigned char {name}[{size}]={{"
                + ",".join(map(str, placeholder))
                + "};\n"
            )
        (work / "config.h").write_text(config)
        (work / "header.bin").write_bytes(bytes(80))
        (work / "body.bin").write_bytes(bytes(packed_size))
        assembly = '.section .rodata.assets,"a"\n.balign 4\n'
        for name, filename in (
            ("packed_header", "header.bin"),
            ("packed_body", "body.bin"),
            ("return_blob", "return-patched.bin"),
        ):
            assembly += f'.global {name}\n{name}:\n.incbin "{(work / filename).as_posix()}"\n.balign 4\n'
        assembly += (
            f".global return_blob_size\nreturn_blob_size: .word {len(trampoline)}\n"
        )
        (work / "assets.S").write_text(assembly)
        tool(
            "gcc",
            "-mcpu=arm926ej-s",
            "-marm",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-ffunction-sections",
            "-fdata-sections",
            "-Wall",
            "-Wextra",
            "-Wno-unused-function",
            "-Wno-unused-const-variable",
            "-nostdlib",
            f"-I{work}",
            "-Wl,-T,helper.lds,--gc-sections",
            "start.S",
            "helper.c",
            "vendor/sha256.c",
            work / "assets.S",
            "-o",
            work / "helper.elf",
        )
        tool("objcopy", "-O", "binary", work / "helper.elf", work / "helper.bin")
        raw = (work / "helper.bin").read_bytes()
        if args.audit_directory is not None:
            args.audit_directory.mkdir(parents=True, exist_ok=True)
            (args.audit_directory / "helper.elf").write_bytes(
                (work / "helper.elf").read_bytes()
            )
            (args.audit_directory / "symbols.txt").write_bytes(
                tool("nm", "-n", work / "helper.elf")
            )
        source = args.mkdfu_source.read_text()
        section = source[
            source.index("unsigned char s5l8702pwnage") : source.index(
                "static uint32_t get_uint32le"
            )
        ]
        certificate = (
            b"".join(
                ast.literal_eval("b" + item) for item in re.findall(r'"[^"]*"', section)
            )
            + b"\0"
        )
        image = bytearray(0x30C + ((len(raw) + 15) & ~15))
        if len(image) > 0x20000:
            raise ValueError("Writer exceeds DFU RAM")
        image[:8] = b"87021.0\x03"
        struct.pack_into("<III", image, 16, 0x300, 0xFFFFF850, 0x2BA)
        image[0x40:0x50] = bytes.fromhex("c2545131dcc084a47fd14508e8ffe81d")
        image[0x50 : 0x50 + len(certificate)] = certificate
        struct.pack_into("<I", image, 0x50 + 0x2BA - 4, 0x2200030C)
        image[0x30C : 0x30C + len(raw)] = raw
        symbols = {
            name: int(address, 16) - 0x22000000
            for address, name in re.findall(
                r"^([0-9a-f]+) \w (\w+)\r?$",
                tool("nm", "-n", work / "helper.elf").decode(),
                re.M,
            )
        }
        sizes.update(packed_header=80, packed_body=packed_size)
        slots = {}
        for name, size in sizes.items():
            offset = symbols[name]
            if not 0x30C <= offset < offset + size <= len(image):
                raise ValueError(f"Invalid template slot: {name}")
            image[offset : offset + size] = bytes(size)
            slots[name] = {"offset": offset, "size": size}
        patch = delta(stock, bytes(target))
        if not profile.shared:
            (assets / "stock.delta").write_bytes(patch)
        (assets / "writer.dfu").write_bytes(image)
        metadata: dict[str, object] = {
            "schema": 1,
            "identifier": "iOpenPod-Bootloader-v1",
            "version": version,
            "family": profile.family,
            "hardware": profile.hardware,
            "stock_sha256": profile.stock_sha256,
            "unmarked_sha256": profile.unmarked_sha256,
            "target_sha256": digest(target),
            "bootrom_sha256": ROM,
            "marker_offset": marker_offset,
            "marker_hex": marker.hex(),
            "gap_start": gap_start,
            "seccore_offset": profile.seccore_offset,
            "max_body_bytes": profile.max_body_bytes,
            "slots": slots,
            "files": {"stock.delta": digest(patch), "writer.dfu": digest(image)},
        }
        if profile.shared:
            # Deltas are migration encodings, not separate executable targets.
            # Every qualified input must reconstruct exactly the same body.
            from iOpenPod.app.firmware.bootloader_bundle import BootloaderBundle

            inputs = {38: stock}
            for source_arg in args.source:
                family_text, separator, filename = source_arg.partition("=")
                family = int(family_text)
                if not separator or family not in (24, 33, 35) or family in inputs:
                    raise ValueError(
                        "Specify each additional stock source exactly once"
                    )
                inputs[family] = checked(Path(filename), PROFILES[family].stock_sha256)
            if set(inputs) != {24, 33, 35, 38}:
                raise ValueError(
                    "Shared bundle requires stock inputs for all four Classics"
                )
            sources: list[dict[str, int | str]] = []
            shared_files = {"writer.dfu": digest(image)}
            assert shared_v2 is not None
            encoded_v2 = delta(shared_v2, bytes(target))
            (assets / "shared-v2.delta").write_bytes(encoded_v2)
            shared_files["shared-v2.delta"] = digest(encoded_v2)
            for family, original in sorted(inputs.items()):
                sources.append(
                    {
                        "family": family,
                        "sha256": digest(shared_v2),
                        "delta": "shared-v2.delta",
                    }
                )
                previous = BootloaderBundle(family).apply(original)
                variants = {"stock": original, "v1": previous}
                if family == 33:
                    unmarked = bytearray(previous)
                    at = PROFILES[33].marker_offset
                    unmarked[at : at + 64] = b"\xff" * 64
                    if digest(unmarked) != PROFILES[33].unmarked_sha256:
                        raise ValueError("Unmarked legacy source differs")
                    variants["v5b"] = bytes(unmarked)
                for label, source_body in variants.items():
                    filename = f"{family}-{label}.delta"
                    encoded = delta(source_body, bytes(target))
                    (assets / filename).write_bytes(encoded)
                    shared_files[filename] = digest(encoded)
                    sources.append(
                        {
                            "family": family,
                            "sha256": digest(source_body),
                            "delta": filename,
                        }
                    )
            metadata.update(
                schema=2,
                image_target=0x43534C43,
                hardware_mask=0xF,
                sources=sources,
                files=shared_files,
            )
            if args.output_dir:
                (assets / "loader-body.bin").write_bytes(target)
        (assets / "manifest.json").write_bytes(
            (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
        )
        print(
            json.dumps(
                {
                    "target_sha256": digest(target),
                    "writer_bytes": len(image),
                    "delta_bytes": len(patch),
                }
            )
        )


if __name__ == "__main__":
    main()
