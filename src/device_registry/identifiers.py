"""Normalization helpers for identifiers accepted by Device Registry."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from device_registry.models import UsbIdentifier

APPLE_USB_VENDOR_ID = 0x05AC
_MODEL_NUMBER = re.compile(r"^M[A-Z0-9]{4}")
_HP_MODEL_NUMBER = re.compile(r"^MP[0-9]{4}(?=$|[^A-Z0-9])")
# HP order numbers name the same marketed variants as the six-character models.
# Evidence: docs/research/hp-ipod-mini-identification.md.
_HP_MINI_ORDER_NUMBERS = {"PW753AA": "MP5001", "PX762AA": "MP5002"}


def normalize_model_number(value: str) -> str:
    """Normalize the model-number spellings found in iPod metadata."""

    text = value.strip().upper()
    hp_model = _HP_MINI_ORDER_NUMBERS.get(text.partition("#")[0])
    if hp_model is not None:
        return hp_model
    if len(text) >= 2 and text[0] in {"X", "P"}:
        text = f"M{text[1:]}"
    hp_match = _HP_MODEL_NUMBER.match(text)
    if hp_match is not None:
        return hp_match.group(0)
    match = _MODEL_NUMBER.match(text)
    return match.group(0) if match is not None else text


def normalize_serial(value: str) -> str:
    """Normalize a serial while retaining only its identifying characters."""

    return "".join(character for character in value.upper() if character.isalnum())


def normalize_product_serial(value: str) -> str:
    """Accept Apple or HP product serials, without assigning a model to HP serials."""

    serial = value.replace(" ", "").strip().upper()
    return serial if re.fullmatch(r"[A-Z0-9]{10,12}", serial, re.ASCII) else ""


def has_apple_serial_format(serial: str) -> bool:
    """Only Apple-length serials may participate in Apple's model-suffix lookup."""

    return re.fullmatch(r"[A-Z0-9]{11,12}", serial, re.ASCII) is not None


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
