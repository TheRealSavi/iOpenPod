"""Synthetic-device fixture serialized by the actual compiled firmware writer."""

import xml.etree.ElementTree as ET
from pathlib import Path

REPORT_XML = (
    Path(__file__).parents[1] / "fixtures/firmware/classic-boot-report.xml"
).read_bytes()


def report_xml(**fields: str | int) -> bytes:
    """Vary selected report fields without reproducing the production encoder."""
    root = ET.fromstring(REPORT_XML)
    dictionary = root.find("./dict/dict")
    assert dictionary is not None
    children = list(dictionary)
    for key, value in zip(children[::2], children[1::2], strict=True):
        if key.text in fields:
            replacement = fields[key.text]
            value.tag = "integer" if type(replacement) is int else "string"
            value.text = str(replacement)
    encoded = ET.tostring(root, encoding="utf-8")
    assert isinstance(encoded, bytes)
    return encoded
