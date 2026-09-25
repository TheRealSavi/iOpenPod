from datetime import UTC, timezone


def sample_rate_to_fixed(hz: int, _device_timezone: timezone = UTC) -> int:
    """Encode sample rate as 16.16 fixed-point for MHIT offset 0x3C."""
    hz = max(0, min(hz, 0xFFFF))
    return hz << 16


def fixed_to_sample_rate(raw: int, _device_timezone: timezone = UTC) -> int:
    """Decode 16.16 fixed-point sample rate to integer Hz."""
    return raw >> 16


def clamp_rating(value: int, _device_timezone: timezone = UTC) -> int:
    """Clamp rating to 0..100"""
    return max(0, min(100, value))


def clamp_volume(value: int) -> int:
    """Clamp volume adjustment to  -255..+255"""
    return max(-255, min(255, value))
