"""Bounded XML framing shared by named settings, inspection and clock evidence.

Nodes retain exact UTF-8 byte spans and decoded text. Parsing grants no write
permission: each consumer independently checks uniqueness, scalar shape and
its own qualified field domain. In particular, an empty self-closing element
has no replaceable text span even though it is a readable observation.
"""

import re
from dataclasses import dataclass, field
from xml.parsers import expat

_MAX_BYTES = 4 * 1024 * 1024
_MAX_NODES = 4096
_MAX_TEXT = 512
_DECIMAL = re.compile(r"[ \t\r\n]*\+?([0-9]+)[ \t\r\n]*\Z")


@dataclass(slots=True)
class NamedNode:
    name: str
    attributes: dict[str, str]
    start: int
    end: int = 0
    complex: bool = False
    self_closing: bool = False
    children: list["NamedNode"] = field(default_factory=list["NamedNode"])
    text: list[str] = field(default_factory=list[str])


def _preview(text: str) -> str:
    if len(text) <= _MAX_TEXT:
        return text
    return text[:_MAX_TEXT] + "… [display truncated]"


def parse_named_xml(source: bytes) -> tuple[NamedNode | None, tuple[str, ...]]:
    if len(source) > _MAX_BYTES:
        return None, (
            "Named Preferences XML exceeds the supported size; bytes are retained.",
        )
    parser = expat.ParserCreate()
    roots: list[NamedNode] = []
    stack: list[NamedNode] = []
    count = 0

    def reject(*_args: object) -> None:
        raise ValueError("DTD and entity declarations are not supported")

    def reject_external_entity(*_args: object) -> int:
        return 0

    def declaration(_version: str, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.lower() not in (
            "utf-8",
            "utf8",
            "us-ascii",
        ):
            raise ValueError("only UTF-8 named Preferences XML is qualified")

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if count > _MAX_NODES or len(stack) >= 8:
            raise ValueError("XML exceeds the structural inspection limit")
        offset = parser.CurrentByteIndex
        quote = 0
        while offset < len(source):
            char = source[offset]
            if quote:
                if char == quote:
                    quote = 0
            elif char in (34, 39):
                quote = char
            elif char == 62:
                break
            offset += 1
        node = NamedNode(name, attributes, offset + 1)
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        node = stack.pop()
        node.end = parser.CurrentByteIndex
        if source[node.start - 2 : node.start] == b"/>":
            node.end = node.start
            node.self_closing = True

    def characters(value: str) -> None:
        if stack:
            stack[-1].text.append(value)

    def complex_content(*_args: object) -> None:
        if stack:
            stack[-1].complex = True

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.XmlDeclHandler = declaration
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject_external_entity
    parser.CommentHandler = complex_content
    parser.ProcessingInstructionHandler = complex_content
    parser.StartCdataSectionHandler = complex_content
    try:
        source.decode("utf-8-sig")
        if b"\0" in source:
            raise ValueError("only UTF-8 named Preferences XML is qualified")
        parser.Parse(source, True)
    except (expat.ExpatError, UnicodeError, ValueError) as error:
        return None, (
            f"Named Preferences XML is uninterpreted: {_preview(str(error))}.",
        )
    if len(roots) != 1 or roots[0].name != "iPodSettings":
        return None, ("Named Preferences XML has an unqualified root.",)
    if roots[0].attributes != {"version": "1.0"}:
        return None, ("Named Preferences XML has an unqualified format version.",)
    return roots[0], ()


def unsigned_decimal(text: str, bits: int, *, boolean: bool = False) -> int | None:
    # Native serializers use decimal words. Avoid reproducing permissive native
    # numeric-prefix parsing: odd spellings stay visible, never normalized.
    if boolean and text[:1] in (" ", "\t", "\r", "\n"):
        return None
    match = _DECIMAL.fullmatch(text)
    if match is None:
        return None
    digits = match[1].lstrip("0") or "0"
    if len(digits) > (10 if bits == 32 else 20):
        return None
    value = int(digits)
    return value if value < 1 << bits else None
