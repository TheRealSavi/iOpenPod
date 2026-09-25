"""Normalization helpers for identifiers accepted by Device Registry."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from device_registry.models import UsbIdentifier

APPLE_USB_VENDOR_ID = 0x05AC
_MODEL_NUMBER = re.compile(r"^M[A-Z0-9]{4}")


def normalize_model_number(value: str) -> str:
    """Normalize the model-number spellings found in iPod metadata."""

    text = value.strip().upper()
    if len(text) >= 2 and text[0] in {"X", "P"}:
        text = f"M{text[1:]}"
    match = _MODEL_NUMBER.match(text)
    return match.group(0) if match is not None else text


def normalize_serial(value: str) -> str:
    """Normalize a serial while retaining only its identifying characters."""

    return "".join(character for character in value.upper() if character.isalnum())


def format_usb_identifier(identifier: UsbIdentifier) -> str:
    return f"{identifier.vendor_id:04X}:{identifier.product_id:04X}"


def parse_unsigned_integer(value: str) -> int | None:
    """Parse the decimal or explicitly hexadecimal integers used by SysInfo."""

    token = value.strip().split(maxsplit=1)[0] if value.strip() else ""
    if not token:
        return None
    try:
        return int(token, 0)
    except ValueError:
        return None
