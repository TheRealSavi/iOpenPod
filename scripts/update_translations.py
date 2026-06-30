"""Extract gettext msgids from source and update locale catalogs.

The app uses English source strings wrapped in ``tr(...)`` or the conventional
``_(...)`` alias. This script keeps ``locale/*/LC_MESSAGES/iopenpod.po`` files
in sync without requiring GNU gettext or Babel on contributor machines.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

from scripts.compile_translations import DOMAIN, LOCALE_ROOT, PROJECT_ROOT, _read_po

SOURCE_ROOTS = (
    "GUI",
    "app_core",
    "infrastructure",
    "main.py",
    "sync_progress_stages.py",
)
TRANSLATION_FUNCTIONS = {"_", "tr"}
I18N_LITERAL_ARG_CALLS = {
    "ActionRow": {0, 1},
    "ComboRow": {0, 1},
    "FileRow": {0, 1},
    "FolderRow": {0, 1},
    "ResettableFolderRow": {0, 1},
    "SettingRow": {0, 1},
    "SpinRow": {0, 1},
    "ToggleRow": {0, 1},
    "ToolRow": {0, 1},
    "_LastFmAuthRow": {0, 1},
    "_TokenRow": {0, 1},
    "BrowserPane": {0},
    "setTitle": {0},
    "_make_pair": {0},
    "_make_setting_combo": {0},
    "_make_setting_label": {0},
    "_set_action_status": {0},
    "_set_status": {0},
    "_show_episode_empty": {0, 1},
    "_show_episode_loading": {0, 1},
    "show_empty": {0, 1},
    "show_error": {0, 1},
    "show_loading": {0, 1},
}
I18N_LITERAL_KEYWORDS = {
    "button_text",
    "current",
    "default_label",
    "options",
}
I18N_ALL_LITERAL_ARG_CALLS = {"_make_page"}


def _source_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SOURCE_ROOTS:
        root = PROJECT_ROOT / root_name
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return sorted(files)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_strings(node: ast.AST) -> list[str]:
    """Return literal string constants nested under *node*."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return []
    values: list[str] = []
    for child in ast.iter_child_nodes(node):
        values.extend(_literal_strings(child))
    return values


def _add_message(
    messages: dict[str, list[str]],
    msgid: str,
    rel_path: Path,
    lineno: int,
) -> None:
    messages[msgid].append(f"{rel_path}:{lineno}")


def extract_messages(paths: list[Path] | None = None) -> dict[str, list[str]]:
    """Return msgid -> source locations for literal translation calls."""

    messages: dict[str, list[str]] = defaultdict(list)
    for path in paths or _source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise SystemExit(f"Could not parse {path}: {exc}") from exc

        try:
            rel_path = path.relative_to(PROJECT_ROOT)
        except ValueError:
            rel_path = path
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            call_name = _call_name(node.func)
            if call_name in TRANSLATION_FUNCTIONS:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    _add_message(messages, first_arg.value, rel_path, node.lineno)
                continue

            literal_arg_indexes = I18N_LITERAL_ARG_CALLS.get(call_name or "")
            if literal_arg_indexes is not None:
                for index in literal_arg_indexes:
                    if index < len(node.args):
                        for msgid in _literal_strings(node.args[index]):
                            _add_message(messages, msgid, rel_path, node.lineno)
            elif call_name in I18N_ALL_LITERAL_ARG_CALLS:
                for arg in node.args:
                    for msgid in _literal_strings(arg):
                        _add_message(messages, msgid, rel_path, node.lineno)

            if call_name in I18N_LITERAL_ARG_CALLS:
                for keyword in node.keywords:
                    if keyword.arg in I18N_LITERAL_KEYWORDS:
                        for msgid in _literal_strings(keyword.value):
                            _add_message(messages, msgid, rel_path, node.lineno)

    return dict(sorted(messages.items(), key=lambda item: item[0]))


def _po_literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _po_field(keyword: str, text: str) -> list[str]:
    if "\n" not in text:
        return [f"{keyword} {_po_literal(text)}"]
    lines = [f"{keyword} \"\""]
    lines.extend(_po_literal(part) for part in text.splitlines(keepends=True))
    return lines


def _format_entry(msgid: str, locations: list[str]) -> str:
    refs = " ".join(locations[:8])
    lines = [f"#: {refs}"] if refs else []
    if len(locations) > 8:
        lines.append(f"#. Additional references: {len(locations) - 8}")
    lines.extend(_po_field("msgid", msgid))
    lines.append('msgstr ""')
    return "\n".join(lines)


def update_catalog(po_path: Path, messages: dict[str, list[str]], *, check: bool) -> list[str]:
    """Append missing msgids to a catalog, or return them in check mode."""

    existing = _read_po(po_path) if po_path.exists() else {}
    missing = [msgid for msgid in messages if msgid not in existing]
    if check or not missing:
        return missing

    original = po_path.read_text(encoding="utf-8") if po_path.exists() else ""
    separator = "\n\n" if original and not original.endswith("\n\n") else ""
    entries = "\n\n".join(_format_entry(msgid, messages[msgid]) for msgid in missing)
    po_path.parent.mkdir(parents=True, exist_ok=True)
    po_path.write_text(f"{original}{separator}{entries}\n", encoding="utf-8")
    return missing


def _catalog_paths() -> list[Path]:
    return sorted(LOCALE_ROOT.glob(f"*/LC_MESSAGES/{DOMAIN}.po"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if any catalog is missing extracted msgids.",
    )
    args = parser.parse_args(argv)

    messages = extract_messages()
    catalog_paths = _catalog_paths()
    if not catalog_paths:
        print("No locale catalogs found.", file=sys.stderr)
        return 1

    failed = False
    for po_path in catalog_paths:
        missing = update_catalog(po_path, messages, check=args.check)
        rel_path = po_path.relative_to(PROJECT_ROOT)
        if missing:
            print(f"{rel_path}: {len(missing)} missing msgids")
            for msgid in missing[:20]:
                print(f"  - {msgid!r}")
            if len(missing) > 20:
                print(f"  ... {len(missing) - 20} more")
            failed = failed or args.check
        else:
            print(f"{rel_path}: up to date")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
