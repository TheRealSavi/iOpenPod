"""Narrow untrusted Jellyfin JSON values before constructing models."""

from typing import TypeGuard, cast


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(
        isinstance(key, str) for key in cast("dict[object, object]", value)
    )


def is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a JSON string.")
    return value


def optional_text(value: object) -> str:
    return "" if value is None else text(value)


def integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Expected a JSON integer.")
    return value


def optional_integer(value: object) -> int:
    return 0 if value is None else integer(value)
