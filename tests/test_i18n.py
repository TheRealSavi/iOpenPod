from PyQt6.QtWidgets import QSplitter

from GUI.widgets.trackListTitleBar import TrackListTitleBar
from infrastructure.i18n import (
    LANGUAGE_DE,
    LANGUAGE_EN,
    LANGUAGE_ES,
    LANGUAGE_FR,
    LANGUAGE_ZH,
    LOCALE_DIR,
    language_from_display_name,
    language_options,
    normalize_language,
    set_language,
    tr,
)


def test_language_normalization_accepts_aliases() -> None:
    assert normalize_language("zh_CN") == LANGUAGE_ZH
    assert normalize_language("zh-Hans") == LANGUAGE_ZH
    assert normalize_language("en_US") == LANGUAGE_EN
    assert normalize_language("de_DE") == LANGUAGE_DE
    assert normalize_language("Deutsch") == LANGUAGE_DE
    assert normalize_language("fr_FR") == LANGUAGE_FR
    assert normalize_language("Français") == LANGUAGE_FR
    assert normalize_language("es_ES") == LANGUAGE_ES
    assert normalize_language("Español") == LANGUAGE_ES
    assert normalize_language("unsupported") == LANGUAGE_EN


def test_translation_uses_active_language_and_falls_back_to_source() -> None:
    try:
        set_language("zh")
        assert tr("Settings") == "设置"
        assert tr("Cache Location") == "缓存位置"
        assert tr("Select an Album") == "选择专辑"
        assert tr("All Tracks") == "全部曲目"
        assert tr("Artist") == "艺人"
        assert tr("Album") == "专辑"
        assert tr("Music") == "音乐"
        assert tr("Ringtones") == "铃声"
        assert tr("Rentals") == "租借影片"
        assert tr("Name") == "名称"
        assert tr("Date Added") == "添加日期"
        assert tr("Scrobble on Sync") == "同步时记录播放"
        assert tr("Auto") == "自动"
        assert tr("Balanced") == "均衡"
        assert tr("iPod Wins") == "iPod 优先"
        assert tr("Add Podcast") == "添加播客"
        assert tr("Refresh All") == "全部刷新"
        assert tr("Sync Podcasts") == "同步播客"
        assert tr("No Podcast Subscriptions") == "没有播客订阅"
        assert tr("Add Your First Podcast") == "添加第一个播客"
        assert tr("{count:,} songs").format(count=2) == "2 首歌曲"
        assert tr("Untranslated source") == "Untranslated source"

        set_language("en")
        assert tr("Settings") == "Settings"
    finally:
        set_language("en")


def test_language_selector_display_names_map_to_codes() -> None:
    assert language_options() == ["English", "中文", "Deutsch", "Français", "Español"]
    assert language_from_display_name("English") == LANGUAGE_EN
    assert language_from_display_name("中文") == LANGUAGE_ZH
    assert language_from_display_name("Deutsch") == LANGUAGE_DE
    assert language_from_display_name("Français") == LANGUAGE_FR
    assert language_from_display_name("Español") == LANGUAGE_ES


def test_chinese_gettext_catalog_is_compiled() -> None:
    assert (LOCALE_DIR / "zh_CN" / "LC_MESSAGES" / "iopenpod.mo").is_file()


def test_additional_gettext_catalogs_are_compiled() -> None:
    assert (LOCALE_DIR / "de" / "LC_MESSAGES" / "iopenpod.mo").is_file()
    assert (LOCALE_DIR / "fr" / "LC_MESSAGES" / "iopenpod.mo").is_file()
    assert (LOCALE_DIR / "es" / "LC_MESSAGES" / "iopenpod.mo").is_file()


def test_additional_language_catalogs_translate_core_strings() -> None:
    try:
        set_language("de")
        assert tr("Settings") == "Einstellungen"
        assert tr("Add Podcast") == "Podcast hinzufügen"
        assert tr("No Podcast Subscriptions") == "Keine Podcast-Abonnements"

        set_language("fr")
        assert tr("Settings") == "Paramètres"
        assert tr("Add Podcast") == "Ajouter un podcast"
        assert tr("No Podcast Subscriptions") == "Aucun abonnement aux podcasts"

        set_language("es")
        assert tr("Settings") == "Configuración"
        assert tr("Add Podcast") == "Añadir podcast"
        assert tr("No Podcast Subscriptions") == "No hay suscripciones a podcasts"
    finally:
        set_language("en")


def test_track_title_bar_leaves_dynamic_titles_untranslated(qtbot) -> None:
    try:
        set_language("zh")
        splitter = QSplitter()
        qtbot.addWidget(splitter)
        title_bar = TrackListTitleBar(splitter)
        qtbot.addWidget(title_bar)

        title_bar.setTitle("Settings")
        assert title_bar.title.text() == "Settings"

        title_bar.setTitle("Settings", translate=True)
        assert title_bar.title.text() == "设置"
    finally:
        set_language("en")


def test_track_list_formatters_use_active_language() -> None:
    from GUI.widgets.MBListView import (
        format_bool_flag,
        format_chapter_count,
        format_explicit,
    )

    try:
        set_language("zh")

        assert format_bool_flag(1) == "是"
        assert format_explicit(1) == "限制级"
        assert format_explicit(2) == "洁净版"
        assert format_chapter_count(2) == "2 个章节"
    finally:
        set_language("en")
