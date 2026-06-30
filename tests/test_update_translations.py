from pathlib import Path

from scripts.compile_translations import _read_po
from scripts.update_translations import extract_messages, update_catalog


def test_extract_messages_reads_literal_translation_calls(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(
            [
                "from infrastructure.i18n import tr as _",
                "label = _('Hello')",
                "other = tr('World')",
                "dynamic = _(f'Ignored {name}')",
            ]
        ),
        encoding="utf-8",
    )

    messages = extract_messages([source])

    assert sorted(messages) == ["Hello", "World"]


def test_extract_messages_reads_i18n_widget_literals(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(
            [
                "row = ComboRow(",
                "    'Mode',",
                "    'Choose how work is done.',",
                "    options=['Auto', 'Manual'],",
                "    current='Auto',",
                ")",
                "page = self._make_page('General', 'Appearance', card)",
                "self.trackTitleBar.setTitle('All Tracks')",
                "self._set_status('Refresh failed')",
                "self._show_episode_empty('Waiting', 'No episodes yet.')",
                "combo = _make_setting_combo(['Newest Episode', 'Next Episode'])",
            ]
        ),
        encoding="utf-8",
    )

    messages = extract_messages([source])

    assert sorted(messages) == [
        "All Tracks",
        "Appearance",
        "Auto",
        "Choose how work is done.",
        "General",
        "Manual",
        "Mode",
        "Newest Episode",
        "Next Episode",
        "No episodes yet.",
        "Refresh failed",
        "Waiting",
    ]


def test_update_catalog_appends_missing_msgids(tmp_path: Path) -> None:
    catalog = tmp_path / "iopenpod.po"
    catalog.write_text(
        "\n".join(
            [
                'msgid ""',
                'msgstr ""',
                '"Language: zh_CN\\n"',
                "",
                'msgid "Existing"',
                'msgstr "已有"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    missing = update_catalog(
        catalog,
        {"Existing": ["sample.py:1"], "New String": ["sample.py:2"]},
        check=False,
    )

    assert missing == ["New String"]
    assert _read_po(catalog)["New String"] == ""


def test_update_catalog_check_reports_missing_without_writing(tmp_path: Path) -> None:
    catalog = tmp_path / "iopenpod.po"
    catalog.write_text('msgid "Existing"\nmsgstr "已有"\n', encoding="utf-8")

    missing = update_catalog(
        catalog,
        {"Existing": ["sample.py:1"], "New String": ["sample.py:2"]},
        check=True,
    )

    assert missing == ["New String"]
    assert "New String" not in catalog.read_text(encoding="utf-8")
