"""Settings illustrations follow layout, hover, and popup lifetime without writes."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QEnterEvent, QPalette, QPixmap
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QGraphicsOpacityEffect, QTabWidget, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.presentation.settings_illustrations import (
    SettingExample,
    has_setting_image,
    setting_image,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.settings_tab import (
    SettingsExampleImage,
    SettingsPreview,
    SettingsTab,
)


@pytest.fixture
def page() -> Iterator[SettingsPage]:
    context = build_context()
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.resize(1760, 1000)
    page.show()
    _settle()
    yield page
    page.close()
    page.deleteLater()
    context.shutdown()


def _settle() -> None:
    for _ in range(3):
        APPLICATION.processEvents()


def _enter(row: SettingRow) -> None:
    APPLICATION.sendEvent(row, QEnterEvent(QPointF(8, 8), QPointF(8, 8), QPointF(8, 8)))
    _settle()
    QTest.qWait(220)


def _appearance(page: SettingsPage) -> SettingsTab:
    tab = page.findChild(SettingsTab, "appearanceSettingsScroll")
    assert tab is not None
    return tab


def _example(tab: SettingsTab) -> SettingExample | None:
    # Read afresh after event delivery rather than retaining a narrowed property.
    delay = tab.preview.findChild(QTimer, "settingsPreviewHoverDelay")
    if delay is not None and delay.isActive():
        QTest.qWait(220)
    return tab.preview.example


def _shown_example(preview: SettingsPreview) -> SettingExample | None:
    # Animation and timer callbacks can change this property between assertions.
    return preview.example


def test_tabs_and_all_categories_share_responsive_width(page: SettingsPage) -> None:
    tabs = page.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    for width in (1000, 1400, 1719, 1720, 2064, 1300, 850):
        page.resize(width, 1000)
        _settle()
        assert page.width() == width
        for index in range(tabs.count()):
            if not tabs.isTabVisible(index):
                continue
            tabs.setCurrentIndex(index)
            _settle()
            tab = tabs.currentWidget()
            assert isinstance(tab, SettingsTab)
            expected = (
                960 if width >= 1720 else tab.viewport().width() - 2 * LAYOUT.space_lg
            )
            assert tabs.tabBar().width() == expected
            assert tab.preview.isVisible() == (width >= 1720)
            bar_left = tabs.tabBar().mapTo(page, tabs.tabBar().rect().topLeft()).x()
            for group in tab.findChildren(SettingGroup):
                if group.isVisible():
                    assert group.width() == expected
                    assert group.mapTo(page, group.rect().topLeft()).x() == bar_left


def test_dropdown_retains_example_and_highlights_without_saving(
    page: SettingsPage,
) -> None:
    tab = _appearance(page)
    combo = tab.findChild(AppComboBox, "darkThemeCombo")
    assert combo is not None
    row = combo.parentWidget()
    assert isinstance(row, SettingRow)
    changes = QSignalSpy(combo.currentIndexChanged)
    _enter(row)
    shown = _example(tab)
    assert shown is not None and shown.key == "darkThemeCombo"
    original = combo.currentIndex()
    combo.showPopup()
    APPLICATION.sendEvent(row, QEvent(QEvent.Type.Leave))
    _settle()
    shown = _example(tab)
    assert shown is not None and shown.key == "darkThemeCombo"
    view = combo.view()
    for index in (2, 3, original):
        QTest.mouseMove(
            view.viewport(), view.visualRect(view.model().index(index, 0)).center()
        )
        _settle()
        shown = _example(tab)
        assert shown is not None and shown.value == str(combo.itemData(index))
        assert combo.currentIndex() == original and changes.count() == 0
    combo.hidePopup()
    QTest.mouseMove(tab.viewport(), tab.preview.geometry().center())
    _settle()
    assert _example(tab) is None


def test_resize_tab_switch_and_scroll_clear_stale_examples(page: SettingsPage) -> None:
    tab = _appearance(page)
    row = tab.findChildren(SettingRow)[0]
    _enter(row)
    assert _example(tab) is not None
    page.resize(1200, 500)
    _settle()
    assert _example(tab) is None and not tab.preview.isVisible()
    page.resize(1760, 500)
    _settle()
    _enter(row)
    assert _example(tab) is not None
    tab.verticalScrollBar().setValue(tab.verticalScrollBar().maximum())
    _settle()
    assert _example(tab) is None
    tab.verticalScrollBar().setValue(0)
    _settle()
    _enter(row)
    tabs = page.findChild(QTabWidget, "settingsTabs")
    assert tabs is not None
    tabs.setCurrentIndex(1)
    _settle()
    assert _example(tab) is None
    tabs.setCurrentIndex(0)
    _settle()
    assert _example(tab) is None


def test_dropdown_opened_in_narrow_layout_gains_preview_when_widened(
    page: SettingsPage,
) -> None:
    tab = _appearance(page)
    combo = tab.findChild(AppComboBox, "appearanceModeCombo")
    assert combo is not None
    page.resize(1200, 1000)
    _settle()
    combo.showPopup()
    _settle()
    assert _example(tab) is None
    page.resize(1760, 1000)
    _settle()
    shown = _example(tab)
    assert shown is not None and shown.key == "appearanceModeCombo"
    combo.hidePopup()


def test_unillustrated_row_and_its_dropdown_leave_the_space_blank(
    page: SettingsPage,
) -> None:
    tabs = page.findChild(QTabWidget, "settingsTabs")
    tab = page.findChild(SettingsTab, "librarySettingsScroll")
    assert tabs is not None and tab is not None
    tabs.setCurrentWidget(tab)
    _settle()
    navigation = tab.findChild(AppComboBox, "navigationStyleCombo")
    draft = tab.findChild(AppComboBox, "draftAllChangesCombo")
    assert navigation is not None and draft is not None
    illustrated_row, plain_row = navigation.parentWidget(), draft.parentWidget()
    assert isinstance(illustrated_row, SettingRow) and isinstance(plain_row, SettingRow)
    _enter(illustrated_row)
    assert _example(tab) is not None
    APPLICATION.sendEvent(illustrated_row, QEvent(QEvent.Type.Leave))
    _enter(plain_row)
    assert _example(tab) is None
    draft.showPopup()
    _settle()
    assert _example(tab) is None
    draft.hidePopup()


@pytest.mark.parametrize("background", ["#f2f3f6", "#12171d"])
def test_each_illustrated_choice_has_a_packaged_image(
    page: SettingsPage, background: str
) -> None:
    palette = QPalette(page.palette())
    palette.setColor(QPalette.ColorRole.Window, QColor(background))
    for combo in page.findChildren(AppComboBox):
        for index in range(combo.count()):
            example = SettingExample(
                combo.objectName(), "", "", "", value=str(combo.itemData(index))
            )
            if has_setting_image(example):
                capture = setting_image(example, palette)
                assert not capture.isNull(), (combo.objectName(), example.value)
                if example.key != "languageCombo":
                    assert capture.width() >= 1500


def test_general_previews_follow_palette_but_theme_previews_keep_their_theme(
    page: SettingsPage,
) -> None:
    light = QPalette(page.palette())
    dark = QPalette(page.palette())
    light.setColor(QPalette.ColorRole.Window, QColor("#f2f3f6"))
    dark.setColor(QPalette.ColorRole.Window, QColor("#12171d"))
    general_count = 0
    for combo in page.findChildren(AppComboBox):
        for index in range(combo.count()):
            example = SettingExample(
                combo.objectName(), "", "", "", value=str(combo.itemData(index))
            )
            if not has_setting_image(example) or example.key == "languageCombo":
                continue
            light_image = setting_image(example, light).toImage()
            dark_image = setting_image(example, dark).toImage()
            assert not light_image.isNull() and not dark_image.isNull()
            if example.key in (
                "appearanceModeCombo",
                "lightThemeCombo",
                "darkThemeCombo",
            ):
                assert light_image == dark_image
            else:
                assert light_image != dark_image, (example.key, example.value)
                assert light_image.size() == dark_image.size()
                general_count += 1
    assert general_count == 15


@pytest.mark.parametrize("theme", (*LightTheme, *DarkTheme))
def test_mode_light_and_dark_show_the_selected_theme(
    theme: LightTheme | DarkTheme,
) -> None:
    mode = "light" if isinstance(theme, LightTheme) else "dark"
    example = SettingExample(
        "appearanceModeCombo",
        "",
        "Mode",
        "",
        value=mode,
        light_theme=theme if isinstance(theme, LightTheme) else LightTheme.PORCELAIN,
        dark_theme=theme if isinstance(theme, DarkTheme) else DarkTheme.SLATE,
    )
    expected = setting_image(
        SettingExample(f"{mode}ThemeCombo", "", "", "", value=theme.value),
        APPLICATION.palette(),
    )
    assert has_setting_image(example)
    assert setting_image(example, APPLICATION.palette()).toImage() == expected.toImage()


@pytest.mark.parametrize(
    "light_theme,dark_theme",
    [(LightTheme.PORCELAIN, DarkTheme.SLATE), (LightTheme.SEA_GLASS, DarkTheme.ORCHID)],
)
@pytest.mark.parametrize("dpr", (1.0, 2.0))
def test_auto_composes_selected_themes_along_bottom_left_to_top_right_diagonal(
    light_theme: LightTheme, dark_theme: DarkTheme, dpr: float
) -> None:
    example = SettingExample(
        "appearanceModeCombo",
        "",
        "Mode",
        "",
        value="system",
        light_theme=light_theme,
        dark_theme=dark_theme,
    )
    assert has_setting_image(example)
    combined = setting_image(example, APPLICATION.palette(), dpr).toImage()
    light = setting_image(
        SettingExample("lightThemeCombo", "", "", "", value=light_theme.value),
        APPLICATION.palette(),
        dpr,
    ).toImage()
    dark = setting_image(
        SettingExample("darkThemeCombo", "", "", "", value=dark_theme.value),
        APPLICATION.palette(),
        dpr,
    ).toImage()
    assert combined.size() == light.size() == dark.size()
    assert combined != light and combined != dark
    # Sample on both sides near each end and the middle of the diagonal. Each
    # side retains the source pixels at the same coordinates, without cropping.
    for x_ratio, y_ratio in ((0.1, 0.8), (0.4, 0.4), (0.8, 0.1)):
        x, y = round(combined.width() * x_ratio), round(combined.height() * y_ratio)
        assert combined.copy(x, y, 5, 5) == light.copy(x, y, 5, 5)
        x, y = combined.width() - x, combined.height() - y
        assert combined.copy(x, y, 5, 5) == dark.copy(x, y, 5, 5)


def test_mode_dropdown_uses_saved_themes_without_committing_hovered_mode(
    page: SettingsPage,
) -> None:
    tab = _appearance(page)
    mode = tab.findChild(AppComboBox, "appearanceModeCombo")
    light = tab.findChild(AppComboBox, "lightThemeCombo")
    dark = tab.findChild(AppComboBox, "darkThemeCombo")
    assert mode is not None and light is not None and dark is not None
    light.setCurrentIndex(light.findData(LightTheme.SEA_GLASS.value))
    dark.setCurrentIndex(dark.findData(DarkTheme.ORCHID.value))
    _settle()
    original = mode.currentIndex()
    changes = QSignalSpy(mode.currentIndexChanged)
    mode.showPopup()
    _settle()
    view = mode.view()
    for value in ("dark", "light", "system"):
        index = mode.findData(value)
        QTest.mouseMove(
            view.viewport(), view.visualRect(view.model().index(index, 0)).center()
        )
        _settle()
        shown = _example(tab)
        assert shown is not None and shown.value == value
        assert shown.light_theme is LightTheme.SEA_GLASS
        assert shown.dark_theme is DarkTheme.ORCHID
        assert mode.currentIndex() == original and changes.count() == 0
    mode.hidePopup()


def test_visible_mode_preview_refreshes_when_either_saved_theme_changes(
    page: SettingsPage,
) -> None:
    tab = _appearance(page)
    mode = tab.findChild(AppComboBox, "appearanceModeCombo")
    light = tab.findChild(AppComboBox, "lightThemeCombo")
    dark = tab.findChild(AppComboBox, "darkThemeCombo")
    assert mode is not None and light is not None and dark is not None
    mode.setCurrentIndex(mode.findData("system"))
    row = mode.parentWidget()
    assert isinstance(row, SettingRow)
    _enter(row)
    first = _example(tab)
    assert first is not None
    light.setCurrentIndex(light.findData(LightTheme.DUNE_PLOVER.value))
    _settle()
    second = _example(tab)
    assert second is not None and second.light_theme is LightTheme.DUNE_PLOVER
    dark.setCurrentIndex(dark.findData(DarkTheme.GRAVITY.value))
    _settle()
    third = _example(tab)
    assert third is not None and third.dark_theme is DarkTheme.GRAVITY
    assert third.light_theme is LightTheme.DUNE_PLOVER
    assert (
        setting_image(first, page.palette()).toImage()
        != setting_image(third, page.palette()).toImage()
    )


@pytest.mark.parametrize("dpr", (1.0, 2.0))
def test_all_languages_share_the_language_switcher_svg(dpr: float) -> None:
    images = [
        setting_image(
            SettingExample("languageCombo", "", "Language", "", value=language),
            APPLICATION.palette(),
            dpr,
        )
        for language in ("system", "en", "de", "es", "fr", "ja", "ar")
    ]
    assert not images[0].isNull()
    assert images[0].devicePixelRatioF() == dpr
    assert images[0].width() == round(512 * dpr)
    assert all(image.toImage() == images[0].toImage() for image in images[1:])


def test_hover_delay_keeps_current_image_and_restarts_for_new_targets() -> None:
    parent = QWidget()
    preview = SettingsPreview(parent)
    first = SettingExample("lightThemeCombo", "", "First", "", value="porcelain")
    second = SettingExample("darkThemeCombo", "", "Second", "", value="slate")
    third = SettingExample("lightThemeCombo", "", "Third", "", value="sea-glass")
    preview.set_example(first)
    preview.queue_example(second)
    QTest.qWait(120)
    assert preview.example == first
    preview.queue_example(third)
    QTest.qWait(120)
    assert preview.example == first
    # Repeated events for the same target must not postpone the transition.
    preview.queue_example(third)
    QTest.qWait(110)
    assert preview.example == third
    preview.queue_example(second)
    preview.queue_example(third)
    QTest.qWait(220)
    assert preview.example == third
    preview.queue_example(second)
    preview.clear()
    QTest.qWait(220)
    assert _shown_example(preview) is None
    parent.deleteLater()


def test_hover_delay_survives_previous_fadeout_and_cancels_on_leave() -> None:
    parent = QWidget()
    preview = SettingsPreview(parent)
    first = SettingExample("lightThemeCombo", "", "First", "", value="porcelain")
    second = SettingExample("darkThemeCombo", "", "Second", "", value="slate")
    animation = preview.findChild(QPropertyAnimation)
    assert animation is not None
    preview.set_example(first)
    animation.setCurrentTime(animation.duration())
    preview.queue_example(None)
    preview.queue_example(second)
    animation.setCurrentTime(animation.duration())
    QTest.qWait(220)
    assert preview.example == second
    preview.queue_example(first)
    preview.queue_example(None)
    QTest.qWait(220)
    assert _shown_example(preview) is None
    parent.deleteLater()


def test_replacements_stay_visible_and_appearance_fades_resume_from_current_opacity() -> (
    None
):
    parent = QWidget()
    preview = SettingsPreview(parent)
    animation = preview.findChild(QPropertyAnimation)
    opacity = preview.graphicsEffect()
    assert animation is not None and isinstance(opacity, QGraphicsOpacityEffect)
    first = SettingExample(
        "lightThemeCombo",
        "appearanceSettingsScroll",
        "Light theme",
        "",
        "Porcelain",
        "porcelain",
    )
    second = SettingExample(
        "darkThemeCombo", "appearanceSettingsScroll", "Dark theme", "", "Slate", "slate"
    )
    preview.set_example(first)
    assert opacity.opacity() == 0.0
    animation.setCurrentTime(animation.duration() // 2)
    middle = opacity.opacity()
    assert 0 < middle < 1
    preview.set_example(second)
    assert opacity.opacity() == middle
    assert animation.startValue() == middle
    animation.setCurrentTime(animation.duration())
    assert preview.accessibleName() == "Dark theme"
    assert opacity.opacity() == 1.0
    preview.set_example(first)
    crossfade = preview.findChild(QVariantAnimation, "settingsImageCrossfade")
    assert crossfade is not None
    assert crossfade.state() == QAbstractAnimation.State.Running
    assert animation.state() == QAbstractAnimation.State.Stopped
    for time in (0, crossfade.duration() // 2, crossfade.duration()):
        crossfade.setCurrentTime(time)
        assert opacity.opacity() == 1.0
    preview.set_example(None)
    animation.setCurrentTime(animation.duration() // 2)
    middle = opacity.opacity()
    assert 0 < middle < 1
    preview.set_example(first)
    preview.set_example(second)
    assert opacity.opacity() == middle
    assert animation.startValue() == middle
    animation.setCurrentTime(animation.duration())
    assert preview.accessibleName() == "Dark theme"
    preview.set_example(None)
    assert animation.state() == QAbstractAnimation.State.Running
    animation.setCurrentTime(animation.duration())
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert opacity.opacity() == 0.0 and preview.accessibleName() == ""
    parent.deleteLater()


def test_leaving_row_fades_gradually_and_keeps_image_until_finished(
    page: SettingsPage,
) -> None:
    tab = _appearance(page)
    row = tab.findChildren(SettingRow)[1]
    _enter(row)
    preview = tab.preview
    animation = preview.findChild(QPropertyAnimation)
    image = preview.findChild(SettingsExampleImage)
    opacity = preview.graphicsEffect()
    assert animation is not None and image is not None
    assert isinstance(opacity, QGraphicsOpacityEffect)
    animation.setCurrentTime(animation.duration())
    original = image.frame()
    title = preview.accessibleName()
    APPLICATION.sendEvent(row, QEvent(QEvent.Type.Leave))
    _settle()
    assert preview.example is None
    animation.setCurrentTime(animation.duration() // 3)
    assert 0.65 < opacity.opacity() < 0.85
    assert image.frame() == original and preview.accessibleName() == title
    animation.setCurrentTime(2 * animation.duration() // 3)
    assert 0.20 < opacity.opacity() < 0.35
    assert image.frame() == original and preview.accessibleName() == title
    animation.setCurrentTime(animation.duration())
    assert opacity.opacity() == 0.0 and preview.accessibleName() == ""


def test_image_crossfade_preserves_coverage_and_continues_from_interrupted_frame() -> (
    None
):
    parent = QWidget()
    image = SettingsExampleImage(parent)
    image.resize(200, 200)
    animation = image.findChild(QVariantAnimation, "settingsImageCrossfade")
    assert animation is not None
    red, blue, green = (QPixmap(200, 200) for _ in range(3))
    red.fill(QColor(255, 0, 0))
    blue.fill(QColor(0, 0, 255))
    green.fill(QColor(0, 255, 0))
    image.set_image(red, animate=False)
    start = image.frame()
    image.set_image(blue, animate=True)
    assert image.frame() == start
    animation.setCurrentTime(animation.duration() // 2)
    middle = image.frame()
    pixel = middle.pixelColor(middle.rect().center())
    assert pixel.alpha() >= 254
    assert pixel.red() == pytest.approx(128, abs=2)
    assert pixel.blue() == pytest.approx(128, abs=2)
    assert pixel.green() == 0

    image.set_image(green, animate=True)
    assert image.frame() == middle
    animation.setCurrentTime(animation.duration() // 2)
    interrupted = image.frame()
    pixel = interrupted.pixelColor(interrupted.rect().center())
    assert pixel.alpha() >= 253
    assert pixel.red() == pytest.approx(64, abs=2)
    assert pixel.blue() == pytest.approx(64, abs=2)
    assert pixel.green() == pytest.approx(128, abs=2)
    animation.setCurrentTime(animation.duration())
    final = image.frame()
    assert final.pixelColor(final.rect().center()) == QColor(0, 255, 0)
    assert animation.state() == QAbstractAnimation.State.Stopped
    parent.deleteLater()


@pytest.mark.parametrize("width,height", [(200, 200), (200, 100), (100, 200)])
def test_image_edges_feather_to_background_while_center_stays_opaque(
    width: int, height: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "iOpenPod.GUI.widgets.settings_tab.SETTINGS_VIGNETTE_ENABLED", True
    )
    parent = QWidget()
    image = SettingsExampleImage(parent)
    image.resize(200, 200)
    source = QPixmap(width, height)
    source.fill(QColor(255, 0, 0))
    image.set_image(source, animate=False)
    frame = image.frame()
    dpr = frame.devicePixelRatio()
    left, top = (200 - width) // 2, (200 - height) // 2
    feather = min(width, height) * 0.25
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        alphas: list[int] = []
        for inset in (0.5 / dpr, feather / 2, feather + 1):
            x = left + width / 2 + dx * (width / 2 - inset)
            y = top + height / 2 + dy * (height / 2 - inset)
            alphas.append(frame.pixelColor(int(x * dpr), int(y * dpr)).alpha())
        assert alphas[0] < 15
        assert 80 < alphas[1] < 180
        assert alphas[2] == 255
    assert frame.pixelColor(frame.rect().center()) == QColor(255, 0, 0)
    parent.deleteLater()


def test_vignette_is_disabled_by_default() -> None:
    parent = QWidget()
    image = SettingsExampleImage(parent)
    image.resize(200, 200)
    source = QPixmap(200, 200)
    source.fill(QColor(255, 0, 0))
    image.set_image(source, animate=False)
    frame = image.frame()
    assert frame.pixelColor(0, 0) == QColor(255, 0, 0)
    assert frame.pixelColor(frame.rect().bottomRight()) == QColor(255, 0, 0)
    parent.deleteLater()


def test_crossfade_blends_transparent_margins_of_differently_shaped_images() -> None:
    parent = QWidget()
    image = SettingsExampleImage(parent)
    image.resize(200, 200)
    animation = image.findChild(QVariantAnimation, "settingsImageCrossfade")
    assert animation is not None
    wide, tall = QPixmap(200, 100), QPixmap(100, 200)
    wide.fill(QColor(255, 0, 0))
    tall.fill(QColor(0, 0, 255))
    image.set_image(wide, animate=False)
    image.set_image(tall, animate=True)
    animation.setCurrentTime(animation.duration() // 2)
    frame = image.frame()
    dpr = frame.devicePixelRatio()
    assert frame.pixelColor(round(100 * dpr), round(100 * dpr)).alpha() == 255
    assert frame.pixelColor(round(25 * dpr), round(100 * dpr)).alpha() == pytest.approx(
        128, abs=1
    )
    assert frame.pixelColor(round(100 * dpr), round(25 * dpr)).alpha() == pytest.approx(
        128, abs=1
    )
    assert frame.pixelColor(round(25 * dpr), round(25 * dpr)).alpha() == 0
    animation.setCurrentTime(animation.duration())
    assert image.frame().pixelColor(round(25 * dpr), round(100 * dpr)).alpha() == 0
    parent.deleteLater()


@pytest.mark.parametrize(
    "key,first,second",
    [
        ("navigationStyleCombo", "sidebar", "compact-top-bar"),
        ("ipodLibraryViewModeCombo", "split-table", "itunes-11"),
        ("itunes107ArtworkCombo", "True", "False"),
        ("colorfulModeCombo", "True", "False"),
        ("playerPositionCombo", "top", "bottom"),
        ("playerAutoMinimizeCombo", "True", "False"),
        ("trackTitleBarStyleCombo", "round", "flat"),
        ("lightThemeCombo", "porcelain", "sea-glass"),
    ],
)
def test_examples_visually_distinguish_choices(
    key: str, first: str, second: str
) -> None:
    images = [
        setting_image(
            SettingExample(key, "appearanceSettingsScroll", key, "", value=value),
            APPLICATION.palette(),
        )
        for value in (first, second)
    ]
    assert all(not image.isNull() for image in images)
    assert images[0].toImage() != images[1].toImage()
