"""Build an exact Classic unsigned-OS loader extension offline, preserving originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
from dataclasses import asdict
from pathlib import Path

from scripts.bootloader.profiles import PROFILES, SHARED_PROFILE

SOURCE = Path(__file__).with_name("loader")


def sha(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def branch(at: int, target: int) -> bytes:
    delta = (target & ~1) - at - 4
    if delta & 1 or not -(1 << 22) <= delta < (1 << 22):
        raise ValueError("Thumb BL out of range")
    return struct.pack(
        "<HH", 0xF000 | ((delta >> 12) & 0x7FF), 0xF800 | ((delta >> 1) & 0x7FF)
    )


def extend_debug(raw: bytes, code: bytes, rva: int) -> bytearray:
    image = bytearray(raw)
    pe = struct.unpack_from("<I", raw, 0x3C)[0]
    opt = pe + 24
    table = opt + struct.unpack_from("<H", raw, pe + 20)[0]
    count = struct.unpack_from("<H", raw, pe + 6)[0]
    section = table + (count - 1) * 40
    if (
        raw[section : section + 8] != b".debug\0\0"
        or struct.unpack_from("<I", raw, section + 12)[0] != rva
    ):
        raise ValueError("Unexpected final debug section")
    rawsize = max(128, (len(code) + 31) & ~31)
    image[rva:] = code + bytes(rawsize - len(code))
    image[section : section + 8] = b".mod\0\0\0\0"
    struct.pack_into("<I", image, section + 8, rawsize)
    struct.pack_into("<I", image, section + 16, rawsize)
    struct.pack_into("<I", image, section + 36, 0x60000020)
    struct.pack_into("<I", image, opt + 56, rva + rawsize)
    image[opt + 96 + 6 * 8 : opt + 96 + 7 * 8] = bytes(8)
    for field, flag in ((4, 0x20), (8, 0x40), (12, 0x80)):
        size = sum(
            struct.unpack_from("<I", image, table + i * 40 + 16)[0]
            for i in range(count)
            if struct.unpack_from("<I", image, table + i * 40 + 36)[0] & flag
        )
        struct.pack_into("<I", image, opt + field, size)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--family", type=int, choices=PROFILES)
    selection.add_argument("--shared", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    for name in ("stock", "modules", "toolchain", "go", "wind3x"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    profile = SHARED_PROFILE if args.shared else PROFILES[args.family or 33]
    if sha(args.stock.read_bytes()) != profile.stock_sha256:
        raise ValueError("Unqualified stock loader for selected family")
    rom = (args.modules / "ROM-773641a1-cc51-41b7-b121-943bd7c5fc3f.pe32").read_bytes()
    bds = (args.modules / "Bds-2ed6d875-3da4-462c-b201-7c557027a5ba.pe32").read_bytes()
    if sha(rom) != profile.rom_sha256 or sha(bds) != profile.bds_sha256:
        raise ValueError("Unqualified native module for selected family")

    def tool(name: str, *arguments: str | Path) -> str:
        executable = args.toolchain / f"arm-none-eabi-{name}.exe"
        if not executable.exists():
            executable = args.toolchain / f"arm-none-eabi-{name}"
        return subprocess.check_output(
            [str(executable), *map(str, arguments)], text=True
        )

    out = args.out.resolve()
    out.mkdir(exist_ok=False)
    (out / "source").mkdir()
    for file in SOURCE.iterdir():
        shutil.copyfile(file, out / "source" / file.name)
    shutil.copyfile(__file__, out / "source" / Path(__file__).name)
    shutil.copyfile(Path(__file__).with_name("profiles.py"), out / "source/profiles.py")
    (out / "profile.json").write_text(json.dumps(asdict(profile), indent=2) + "\n")
    reports: dict[str, dict[str, int]] = {}
    units = [
        ("gate", ("gate.c", "native.S", "crc32.S"), ".mod"),
        ("bds_bridge", ("bds_bridge.S",), ".bds_bridge"),
    ]
    if profile.shared:
        units.append(("software_version", ("software_version.c",), ".mod"))
    for name, inputs, section in units:
        flags = [
            "-mcpu=arm926ej-s",
            "-mthumb",
            "-Os",
            "-ffreestanding",
            "-fno-builtin",
            "-fno-stack-protector",
            "-fno-unwind-tables",
            "-fno-asynchronous-unwind-tables",
            "-fno-jump-tables",
            "-nostdlib",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-DUPDATER_FAMILY={profile.family}",
            f"-DMAX_BODY={profile.max_body_bytes}u",
        ]
        if profile.shared:
            flags.append("-DSHARED_CLASSIC=1")
            if name == "bds_bridge":
                displacement = (
                    reports["gate"]["shared_context"]
                    - reports["gate"]["unsigned_header_gate"]
                )
                if not 0 <= displacement <= 255:
                    raise ValueError("ROM context helper exceeds the Bds bridge range")
                flags.append(f"-DCONTEXT_OFFSET={displacement}")
        tool(
            "gcc",
            *flags,
            "-Wl,-T," + str(SOURCE / (name + ".lds")),
            *[SOURCE / f for f in inputs],
            "-o",
            out / (name + ".elf"),
        )
        tool(
            "objcopy",
            "-O",
            "binary",
            "--only-section=" + section,
            out / (name + ".elf"),
            out / (name + ".bin"),
        )
        symbols = tool("nm", "-n", out / (name + ".elf"))
        (out / (name + ".symbols.txt")).write_text(symbols)
        (out / (name + ".asm.txt")).write_text(
            tool("objdump", "-d", out / (name + ".elf"))
        )
        reports[name] = {
            row.split()[2]: int(row.split()[0], 16)
            for row in symbols.splitlines()
            if len(row.split()) == 3
        }
    if (
        rom[0x6B2:0x6B6] != bytes.fromhex("02229847")
        or bds[0x3D0:0x3DA] != bytes.fromhex("0f980899836801229847")
        or bds[0x3DE:0x3E4] != bytes.fromhex("05991598401a")
        or bds[0x49C:0x4A2] != bytes.fromhex("099a08999847")
    ):
        raise ValueError("Native call site differs")
    rp = extend_debug(rom, (out / "gate.bin").read_bytes(), 0x1560)
    struct.pack_into("<I", rp, 0x13D4, reports["gate"]["unsigned_header_gate"] | 1)
    rp[0x6B2:0x6B6] = branch(0x6B2, reports["gate"]["body_dispatch"])
    bp = extend_debug(bds, (out / "bds_bridge.bin").read_bytes(), 0x1480)
    bp[0x3D0:0x3DA] = (
        branch(0x3D0, reports["bds_bridge"]["header_bridge"])
        + bytes.fromhex("c046") * 3
    )
    bp[0x3DE:0x3E4] = branch(
        0x3DE, reports["bds_bridge"]["allocation_bridge"]
    ) + bytes.fromhex("c046")
    bp[0x49C:0x4A2] = branch(
        0x49C, reports["bds_bridge"]["body_bridge"]
    ) + bytes.fromhex("c046")
    if profile.shared:
        if bds[0x4C6:0x4CA] != bytes.fromhex("67491798"):
            raise ValueError("Shared SysInfo handoff call site differs")
        bp[0x4C6:0x4CA] = branch(0x4C6, reports["bds_bridge"]["context_bridge"])
        version = (
            args.modules / "SoftwareVersion-0e2bee84-a47c-4d0c-8271-97f42cdbcc76.pe32"
        ).read_bytes()
        if (
            sha(version)
            != "ef780c54db62b6218ed48b4416a0d12f58ad3d3fcda280c612d96c177530a619"
        ):
            raise ValueError("Unqualified SoftwareVersion module")
        vp = extend_debug(version, (out / "software_version.bin").read_bytes(), 0x560)
        if struct.unpack_from("<I", vp, 0x504)[0] != 0x221:
            raise ValueError("SoftwareVersion protocol pointer differs")
        struct.pack_into(
            "<I", vp, 0x504, reports["software_version"]["shared_version_check"] | 1
        )
        (out / "SoftwareVersion-shared.pe32").write_bytes(vp)
        # The expanded Bds compresses 16 bytes beyond its old FFS span. Its
        # immediately following, relocatable module supplies those bytes by
        # discarding only its debugger record. Every later file stays fixed.
        security = (
            args.modules
            / "ImageManagerSecurity-a3f1a310-0ad9-42e3-8918-3c81d2e3008c.pe32"
        ).read_bytes()
        if (
            sha(security)
            != "9ca33832e7fc26f08528d31f4be5559fed837464bee316b55c9f6435b9e63297"
        ):
            raise ValueError("Unqualified ImageManagerSecurity module")
        pe = struct.unpack_from("<I", security, 0x3C)[0]
        opt = pe + 24
        if struct.unpack_from("<I", security, opt + 28)[0] != 0:
            raise ValueError("ImageManagerSecurity is not relocatable")
        debug = struct.unpack_from("<I", security, opt + 96 + 6 * 8)[0]
        stripped = bytearray(security)
        stripped[debug:] = bytes(len(security) - debug)
        stripped[opt + 96 + 6 * 8 : opt + 96 + 7 * 8] = bytes(8)
        (out / "ImageManagerSecurity-shared.pe32").write_bytes(stripped)
    (out / "ROM-unsigned.pe32").write_bytes(rp)
    (out / "Bds-unsigned.pe32").write_bytes(bp)
    module = out / "repack-module"
    module.mkdir()
    (module / "go.mod").write_text(
        "module iopenpod-loader-repack\n\ngo 1.23.0\n\n"
        "require github.com/freemyipod/wInd3x v0.0.0\n\n"
        "replace github.com/freemyipod/wInd3x => "
        + json.dumps(args.wind3x.resolve().as_posix())
        + "\n"
    )
    subprocess.run(
        [
            str(args.go),
            "run",
            "-mod=mod",
            str(SOURCE / "repack.go"),
            str(args.stock.resolve()),
            str(out),
            str(out / "profile.json"),
        ],
        cwd=module,
        check=True,
    )
    body = (out / "loader-body.bin").read_bytes()
    if sha(body) != profile.unmarked_sha256:
        raise ValueError("Rebuilt loader differs from the reviewed output")
    fs = (out / "extracted-81b6cb09-0d19-4b56-bc42-df9c35fbe21f.pe32").read_bytes()
    if sha(fs) != profile.fs_sha256:
        raise ValueError("FirmwareFS changed during repacking")
    header = bytearray(0x800)
    header[:8] = b"87021.0\x02"
    struct.pack_into("<I", header, 12, len(body))
    unsigned = header + body
    (out / "loader-unsigned.im3").write_bytes(unsigned)
    report = {
        "status": "offline-candidate-not-installed",
        "family": profile.family,
        "max_body_bytes": profile.max_body_bytes,
        "symbols": reports,
        "loader_unsigned_sha256": sha(unsigned),
        "loader_body_sha256": sha(body),
        "rom_sha256": sha(rp),
        "bds_sha256": sha(bp),
        "source_hashes": {
            p.name: sha(p.read_bytes()) for p in (out / "source").iterdir()
        },
    }
    (out / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
