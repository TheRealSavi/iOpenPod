"""Build the common Classic 2.0.5 OS and selected native mods offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
from dataclasses import asdict
from pathlib import Path

from iOpenPod.app.firmware.bootloader_identity import MARKER_OFFSETS
from iOpenPod.app.firmware.classic_layout import (
    EXPANDED_LAYOUT,
    MOD_BASE,
    MOD_MEMORY_BYTES,
)

from .classic_appearance import (
    AUTO_LIGHT_END_HOUR,
    AUTO_LIGHT_START_HOUR,
    artwork_patches,
    emit_appearance_header,
    settings_resources,
)
from .classic_deltas import encode_xor_delta
from .classic_menu import (
    MOD_PREVIEW_IMAGE,
    emit_menu_header,
    included_mods,
    menu_resources,
    mod_records,
)
from .classic_mono import ICON_PATH as MONO_ICON_PATH
from .classic_mono import mono_resources
from .classic_patches import apply_patches, native_patches
from .classic_preview_artwork import preview_artwork_resources
from .classic_resources import blocks, pack_blocks, put, u32
from .classic_target import HEADER_BYTES, INPUT_BYTES, INPUT_SHA
from .classic_title_clock import title_clock_resources

VIEW_OFFSET, VIEW_SIZE = 0x839DF8, 892
PAYLOAD_BASE = MOD_BASE
OSOS_SLOT_BYTES = EXPANDED_LAYOUT.os_slot_bytes


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def about_resources(raw: bytes, version: str) -> dict[str, bytes]:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError(
            "Use a three-component Mod Platform Version with optional prerelease"
        )
    if len(version.encode("ascii")) >= 32:
        raise ValueError("Mod Platform Version exceeds its independent 32-byte field")
    original = blocks(raw[VIEW_OFFSET : VIEW_OFFSET + VIEW_SIZE])
    if len(original) != 6:
        raise ValueError("Expected six original About text fields")
    updated: list[tuple[int, bytes]] = []
    for index, (kind, body) in enumerate(original):
        if (
            kind != 0x74657874
            or len(body) != 140
            or u32(body, 0x30) != 0x0DAD0B2B + index
            or u32(body, 0x64) != 1672 + index
            or u32(body, 0xC) != (153, 171, 189)[index % 3]
        ):
            raise ValueError("Native About template identity changed")
        changed = bytearray(body)
        put(changed, 0xC, u32(body, 0xC) - 9)
        updated.append((kind, bytes(changed)))
    for index, source_id, child_id in (
        (2, 0x0CF00002, 0x0CF00004),
        (5, 0x0CF00003, 0x0CF00005),
    ):
        kind, body = original[index]
        changed = bytearray(body)
        for offset, value in ((0xC, 198), (0x30, child_id), (0x64, source_id)):
            put(changed, offset, value)
        updated.append((kind, bytes(changed)))
    return {
        "iop_mod_label": b"Mod Version\0",
        "iop_label_source": pack_blocks(
            [(0x534F5243, struct.pack("<III", 0x80, 0x0CF00000, 1))]
        ),
        "iop_version_source": pack_blocks(
            [(0x534F5243, struct.pack("<III", 0x80, 0x0CF00001, 1))]
        ),
        "iop_about_view": pack_blocks(updated),
    }


def build(
    source_os: Path,
    output: Path,
    compiler: Path,
    version: str,
    *,
    homebrew_eapps: bool = False,
    dark_mode: bool = False,
    now_playing_artwork: bool = False,
    bootloader_report: bool = False,
    artwork_diagnostics: bool = False,
    long_audio: bool = False,
    photo_zoom: bool = False,
    title_bar_clock: bool = False,
    mono_audio: bool = False,
    mod_sources: tuple[Path, ...] = (),
) -> bytes:
    if artwork_diagnostics and not (now_playing_artwork and bootloader_report):
        raise ValueError(
            "Artwork diagnostics require preview artwork and bootloader reporting"
        )
    raw = source_os.read_bytes()
    if len(raw) != INPUT_BYTES or sha(raw) != INPUT_SHA:
        raise ValueError("Unexpected original Classic 2.0.5 firmware")
    resources = about_resources(raw, version)
    menu = menu_resources(
        raw,
        included_mods(
            homebrew_eapps=homebrew_eapps,
            dark_mode=dark_mode,
            now_playing_artwork=now_playing_artwork,
            bootloader_report=bootloader_report,
            long_audio=long_audio,
            photo_zoom=photo_zoom,
            title_bar_clock=title_bar_clock,
            mono_audio=mono_audio,
        ),
    )
    if dark_mode:
        settings_resources(menu)
    if now_playing_artwork:
        preview_artwork_resources(menu)
    output.mkdir(parents=True, exist_ok=False)
    if mono_audio:
        (output / "mono_resources.h").write_text(mono_resources(menu), encoding="ascii")
    if title_bar_clock:
        (output / "title_clock_layouts.h").write_text(
            title_clock_resources(menu), encoding="ascii"
        )
    (output / "menu_resources.h").write_text(
        emit_menu_header(menu, raw), encoding="ascii"
    )
    header = [
        f'#define IOP_PLATFORM_VERSION "{version}"',
        f"#define IOP_VERSION_BYTES {len(version) + 1}",
    ]
    for name, data in resources.items():
        header.append(
            f"static const unsigned char {name}[] __attribute__((aligned(4))) = {{"
        )
        header.extend(
            "    " + ",".join(f"0x{x:02x}" for x in data[p : p + 16]) + ","
            for p in range(0, len(data), 16)
        )
        header.append("};")
    (output / "about_resources.h").write_text(
        "\n".join(header) + "\n", encoding="ascii"
    )
    source = Path(__file__).with_name("classic_about")
    appearance_sources = (
        (source / "appearance.c", source / "appearance.S") if dark_mode else ()
    )
    artwork_sources = (
        (source / "artwork.c", source / "artwork.S")
        + ((source / "artwork_trace.c",) if artwork_diagnostics else ())
        if now_playing_artwork
        else ()
    )
    settings_sources = (source / "preference.c",) if dark_mode or mono_audio else ()
    mono_sources = (
        (source / "mono_audio.c", source / "mono_mix.S") if mono_audio else ()
    )
    audio_sources = (source / "long_audio.c",) if long_audio else ()
    photo_sources = (source / "photo_zoom.c",) if photo_zoom else ()
    clock_sources = (source / "title_clock.c",) if title_bar_clock else ()
    report_sources = (
        (
            source / "boot_report.c",
            source.parent.parent / "bootloader/native/vendor/sha256.c",
        )
        if bootloader_report
        else ()
    )
    if bootloader_report:
        (output / "boot_report_resources.h").write_text(
            "static const unsigned iop_marker_offsets[] = {"
            + ",".join(str(offset) for offset in MARKER_OFFSETS)
            + "};\n",
            encoding="ascii",
        )
    if dark_mode:
        (output / "appearance_resources.h").write_text(
            emit_appearance_header(raw), encoding="ascii"
        )
    prefix = str(compiler.resolve())[:-7]
    command = [
        str(compiler),
        "-mcpu=arm926ej-s",
        "-marm",
        "-Os",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-fno-unwind-tables",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-nostdlib",
        *(["-DIOP_BOOT_REPORT=1"] if bootloader_report else []),
        *(["-DIOP_ARTWORK_DIAGNOSTICS=1"] if artwork_diagnostics else []),
        *(["-DIOP_DARK_MODE=1"] if dark_mode else []),
        "-I",
        str(output),
        f"-Wl,-T,{source / 'payload.lds'},-Map,{output / 'payload.map'}",
        f"-Wl,--defsym=IOP_MOD_BASE={MOD_BASE},--defsym=IOP_MOD_MEMORY_BYTES={MOD_MEMORY_BYTES}",
        str(source / "entry.S"),
        str(source / "payload.c"),
        *(str(path) for path in settings_sources + mono_sources + appearance_sources),
        *(str(path) for path in artwork_sources),
        *(str(path) for path in report_sources),
        *(str(path) for path in audio_sources),
        *(str(path) for path in photo_sources),
        *(str(path) for path in clock_sources),
        *(str(path.resolve()) for path in mod_sources),
        "-o",
        str(output / "payload.elf"),
    ]
    subprocess.run(command, check=True)
    subprocess.run(
        [
            prefix + "objcopy.exe",
            "-O",
            "binary",
            str(output / "payload.elf"),
            str(output / "payload.bin"),
        ],
        check=True,
    )
    symbols: dict[str, int] = {}
    for line in subprocess.check_output(
        [prefix + "nm.exe", "-n", str(output / "payload.elf")], text=True
    ).splitlines():
        parts = line.split()
        if len(parts) == 3:
            symbols[parts[2]] = int(parts[0], 16)
    payload = (output / "payload.bin").read_bytes()
    if (
        symbols["iop_copy_entry"] != PAYLOAD_BASE
        or len(payload) % 4
        or symbols["__payload_copy_bytes"] != len(payload)
        or INPUT_BYTES + len(payload) > OSOS_SLOT_BYTES
        or not PAYLOAD_BASE
        < symbols["__payload_limit"]
        <= PAYLOAD_BASE + MOD_MEMORY_BYTES
    ):
        raise ValueError("Payload placement exceeds its qualified memory/disk bounds")
    patched, patches = apply_patches(
        raw,
        native_patches(
            symbols,
            homebrew_eapps=homebrew_eapps,
            dark_mode=dark_mode,
            bootloader_report=bootloader_report,
            long_audio=long_audio,
            photo_zoom=photo_zoom,
            title_bar_clock=title_bar_clock,
            mono_audio=mono_audio,
            now_playing_artwork=now_playing_artwork,
            artwork_diagnostics=artwork_diagnostics,
        ),
    )
    candidate = bytearray(patched)
    candidate.extend(payload)
    for offset in (0xC, 0x10, 0x14):
        if u32(raw, offset) != INPUT_BYTES - HEADER_BYTES:
            raise ValueError("Unexpected prepared IMG1 header")
        put(candidate, offset, len(candidate) - HEADER_BYTES)
    target = output / "osos-about-unsigned.bin"
    target.write_bytes(candidate)
    (output / "payload.asm.txt").write_bytes(
        subprocess.check_output(
            [prefix + "objdump.exe", "-d", str(output / "payload.elf")]
        )
    )
    appearance_artwork = artwork_patches(raw) if dark_mode else ()
    receipt = {
        "input_sha256": INPUT_SHA,
        "output_sha256": sha(bytes(candidate)),
        "output_bytes": len(candidate),
        "status": "offline-unsigned-not-installable",
        "platform_version": version,
        "mods": mod_records(
            homebrew_eapps=homebrew_eapps,
            dark_mode=dark_mode,
            now_playing_artwork=now_playing_artwork,
            bootloader_report=bootloader_report,
            long_audio=long_audio,
            photo_zoom=photo_zoom,
            title_bar_clock=title_bar_clock,
            mono_audio=mono_audio,
        ),
        "appearance": {
            "enabled": dark_mode,
            "default": "light",
            "auto_light_hours": [AUTO_LIGHT_START_HOUR, AUTO_LIGHT_END_HOUR]
            if dark_mode
            else None,
            "bitmap_patches": len(appearance_artwork),
            "bitmap_delta_bytes": sum(len(p.original) for p in appearance_artwork),
            "bitmap_encoded_bytes": sum(
                len(encode_xor_delta(p.original, p.changed)) for p in appearance_artwork
            ),
        },
        "apple_version": "2.0.5",
        "payload_bytes": len(payload),
        "payload_sha256": sha(payload),
        "mod_memory_bytes": symbols["__payload_limit"] - PAYLOAD_BASE,
        "mod_memory_capacity": MOD_MEMORY_BYTES,
        "os_slot_bytes": OSOS_SLOT_BYTES,
        "additional_sources": [
            {"name": path.name, "sha256": sha(path.read_bytes())}
            for path in mod_sources
        ],
        "artwork_diagnostics": artwork_diagnostics,
        "symbols": symbols,
        "patches": [asdict(patch) for patch in patches],
        "compiler_version": subprocess.check_output(
            [str(compiler), "--version"], text=True
        ).splitlines()[0],
        "source_hashes": {
            p.name: sha(p.read_bytes())
            for p in [
                source / "entry.S",
                source / "payload.c",
                source / "payload.lds",
                *settings_sources,
                *([source / "preference.h"] if settings_sources else []),
                *mono_sources,
                *(
                    [Path(__file__).with_name("classic_mono.py"), MONO_ICON_PATH]
                    if mono_audio
                    else []
                ),
                *appearance_sources,
                *artwork_sources,
                *report_sources,
                *audio_sources,
                *photo_sources,
                *clock_sources,
                *(
                    [Path(__file__).with_name("classic_title_clock.py")]
                    if title_bar_clock
                    else []
                ),
                *(
                    [source.parent.parent / "bootloader/native/vendor/sha256.h"]
                    if bootloader_report
                    else []
                ),
                Path(__file__),
                Path(__file__).with_name("classic_menu.py"),
                MOD_PREVIEW_IMAGE,
                Path(__file__).with_name("classic_settings.py"),
                Path(__file__).with_name("classic_patches.py"),
                Path(__file__).with_name("classic_target.py"),
                Path(__file__).with_name("classic_preview_artwork.py"),
                Path(__file__).with_name("classic_resources.py"),
                Path(__file__).with_name("classic_appearance.py"),
                Path(__file__).with_name("classic_deltas.py"),
                Path(__file__).with_name("classic_bitmaps.py"),
            ]
        },
        "resources": {
            name: {"bytes": len(data), "sha256": sha(data)}
            for name, data in resources.items()
        },
        "menu_resources": [
            {"kind": kind, "id": resource_id, "bytes": len(data), "sha256": sha(data)}
            for (kind, resource_id), data in menu.added.items()
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(target),
                "bytes": len(candidate),
                "payload_bytes": len(payload),
                "version": version,
                "status": receipt["status"],
            },
            indent=2,
        )
    )

    return bytes(candidate)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--osos", type=Path, required=True)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--mod-source", type=Path, action="append", default=[])
    parser.add_argument(
        "--artwork-diagnostics",
        action="store_true",
        help="Retain bounded preview state for normal-USB debugging (requires artwork and boot report)",
    )
    parser.add_argument(
        "--bootloader-report",
        action="store_true",
        help="Measure NOR at boot and report loader identity over normal USB",
    )
    parser.add_argument(
        "--dark-mode",
        action="store_true",
        help="Include persistent Settings Light/Dark/Auto appearance",
    )
    parser.add_argument(
        "--now-playing-artwork",
        action="store_true",
        help="Show album artwork in the main-menu Now Playing preview",
    )
    parser.add_argument(
        "--homebrew-eapps",
        action="store_true",
        help="Allow unsigned game manifests; executable Verify/DRM stays unchanged",
    )
    parser.add_argument(
        "--photo-zoom", action="store_true", help="Zoom and pan full-size photos"
    )
    parser.add_argument(
        "--long-audio",
        action="store_true",
        help="Fix long MP4 audio playback and accelerate validated audio seeks",
    )
    parser.add_argument(
        "--title-bar-clock",
        action="store_true",
        help="Keep the title and local time visible on full-width bars",
    )
    parser.add_argument(
        "--mono-audio",
        action="store_true",
        help="Add the system-wide Mono Audio setting",
    )
    args = parser.parse_args()
    from iOpenPod.app.firmware.classic_shared import (
        compose_shared_firmware,
        wrap_shared_os,
    )

    prepared = build(
        args.osos,
        args.out.resolve(),
        args.compiler.resolve(),
        args.version,
        homebrew_eapps=args.homebrew_eapps,
        dark_mode=args.dark_mode,
        artwork_diagnostics=args.artwork_diagnostics,
        now_playing_artwork=args.now_playing_artwork,
        bootloader_report=args.bootloader_report,
        long_audio=args.long_audio,
        photo_zoom=args.photo_zoom,
        title_bar_clock=args.title_bar_clock,
        mono_audio=args.mono_audio,
        mod_sources=tuple(args.mod_source),
    )
    common_os = wrap_shared_os(prepared[HEADER_BYTES:])
    firmware = compose_shared_firmware(args.firmware.read_bytes(), common_os)
    (args.out / "osos-common.im3").write_bytes(common_os)
    (args.out / "firmware-common.bin").write_bytes(firmware)
    (args.out / "shared-image.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "apple_version": "2.0.5",
                "platform_version": args.version,
                "artwork_diagnostics": args.artwork_diagnostics,
                "mods": mod_records(
                    homebrew_eapps=args.homebrew_eapps,
                    dark_mode=args.dark_mode,
                    now_playing_artwork=args.now_playing_artwork,
                    bootloader_report=args.bootloader_report,
                    long_audio=args.long_audio,
                    photo_zoom=args.photo_zoom,
                    title_bar_clock=args.title_bar_clock,
                    mono_audio=args.mono_audio,
                ),
                "families": [24, 33, 35, 38],
                "device_crypto_required": False,
                "osos_sha256": sha(common_os),
                "firmware_sha256": sha(firmware),
                "firmware_bytes": len(firmware),
                "status": "offline-built-not-physically-tested",
            },
            indent=2,
        )
        + "\n"
    )
