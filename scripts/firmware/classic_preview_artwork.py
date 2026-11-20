"""Use the current native album-art source in the main-menu song preview."""

import hashlib
import struct

from .classic_menu import MenuResources
from .classic_resources import blocks, pack_blocks

PREVIEW_BINDINGS = 0x162
PREVIEW_IMAGE = 0x0DAD01BA
ARTWORK_SOURCE = 0x4A9
PREVIEW_LAYOUT = 0x0DAD01C0
LAYOUT_SHA256 = "d179dbe61b2a84cbf2ac0f553453b35b9919fcd4e6483c179407554eb8021238"


def preview_artwork_resources(menu: MenuResources) -> None:
    """Replace the static proxy binding while retaining native view ownership.

    Apple's HandleNowPlayingHilited always chooses the NoNowPlayingArt layout.
    Its image is an ordinary BitmapView, which can consume the same Draw source
    as Now Playing. That model owns artwork loading, change notices and fallback.
    """
    key = "VCvs", PREVIEW_BINDINGS
    expected = pack_blocks(
        [
            (child, struct.pack("<4I", 1, 4, 0x534F5243, source))
            for child, source in (
                (PREVIEW_IMAGE, 0x3B1),
                (0x0DAD01BB, 0x3B2),
                (0x0DAD01BC, 0x3B3),
                (0x0DAD01BD, 0x3B4),
            )
        ]
    )
    if menu.stock[key] != expected:
        raise ValueError("Unexpected native Now Playing preview bindings")
    artwork = pack_blocks([(0x534F5243, struct.pack("<3I", 0x7F00, 0x7F05, 1))])
    if menu.stock["SORC", ARTWORK_SOURCE] != artwork:
        raise ValueError("Unexpected native Now Playing artwork source")
    layout_key = "VLyt", PREVIEW_LAYOUT
    layout = menu.stock[layout_key]
    if hashlib.sha256(layout).hexdigest() != LAYOUT_SHA256:
        raise ValueError("Unexpected native Now Playing preview layout")
    if key in menu.added or layout_key in menu.added:
        raise ValueError("Now Playing preview already has a resource override")
    children = blocks(layout)
    image_options = [
        (kind, body)
        for kind, body in blocks(children[0][1])
        if kind not in range(1000, 1004)
    ]
    # Native constraint order is top, left, bottom, right. Bottom/right are
    # offsets from the screen's lower/right edges: (35,176)-(163,304), 128².
    # This layout is exclusive to the main-menu preview; shared View01B9 stays
    # intact. Native primary artwork and both fallback bitmaps are 128².
    image_options.extend(
        (kind, struct.pack("<iII", value, 0, 0))
        for kind, value in zip(range(1000, 1004), (35, 176, -77, -16), strict=True)
    )
    updated_layout = pack_blocks(
        [(PREVIEW_IMAGE, pack_blocks(image_options)), *children[1:]]
    )
    changed = bytearray(expected)
    struct.pack_into("<I", changed, 24, ARTWORK_SOURCE)
    menu.added[key] = bytes(changed)
    menu.added[layout_key] = updated_layout
    menu.replacements.add(key)
    menu.replacements.add(layout_key)
