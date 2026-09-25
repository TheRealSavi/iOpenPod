"""Model lookup functions — identify iPods from model numbers, serials, etc."""

import re

from .capabilities import _FAMILY_GEN_CAPABILITIES
from .models import IPOD_MODELS, SERIAL_SUFFIX_TO_MODEL, canonicalize_model_identity


def _identity_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def extract_model_number(model_str: str) -> str | None:
    """Extract normalised model number from ModelNumStr.

    ModelNumStr format varies:
    - ``"xA623"`` → ``"MA623"``
    - ``"MC293"`` → ``"MC293"``
    - ``"M9282"`` → ``"M9282"``
    - ``"P9804"`` → ``"M9804"``  (SysInfo sometimes uses non-M first char)
    """
    if not model_str:
        return None

    # Normalise 'x' prefix: "xA623" → "MA623"
    if model_str.startswith('x'):
        model_str = 'M' + model_str[1:]

    match = re.match(r'^(M[A-Z]?\d{3,4})', model_str.upper())
    if match:
        return match.group(1)

    # Some SysInfo ModelNumStr values use a non-M first character (e.g. "P9804"
    # instead of "M9804").  Try substituting M and re-matching.
    alt = 'M' + model_str[1:]
    match = re.match(r'^(M[A-Z]?\d{3,4})', alt.upper())
    if match:
        return match.group(1)

    return model_str.upper()[:5] if len(model_str) >= 5 else model_str.upper()


def usb_pid_identity_conflicts(
    model_family: str,
    generation: str,
    pid_family: str,
    pid_generation: str,
) -> bool:
    """Return True when an exact model tuple cannot belong to a USB PID hint."""
    model_family, generation, _model_color = canonicalize_model_identity(
        model_family,
        generation,
    )
    pid_family, pid_generation, _pid_color = canonicalize_model_identity(
        pid_family,
        pid_generation,
    )
    model_family_norm = _identity_text(model_family)
    pid_family_norm = _identity_text(pid_family)
    if not model_family_norm or not pid_family_norm:
        return False

    model_generation_norm = _identity_text(generation)
    pid_generation_norm = _identity_text(pid_generation)
    if pid_family_norm == "ipod" and not pid_generation_norm:
        return False

    family_compatible = model_family_norm == pid_family_norm

    if not family_compatible:
        return True

    if not model_generation_norm or not pid_generation_norm:
        return False
    if model_generation_norm == pid_generation_norm:
        return False

    # Some USB PID identities are coarser than the exact model table.
    if (
        pid_family_norm == "ipod"
        and pid_generation_norm == "5th gen"
        and model_generation_norm == "5.5th gen"
    ):
        return False
    if (
        pid_family_norm == "ipod"
        and pid_generation_norm == "4th gen (photo)"
        and model_generation_norm in {"4th gen (photo)", "4th gen (color)"}
    ):
        return False

    return True


def get_model_info(model_number: str | None) -> tuple[str, str, str, str] | None:
    """Get detailed model information from model number.

    Returns:
        Tuple of ``(name, generation, capacity, color)`` or ``None``.
    """
    if not model_number:
        return None

    if model_number in IPOD_MODELS:
        return IPOD_MODELS[model_number]

    # If the first character isn't M, try substituting M (handles SysInfo quirks)
    if not model_number.startswith('M') and len(model_number) > 1:
        alt = 'M' + model_number[1:]
        if alt in IPOD_MODELS:
            return IPOD_MODELS[alt]

    for prefix, info in IPOD_MODELS.items():
        if model_number.startswith(prefix[:4]):
            return info

    return None


def get_friendly_model_name(model_number: str | None) -> str:
    """Return a user-friendly model name string."""
    info = get_model_info(model_number)
    if info:
        name, gen, capacity, color = info
        if gen:
            parts = [name, gen]
        else:
            parts = [name]
        if capacity:
            parts.append(capacity)
        if color:
            parts.append(color)
        return " ".join(p for p in parts if p)
    return f"Unknown iPod ({model_number})" if model_number else "Unknown iPod"


def match_serial_suffix(serial: str) -> str | None:
    """Return the longest published model suffix matching *serial*."""

    normalized = str(serial or "").strip().upper()
    if not normalized:
        return None

    suffix_lengths = sorted(
        {len(suffix) for suffix in SERIAL_SUFFIX_TO_MODEL},
        reverse=True,
    )
    for suffix_length in suffix_lengths:
        if len(normalized) < suffix_length:
            continue
        candidate = normalized[-suffix_length:]
        if candidate in SERIAL_SUFFIX_TO_MODEL:
            return candidate
    return None


def lookup_by_serial(serial: str) -> tuple[str, tuple[str, str, str, str]] | None:
    """Look up an iPod model from its longest matching serial suffix.

    Returns:
        ``(model_number, (family, generation, capacity, color))`` or ``None``.
    """
    suffix = match_serial_suffix(serial)
    if not suffix:
        return None
    model_num = SERIAL_SUFFIX_TO_MODEL.get(suffix)
    if not model_num:
        return None
    info = IPOD_MODELS.get(model_num)
    if not info:
        return None
    return (model_num, info)


def infer_generation(
    family: str,
    capacity: str = "",
) -> str | None:
    """Best-effort generation inference from family + available signals.

    Uses the model table to find which generations match a given capacity.
    If only one generation of a family offers that capacity, we can infer
    the generation with certainty (e.g. iPod Classic 120GB → 6.5th Gen).

    Falls back to returning the sole generation if a family has only one.
    Returns ``None`` when the generation is ambiguous.
    """
    if not family:
        return None

    family_gens = {g for (f, g) in _FAMILY_GEN_CAPABILITIES if f == family}

    if len(family_gens) == 1:
        return family_gens.pop()

    if capacity:
        matching_gens: set[str] = set()
        for _mn, (_mf, _mg, _mc, _color) in IPOD_MODELS.items():
            if _mf == family and _mc == capacity:
                matching_gens.add(_mg)
        if len(matching_gens) == 1:
            return matching_gens.pop()

    return None
