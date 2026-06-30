"""Compile gettext .po files to .mo files.

The project only needs a small subset of gettext catalog features for the GUI
strings: singular ``msgid`` / ``msgstr`` entries with standard Python escaping.
Keeping this script local avoids requiring GNU gettext on contributor machines.
"""

from __future__ import annotations

import ast
import struct
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALE_ROOT = PROJECT_ROOT / "locale"
DOMAIN = "iopenpod"


def _unquote_po_string(line: str) -> str:
    return ast.literal_eval(line.strip())


def _read_po(path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    msgid: str | None = None
    msgstr: str | None = None
    active: str | None = None

    def flush() -> None:
        nonlocal msgid, msgstr, active
        if msgid is not None and msgstr is not None:
            messages[msgid] = msgstr
        msgid = None
        msgstr = None
        active = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgid "):
            if msgid is not None and msgstr is not None:
                flush()
            msgid = _unquote_po_string(line[6:])
            msgstr = None
            active = "msgid"
            continue
        if line.startswith("msgstr "):
            msgstr = _unquote_po_string(line[7:])
            active = "msgstr"
            continue
        if line.startswith('"') and active == "msgid" and msgid is not None:
            msgid += _unquote_po_string(line)
            continue
        if line.startswith('"') and active == "msgstr" and msgstr is not None:
            msgstr += _unquote_po_string(line)
            continue

    flush()
    return messages


def _write_mo(messages: dict[str, str], path: Path) -> None:
    keys = sorted(messages)
    ids = b""
    strs = b""
    offsets: list[tuple[int, int, int, int]] = []

    for key in keys:
        msgid = key.encode("utf-8")
        msgstr = messages[key].encode("utf-8")
        offsets.append((len(msgid), len(ids), len(msgstr), len(strs)))
        ids += msgid + b"\0"
        strs += msgstr + b"\0"

    count = len(keys)
    keystart = 7 * 4
    valuestart = keystart + count * 8
    ids_offset = valuestart + count * 8
    strs_offset = ids_offset + len(ids)

    output = [
        struct.pack(
            "Iiiiiii",
            0x950412DE,
            0,
            count,
            keystart,
            valuestart,
            0,
            0,
        )
    ]

    for msgid_len, msgid_offset, _msgstr_len, _msgstr_offset in offsets:
        output.append(struct.pack("ii", msgid_len, ids_offset + msgid_offset))
    for _msgid_len, _msgid_offset, msgstr_len, msgstr_offset in offsets:
        output.append(struct.pack("ii", msgstr_len, strs_offset + msgstr_offset))
    output.append(ids)
    output.append(strs)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(output))


def compile_catalogs() -> list[Path]:
    outputs: list[Path] = []
    for po_path in sorted(LOCALE_ROOT.glob(f"*/LC_MESSAGES/{DOMAIN}.po")):
        messages = _read_po(po_path)
        mo_path = po_path.with_suffix(".mo")
        _write_mo(messages, mo_path)
        outputs.append(mo_path)
    return outputs


if __name__ == "__main__":
    for output_path in compile_catalogs():
        print(output_path.relative_to(PROJECT_ROOT))
