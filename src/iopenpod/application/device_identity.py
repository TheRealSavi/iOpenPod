"""Device identity helpers that keep iPod internals out of the GUI shell."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import Any


def identify_ipod_at_root(path: str) -> Any | None:
    """Identify an iPod mounted at a validated root path."""

    from iopenpod.device import identify_ipod_at_path

    return identify_ipod_at_path(path)


def refresh_device_disk_usage(
    device_info: Any | None,
    *,
    disk_usage_fn: Callable[[str], Any] = shutil.disk_usage,
) -> None:
    """Refresh mutable disk usage fields on a device info object."""

    if device_info is None:
        return

    path = str(getattr(device_info, "path", "") or "")
    if not path:
        return

    try:
        total, _used, free = disk_usage_fn(path)
    except OSError:
        return

    device_info.disk_size_gb = round(total / 1e9, 1)
    device_info.free_space_gb = round(free / 1e9, 1)


def format_checksum_type_name(value: Any) -> str:
    """Return the display name for a device checksum type value."""

    name = getattr(value, "name", None)
    if name:
        return str(name)

    try:
        from iopenpod.device import ChecksumType

        return ChecksumType(value).name
    except (TypeError, ValueError):
        return "Unknown"


def generic_ipod_image_filename() -> str:
    """Return the generic iPod product image filename."""

    from iopenpod.device import GENERIC_IMAGE

    return GENERIC_IMAGE


def resolve_ipod_product_image_filename(
    family: str,
    generation: str,
    color: str = "",
) -> str:
    """Resolve the product image filename for iPod identity fields."""

    from iopenpod.device import resolve_image_filename

    return (
        resolve_image_filename(family, generation, color)
        or generic_ipod_image_filename()
    )


def resolve_ipod_image_color(image_filename: str) -> tuple[int, int, int] | None:
    """Return the representative RGB color for an iPod product image."""

    if not image_filename:
        return None

    from iopenpod.device import color_for_image

    return color_for_image(image_filename)


def resolve_device_image_filename(device_info: Any | None) -> str:
    """Return the product image filename for a device identity object."""

    if device_info is None:
        return ""

    from iopenpod.device import image_for_model, resolve_image_filename

    model_number = str(getattr(device_info, "model_number", "") or "")
    if model_number:
        image = image_for_model(model_number) or ""
        if image:
            return image

    model_family = str(getattr(device_info, "model_family", "") or "")
    generation = str(getattr(device_info, "generation", "") or "")
    color = str(getattr(device_info, "color", "") or "")
    if model_family and generation:
        return resolve_image_filename(model_family, generation, color) or ""

    return ""
