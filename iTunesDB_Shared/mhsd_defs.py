"""MHSD (DataSet) field definitions.

Declarative :class:`FieldDef` list for the MHSD chunk — a dataset
container with a type field that determines its child.
"""

from .field_base import FieldDef, _u32

_S = "mhsd"

MHSD_HEADER_SIZE: int = 96

MHSD_FIELDS: list[FieldDef] = [
    _u32("dataset_type", 0x0C, section_type=_S, required=True),
]
