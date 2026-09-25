# iPodDB/shared/memory.py

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import cast


def deep_sizeof(obj: object, seen: set[int] | None = None) -> int:
    """
    Approximate total Python memory footprint of an object graph.

    Includes:
    - object itself
    - referenced containers
    - dataclass fields
    - bytes payloads
    - strings
    - child trees

    Avoids double counting shared objects.
    """
    if seen is None:
        seen = set()

    obj_id = id(obj)

    if obj_id in seen:
        return 0

    seen.add(obj_id)

    size = sys.getsizeof(obj)

    if is_dataclass(obj):
        for dataclass_field in fields(obj):
            size += deep_sizeof(
                getattr(
                    obj,
                    dataclass_field.name,
                ),
                seen,
            )

        return size

    if isinstance(obj, Mapping):
        mapping = cast(
            "Mapping[object, object]",
            obj,
        )

        for key, value in mapping.items():
            size += deep_sizeof(
                key,
                seen,
            )
            size += deep_sizeof(
                value,
                seen,
            )

        return size

    if isinstance(obj, tuple):
        tuple_items = cast(
            "tuple[object, ...]",
            obj,
        )

        for item in tuple_items:
            size += deep_sizeof(
                item,
                seen,
            )

        return size

    if isinstance(obj, list):
        list_items = cast(
            "list[object]",
            obj,
        )

        for item in list_items:
            size += deep_sizeof(
                item,
                seen,
            )

        return size

    if isinstance(obj, (set, frozenset)):
        set_items = cast(
            "set[object] | frozenset[object]",
            obj,
        )

        for item in set_items:
            size += deep_sizeof(
                item,
                seen,
            )

    return size
