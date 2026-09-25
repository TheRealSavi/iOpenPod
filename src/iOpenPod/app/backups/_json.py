"""Strict JSON decoding shared by versioned Backup Archive formats."""

from __future__ import annotations

import json
from typing import NoReturn, cast


class StrictJsonError(ValueError):
    """JSON bytes are ambiguous, non-standard, or structurally unreadable."""


def loads_strict(data: bytes) -> object:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    try:
        value: object = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except StrictJsonError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise StrictJsonError(str(error)) from error
    _reject_unicode_surrogates(value)
    return value


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise StrictJsonError(f"Duplicate JSON field: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise StrictJsonError(f"Non-standard JSON number: {value}")


def _reject_unicode_surrogates(value: object) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise StrictJsonError(
                    "JSON text contains an unpaired Unicode surrogate"
                )
        elif isinstance(current, dict):
            mapping = cast("dict[object, object]", current)
            pending.extend(mapping.keys())
            pending.extend(mapping.values())
        elif isinstance(current, list):
            pending.extend(cast("list[object]", current))


__all__ = ["StrictJsonError", "loads_strict"]
