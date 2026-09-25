"""Semantic design tokens for the iOpenPod desktop theme.

The values describe iOpenPod's visual language, not any current page layout. Qt
widgets consume these roles so the application shell can evolve without replacing
the theme system with it.
"""

from dataclasses import dataclass

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo

from iOpenPod.app.core.settings.definitions import DarkTheme, LightTheme

type Theme = LightTheme | DarkTheme


@dataclass(frozen=True, slots=True)
class LayoutTokens:
    """Shared spacing and shape values in Qt device-independent logical pixels."""

    space_3xs: int = 2
    space_2xs: int = 4
    space_xs: int = 8
    space_sm: int = 12
    space_md: int = 16
    space_lg: int = 24
    space_xl: int = 32
    space_2xl: int = 40
    space_3xl: int = 64
    control_height_compact: int = 32
    control_height: int = 36
    control_height_large: int = 44
    minimum_touch_target: int = 44
    checkbox_indicator_size: int = 24
    combo_indicator_width: int = 36
    icon_size: int = 18
    icon_button_size: int = 36
    sidebar_device_image_size: int = 44
    device_picker_image_size: int = 52
    device_picker_row_height: int = 64
    scrollbar_extent: int = 10
    scrollbar_handle_minimum: int = 36
    radius_control: int = 8
    radius_panel: int = 12
    radius_pill: int = 999
    sidebar_width: int = 256
    source_list_width: int = 272
    source_list_minimum_width: int = 176
    source_list_maximum_width: int = 320
    source_list_splitter_handle_width: int = 4
    artwork_source_list_width: int = 280
    collection_list_row_height: int = 60
    player_idle_height: int = 0
    player_height: int = 68
    player_idle_surface_height: int = 0
    player_surface_height: int = 68
    player_surface_maximum_width: int = 1200
    player_artwork_size: int = 48
    player_skip_icon_size: int = 20
    player_play_icon_size: int = 24
    player_volume_minimum_width: int = 64
    player_volume_width: int = 112
    player_transition_ms: int = 220
    playback_pane_width: int = 360
    playback_row_height: int = 64
    playback_row_artwork_size: int = 44
    playback_pane_animation_ms: int = 180
    selection_group_animation_ms: int = 200
    sync_scan_panel_minimum_width: int = 520
    sync_scan_panel_maximum_width: int = 720
    sync_storage_bar_height: int = 10
    sync_review_visible_rows: int = 8
    page_header_height: int = 56
    album_card_padding: int = 6
    album_caption_gap: int = 6
    album_artwork_size: int = 168
    collection_detail_artwork_size: int = 128
    album_card_width: int = 180
    album_card_minimum_height: int = 228
    photo_album_pane_width: int = 220
    photo_album_pane_minimum_width: int = 176
    photo_inspector_width: int = 340
    photo_inspector_minimum_width: int = 280
    photo_inspector_preview_minimum_height: int = 220
    track_list_handle_height: int = 44
    track_table_header_height: int = 40
    track_row_height: int = 36
    track_artwork_size: int = 28
    playlist_banner_minimum_height: int = 152
    playlist_banner_artwork_size: int = 88
    status_popup_width: int = 440
    status_popup_height: int = 300


@dataclass(frozen=True, slots=True)
class TypographyTokens:
    """Installed families and a point-sized scale derived from the system font."""

    body: str
    display: str
    mono: str
    small_pt: float
    body_pt: float
    table_header_pt: float
    album_card_detail_pt: float
    album_card_title_pt: float
    heading_pt: float
    title_pt: float


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    """Opaque semantic colors for one effective theme."""

    window: str
    surface: str
    surface_alt: str
    surface_hover: str
    surface_pressed: str
    surface_selected: str
    text: str
    text_secondary: str
    text_disabled: str
    border: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_ink: str
    focus: str
    scrollbar: str
    scrollbar_hover: str
    danger: str
    warning: str
    success: str
    artwork_blue: str
    artwork_green: str
    artwork_gold: str
    artwork_coral: str
    artwork_violet: str
    artwork_slate: str
    artwork_ink: str


LAYOUT = LayoutTokens()

_MINIMUM_BODY_POINT_SIZE = 10.5
_MINIMUM_SMALL_POINT_SIZE = 9.0
_MINIMUM_TABLE_HEADER_POINT_SIZE = 12.0
_MINIMUM_ALBUM_CARD_DETAIL_POINT_SIZE = 12.0
_MINIMUM_ALBUM_CARD_TITLE_POINT_SIZE = 14.0
_TYPE_SCALE = 1.25
_MONO_FONT_CANDIDATES = (
    "SF Mono",
    "Cascadia Mono",
    "Cascadia Code",
    "Consolas",
    "Noto Sans Mono",
    "DejaVu Sans Mono",
    "Menlo",
)

LIGHT_TOKENS = ThemeTokens(
    window="#F3F5F8",
    surface="#FBFCFE",
    surface_alt="#E9EDF3",
    surface_hover="#F0F3F7",
    surface_pressed="#E1E7EF",
    surface_selected="#DCE9F8",
    text="#20252D",
    text_secondary="#535D6C",
    text_disabled="#788393",
    border="#CDD4DF",
    border_strong="#8591A2",
    accent="#176FD1",
    accent_hover="#0F61BC",
    accent_pressed="#0B53A2",
    accent_ink="#F8FBFF",
    focus="#0B5CAB",
    scrollbar="#7B8797",
    scrollbar_hover="#5D6878",
    danger="#B32937",
    warning="#865300",
    success="#247642",
    artwork_blue="#9CC7EE",
    artwork_green="#9FCAB3",
    artwork_gold="#DDC37D",
    artwork_coral="#DEA39C",
    artwork_violet="#B9ACD8",
    artwork_slate="#9BAABA",
    artwork_ink="#34485D",
)

DARK_TOKENS = ThemeTokens(
    window="#12171D",
    surface="#1B2129",
    surface_alt="#252D38",
    surface_hover="#2B3541",
    surface_pressed="#343F4D",
    surface_selected="#203B59",
    text="#EFF3F8",
    text_secondary="#B5BECA",
    text_disabled="#7F8A99",
    border="#374351",
    border_strong="#606D7E",
    accent="#69A9F2",
    accent_hover="#82BAF5",
    accent_pressed="#4A92E3",
    accent_ink="#0C2238",
    focus="#8FC7FF",
    scrollbar="#667386",
    scrollbar_hover="#8B97A8",
    danger="#FF8790",
    warning="#F0B45F",
    success="#72CE8C",
    artwork_blue="#315B83",
    artwork_green="#35654E",
    artwork_gold="#75622F",
    artwork_coral="#744944",
    artwork_violet="#584B78",
    artwork_slate="#415166",
    artwork_ink="#D7E6F5",
)

ORIGINAL_DARK_TOKENS = ThemeTokens(
    window="#1A1A2E",
    surface="#212135",
    surface_alt="#252538",
    surface_hover="#303042",
    surface_pressed="#39394B",
    surface_selected="#34344A",
    text="#E9E9EB",
    text_secondary="#B2B2BA",
    text_disabled="#8A8A96",
    border="#353546",
    border_strong="#6B6B7E",
    accent="#409CFF",
    accent_hover="#60B0FF",
    accent_pressed="#2189E9",
    accent_ink="#101C2A",
    focus="#74C0FC",
    scrollbar="#747486",
    scrollbar_hover="#A1A1AD",
    danger="#FF7B7B",
    warning="#FCCF52",
    success="#67D879",
    artwork_blue="#355F8A",
    artwork_green="#386A52",
    artwork_gold="#7A6630",
    artwork_coral="#7A4D48",
    artwork_violet="#5D507F",
    artwork_slate="#46566C",
    artwork_ink="#DFE8F3",
)


def tokens_for(theme: Theme) -> ThemeTokens:
    """Return semantic colors for one exact theme selection."""

    if theme is LightTheme.PORCELAIN:
        return LIGHT_TOKENS
    if theme is DarkTheme.SLATE:
        return DARK_TOKENS
    if theme is DarkTheme.ORIGINAL:
        return ORIGINAL_DARK_TOKENS
    raise ValueError(f"Unknown theme: {theme!r}")


def resolve_typography() -> TypographyTokens:
    """Resolve semantic type roles from native, positive point-sized fonts."""

    available = {family.casefold(): family for family in QFontDatabase.families()}
    system_body_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    system_display_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.TitleFont)
    system_mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    body_point_size = max(
        _resolved_point_size(system_body_font),
        _MINIMUM_BODY_POINT_SIZE,
    )
    return TypographyTokens(
        body=system_body_font.family(),
        display=system_display_font.family() or system_body_font.family(),
        mono=_first_available(
            _MONO_FONT_CANDIDATES,
            available,
            system_mono_font.family(),
        ),
        small_pt=max(
            _scaled_point_size(body_point_size, -1),
            _MINIMUM_SMALL_POINT_SIZE,
        ),
        body_pt=body_point_size,
        table_header_pt=max(
            body_point_size,
            _MINIMUM_TABLE_HEADER_POINT_SIZE,
        ),
        album_card_detail_pt=max(
            body_point_size,
            _MINIMUM_ALBUM_CARD_DETAIL_POINT_SIZE,
        ),
        album_card_title_pt=max(
            _scaled_point_size(body_point_size, 1),
            _MINIMUM_ALBUM_CARD_TITLE_POINT_SIZE,
        ),
        heading_pt=_scaled_point_size(body_point_size, 1),
        title_pt=_scaled_point_size(body_point_size, 2),
    )


def _resolved_point_size(font: QFont) -> float:
    requested_size = font.pointSizeF()
    if requested_size > 0:
        return float(requested_size)

    effective_size = QFontInfo(font).pointSizeF()
    if effective_size > 0:
        return float(effective_size)
    return _MINIMUM_BODY_POINT_SIZE


def _scaled_point_size(base_size: float, steps: int) -> float:
    return round(base_size * (_TYPE_SCALE**steps), 2)


def _first_available(
    candidates: tuple[str, ...],
    available: dict[str, str],
    fallback: str,
) -> str:
    return next(
        (
            available[candidate.casefold()]
            for candidate in candidates
            if candidate.casefold() in available
        ),
        fallback,
    )
