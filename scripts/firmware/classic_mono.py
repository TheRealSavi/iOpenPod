"""Native Classic Mono Audio row and its compiled resource identifiers."""

import struct
from pathlib import Path

from PIL import Image

from .classic_menu import MenuResources
from .classic_settings import add_settings_toggle

VALUE = 0x0CF00400
ROW = VALUE + 1
ACTION = "iOpenPod_Mono_Audio_Toggle"
PREVIEW = "iOpenPod_Mono_Audio_Preview"
ICON = VALUE + 7
ICON_PATH = Path(__file__).with_name("classic_about") / "mono_audio.png"


def mono_resources(menu: MenuResources) -> str:
    if any(VALUE <= key[1] <= ICON for key in menu.stock | menu.added):
        raise ValueError("Mono Audio IDs overlap existing resources")
    title, source, off, on, error = range(VALUE + 2, VALUE + 7)
    for resource_id, label in (
        (title, "Mono Audio"),
        (off, "Off"),
        (on, "On"),
        (error, "Not saved"),
    ):
        menu.added["Str ", resource_id] = label.encode("ascii") + b"\0"
    # Settings uses tinted coverage masks, with the reflection inside the frame.
    with Image.open(ICON_PATH) as image:
        if image.mode != "L" or image.size != (78, 121):
            raise ValueError("Expected a grayscale icon in the native Settings frame")
        width, height = image.size
        stride = (width + 3) & ~3
        pixels = image.tobytes("raw", "L", stride)
    menu.added["BMap", ICON] = (
        struct.pack("<4H5I", 8, 0, stride, 8, 0, 0, height, width, len(pixels)) + pixels
    )
    menu.added["IMAG", ICON] = struct.pack("<I", ICON)
    add_settings_toggle(
        menu,
        title="Mono Audio",
        title_id=title,
        source_id=source,
        row_id=ROW,
        value_id=VALUE,
        after=0x0DAD0C76,
        action_name=ACTION,
        preview_name=PREVIEW,
        image_binding=(0x80, ICON),
    )
    return (
        f'#define MONO_ACTION "{ACTION}"\n'
        f"#define MONO_VALUE {VALUE}u\n#define MONO_OFF {off}u\n"
        f"#define MONO_ON {on}u\n#define MONO_SAVE_ERROR {error}u\n"
    )
