"""Plan and validate native Classic hooks before modifying any image bytes.

The recipe below is specific to the hash-qualified 2.0.5 input. The patcher
validates complete spans and original bytes, rejects overlap, and returns a new
image plus typed provenance. It performs no file I/O or device operations.
"""

import struct
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from .classic_target import (
    DRAM_BASE,
    DRAM_END,
    DRAM_FILE,
    HEADER_BYTES,
    INPUT_BYTES,
    IRAM_BASE,
    IRAM_END,
)


@dataclass(frozen=True)
class NativePatch:
    address: int
    before: bytes
    after: bytes
    purpose: str


@dataclass(frozen=True)
class AppliedPatch:
    address: int
    file_offset: int
    before: str
    after: str
    purpose: str


def runtime_offset(address: int, size: int) -> int:
    """Map a complete nonempty span, rejecting gaps and region crossings."""
    for start, end, offset in (
        (IRAM_BASE, IRAM_END, HEADER_BYTES),
        (DRAM_BASE, DRAM_END, DRAM_FILE),
    ):
        if size > 0 and start <= address < end and size <= end - address:
            return offset + address - start
    raise ValueError(
        f"Patch span lies outside initialized native regions: {address:#x}"
    )


def apply_patches(
    original: bytes, patches: Iterable[NativePatch]
) -> tuple[bytes, tuple[AppliedPatch, ...]]:
    """Validate the entire plan against pristine bytes before applying it.

    Overlap is forbidden even when the second patch expects the first patch's
    output, or two patches happen to write identical bytes. A shared hook must
    have one explicit owner.
    """
    planned = tuple(patches)
    spans: list[tuple[int, int]] = []
    records: list[AppliedPatch] = []
    for patch in planned:
        if not patch.before or len(patch.before) != len(patch.after):
            raise ValueError(f"Patch must preserve a nonempty span: {patch.purpose}")
        offset = runtime_offset(patch.address, len(patch.before))
        end = offset + len(patch.before)
        if end > len(original):
            raise ValueError(f"Patch exceeds input image: {patch.purpose}")
        if any(
            offset < previous_end and previous_start < end
            for previous_start, previous_end in spans
        ):
            raise ValueError(f"Overlapping native patch: {patch.purpose}")
        if original[offset:end] != patch.before:
            raise ValueError(f"Unexpected instructions/data at {patch.address:#x}")
        spans.append((offset, end))
        records.append(
            AppliedPatch(
                patch.address,
                offset,
                patch.before.hex(),
                patch.after.hex(),
                patch.purpose,
            )
        )
    result = bytearray(original)
    for patch, record in zip(planned, records, strict=True):
        result[record.file_offset : record.file_offset + len(patch.after)] = patch.after
    return bytes(result), tuple(records)


def arm_immediate(value: int) -> int:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("ARM immediate must be an unsigned 32-bit value")
    for rotation in range(16):
        shift = rotation * 2
        candidate = (
            (value << shift) | (value >> (32 - shift if shift else 32))
        ) & 0xFFFFFFFF
        if candidate <= 0xFF:
            return rotation << 8 | candidate
    raise ValueError(f"Cannot encode ARM immediate {value:#x}")


def arm_call(address: int, target: int) -> bytes:
    delta = target - address - 8
    if (
        not 0 <= address <= 0xFFFFFFFF
        or not 0 <= target <= 0xFFFFFFFF
        or address % 4
        or target % 4
        or not -(1 << 25) <= delta < 1 << 25
    ):
        raise ValueError("Branch exceeds native ARM range or is not word aligned")
    return struct.pack("<I", 0xEB000000 | ((delta >> 2) & 0xFFFFFF))


def native_patches(
    symbols: Mapping[str, int],
    *,
    homebrew_eapps: bool,
    dark_mode: bool,
    bootloader_report: bool = False,
    now_playing_artwork: bool = False,
    artwork_diagnostics: bool = False,
    long_audio: bool = False,
    photo_zoom: bool = False,
    title_bar_clock: bool = False,
) -> Iterator[NativePatch]:
    """The explicit, ordered hook recipe for the selected built-in mods."""
    # r4 retains the original DRAM source. Reach the appended PIC bootstrap.
    delta = INPUT_BYTES - DRAM_FILE
    jump = struct.pack(
        "<III",
        0xE2840000 | arm_immediate(delta & 0xFF0000),
        0xE2800000 | arm_immediate(delta & 0xFF00),
        0xE280F000 | arm_immediate(delta & 0xFF),
    )
    yield NativePatch(
        0x2200479C,
        bytes.fromhex("04009fe57040bde810ff2fe1"),
        jump,
        "copy appended payload before native BSS clear",
    )
    for address in (0x0804B478, 0x0807C048):
        yield NativePatch(
            address,
            struct.pack("<I", 0x08B3B1B0),
            struct.pack("<I", symbols["__payload_limit"]),
            "reserve payload above native BSS and downward-growing stacks",
        )
    yield NativePatch(
        0x081C7EA8,
        bytes.fromhex("1428fdeb"),
        arm_call(0x081C7EA8, symbols["iop_resource_init"]),
        "install independent version, extended native About and Extras Mods list",
    )
    if bootloader_report:
        yield NativePatch(
            0x081477F4,
            bytes.fromhex("3d45ffeb"),
            arm_call(0x081477F4, symbols["iop_boot_report_xml"]),
            "publish boot-time NOR measurement in live SysInfo before root close",
        )
    if title_bar_clock:
        address = 0x08175D30
        yield NativePatch(
            address,
            arm_call(address, 0x082641DC),
            arm_call(address, symbols["iop_title_clock_left"]),
            "apply native left text alignment to clock-enabled titles",
        )
        address = 0x08178374
        yield NativePatch(
            address,
            arm_call(address, 0x0817A900),
            arm_call(address, symbols["iop_title_clock_layout"]),
            "select the full-width clock layout using Time in Title",
        )
        yield NativePatch(
            0x08993188,
            struct.pack("<I", 0x0819CE88),
            struct.pack("<I", symbols["iop_title_clock_property"]),
            "keep the native title binding while its separate clock is visible",
        )
    if photo_zoom:
        yield NativePatch(
            0x081C23BC,
            struct.pack("<I", 0xE3E02000),
            struct.pack("<I", 0xE3A02005),
            "cache F1067 beside the LCD rendition in the full-size photo browser",
        )
        # Both TPhotosBrowseCntlr vtables share the physical-event entry.
        for address in (0x089956D0, 0x0899FE8C):
            yield NativePatch(
                address,
                struct.pack("<I", 0x0812A070),
                struct.pack("<I", symbols["iop_photo_event"]),
                "handle click wheel and buttons in the full-size photo viewer",
            )
        yield NativePatch(
            0x08995724,
            struct.pack("<I", 0x081C2FA8),
            struct.pack("<I", symbols["iop_photo_timer"]),
            "advance held-button panning on the Photos model UI timer",
        )
        address = 0x081C2388
        yield NativePatch(
            address,
            arm_call(address, 0x081C2624),
            arm_call(address, symbols["iop_photo_open_large"]),
            "start each full-size photo browsing session at fit",
        )
        # Preserve the existing tail call so the controller's caller owns LR.
        address = 0x081C1350
        yield NativePatch(
            address,
            arm_call(address, 0x08103118)[:3] + b"\xea",
            arm_call(address, symbols["iop_photo_leave"])[:3] + b"\xea",
            "clear photo zoom across native controller transitions",
        )
        # PhotoBrowse_Large constructs an untiled, model-bound 'imag' BitmapView.
        address = 0x081002E4
        yield NativePatch(
            address,
            arm_call(address, 0x08259568),
            arm_call(address, symbols["iop_photo_blit"]),
            "render the full-size photo through its native BitmapView blit",
        )
    if long_audio:
        # kayboll/osos-lab PR 62, 5f3744d4b752dd36460d2c840edf251a6363c099.
        # r2 points past the 64-bit media time at each qualified instruction.
        for address, instruction in (
            (0x081BB5E8, 0xE512101C),
            (0x081BC0F4, 0xE5121014),
            (0x081BC114, 0xE512101C),
        ):
            yield NativePatch(
                address,
                struct.pack("<I", 0xE1A01FC0),
                struct.pack("<I", instruction),
                "compare the complete MP4 audio media time across long edits",
            )
        yield NativePatch(
            0x081BD204,
            arm_call(0x081BD204, 0x081BB188),
            arm_call(0x081BD204, symbols["iop_audio_seek"]),
            "accelerate only audio after native seek validation and video alignment",
        )
    if now_playing_artwork:
        yield NativePatch(
            0x081001F0,
            bytes.fromhex("b80bd4e1"),  # ldrh r0,[r4,#0xb8]
            arm_call(0x081001F0, symbols["iop_artwork_format"]),
            "select preview drawing mode from the actual dynamic bitmap format",
        )
        yield NativePatch(
            0x08998708,
            struct.pack("<I", 0x081EDA2C),
            struct.pack("<I", symbols["iop_artwork_property"]),
            "retain native current-track artwork before borrowing the preview bitmap",
        )
        yield NativePatch(
            0x089889A8,
            struct.pack("<I", 0x08100318),
            struct.pack("<I", symbols["iop_artwork_visibility"]),
            "release borrowed dynamic BitmapView contexts across visibility changes",
        )
    if artwork_diagnostics:
        if not (now_playing_artwork and bootloader_report):
            raise ValueError("Artwork diagnostics require artwork and boot reporting")
        yield NativePatch(
            0x08988974,
            struct.pack("<I", 0x0810012C),
            struct.pack("<I", symbols["iop_artwork_trace_paint"]),
            "record native Now Playing BitmapView state without changing rendering",
        )
        yield NativePatch(
            0x0810008C,
            arm_call(0x0810008C, 0x08268B64),
            arm_call(0x0810008C, symbols["iop_artwork_trace_query"]),
            "record the native preview source result without changing model ownership",
        )
        for address in (0x08100278, 0x081002E4):
            if photo_zoom and address == 0x081002E4:
                continue  # The photo wrapper forwards other draws to tracing.
            yield NativePatch(
                address,
                arm_call(address, 0x08259568),
                arm_call(address, symbols["iop_artwork_trace_blit"]),
                "record preview blit inputs while preserving the native draw",
            )
    if homebrew_eapps:
        # This call belongs to the game manifest loader, not the shared PKCS#7
        # verifier. r3 = NULL selects Apple's existing unsigned reader mode.
        # XML parsing and the executable's Verify/DRM paths are left intact.
        yield NativePatch(
            0x080F9414,
            bytes.fromhex("0530a0e1"),  # mov r3,r5 (detached signature path)
            bytes.fromhex("0030a0e3"),  # mov r3,#0
            "allow unsigned eapp manifests through the native game reader",
        )
    if dark_mode:
        for address, original, replacement in (
            (0x089A3BF4, 0x0821DAF4, "iop_appearance_action"),
            (0x089A7C3C, 0x0821DAF4, "iop_appearance_action"),
            (0x08997B60, 0x081E11F4, "iop_appearance_property"),
        ):
            yield NativePatch(
                address,
                struct.pack("<I", original),
                struct.pack("<I", symbols[replacement]),
                replacement,
            )
        for address, original, replacement in (
            (0x08058808, 0x0809C69C, "iop_preferences_hook"),
            (0x0817E320, 0x0817D6E8, "iop_appearance_clock_tick"),
            (0x0825AE9C, 0x08069A5C, "iop_appearance_fill"),
            (0x082872A8, 0x08259B28, "iop_appearance_text"),
            (0x081A8F0C, 0x08259B28, "iop_appearance_text"),
            (0x081C0170, 0x08259B28, "iop_appearance_text"),
            (0x081365E4, 0x08259B28, "iop_appearance_text"),
            (0x08196E24, 0x08259B28, "iop_appearance_text"),
            (0x081E0930, 0x08259B28, "iop_appearance_option_text"),
            (0x0828844C, 0x08259B28, "iop_appearance_shadow"),
            (0x0810020C, 0x08259B28, "iop_appearance_mask"),
            (0x08138304, 0x082C7820, "iop_appearance_clear"),
            (0x08164230, 0x082C7820, "iop_appearance_clear"),
            (0x0826A890, 0x0826A9A8, "iop_appearance_reflection"),
            (0x08263730, 0x08298E0C, "iop_appearance_selection_rect"),
            (0x08263C08, 0x08298E0C, "iop_appearance_selection_rect"),
            (0x08263934, 0x08259B28, "iop_appearance_gradient_first"),
            (0x08263D7C, 0x08259B28, "iop_appearance_gradient_second"),
            (0x082637E0, 0x08259B28, "iop_appearance_selection_border"),
            (0x08263820, 0x08259B28, "iop_appearance_selection_border"),
            (0x08263C4C, 0x08259B28, "iop_appearance_selection_border"),
        ):
            yield NativePatch(
                address,
                arm_call(address, original),
                arm_call(address, symbols[replacement]),
                replacement,
            )
        yield NativePatch(
            0x08268B64,
            struct.pack("<II", 0xE92D40F8, 0xE1A05001),
            struct.pack("<II", 0xE51FF004, symbols["iop_appearance_resource"]),
            "preserve ink on the light Settings calendar illustration",
        )
