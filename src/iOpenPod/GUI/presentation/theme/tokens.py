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


# Original iOpenPod palettes translated to the v2 semantic contract. Interaction
# states and supporting colors are adjusted to retain the shared contrast floors.
CATPPUCCIN_LATTE_TOKENS = ThemeTokens(
    window="#EFF1F5",
    surface="#E7E9EF",
    surface_alt="#CCD0DA",
    surface_hover="#C9CDD7",
    surface_pressed="#C5C9D4",
    surface_selected="#C7D4F0",
    text="#474A63",
    text_secondary="#505368",
    text_disabled="#818592",
    border="#BABECA",
    border_strong="#81848E",
    accent="#1E66F5",
    accent_hover="#1B5CDC",
    accent_pressed="#1852C4",
    accent_ink="#F4F6F8",
    focus="#1E66F5",
    scrollbar="#818592",
    scrollbar_hover="#64677C",
    danger="#D00F38",
    warning="#915C13",
    success="#2F7620",
    artwork_blue="#8CCEEB",
    artwork_green="#A4CCA1",
    artwork_gold="#E4C59B",
    artwork_coral="#F0B494",
    artwork_violet="#C1A3EF",
    artwork_slate="#C3C5D0",
    artwork_ink="#474A63",
)

CATPPUCCIN_FRAPPE_TOKENS = ThemeTokens(
    window="#303446",
    surface="#34384A",
    surface_alt="#414559",
    surface_hover="#44495D",
    surface_pressed="#484D62",
    surface_selected="#424A64",
    text="#C6D0F5",
    text_secondary="#B5BFE2",
    text_disabled="#7D829B",
    border="#4A4F65",
    border_strong="#7D8296",
    accent="#8CAAEE",
    accent_hover="#BABBF1",
    accent_pressed="#819CDA",
    accent_ink="#303345",
    focus="#BABBF1",
    scrollbar="#7D829B",
    scrollbar_hover="#A5ADCE",
    danger="#E88789",
    warning="#E5C890",
    success="#A6D189",
    artwork_blue="#526676",
    artwork_green="#56665D",
    artwork_gold="#69635F",
    artwork_coral="#6C5757",
    artwork_violet="#615779",
    artwork_slate="#42465A",
    artwork_ink="#C6D0F5",
)

CATPPUCCIN_MACCHIATO_TOKENS = ThemeTokens(
    window="#24273A",
    surface="#282B3F",
    surface_alt="#363A4F",
    surface_hover="#3A3E53",
    surface_pressed="#3F4358",
    surface_selected="#38405C",
    text="#CAD3F5",
    text_secondary="#B8C0E0",
    text_disabled="#71768F",
    border="#41455B",
    border_strong="#70758A",
    accent="#8AADF4",
    accent_hover="#B7BDF8",
    accent_pressed="#7E9DDE",
    accent_ink="#24273A",
    focus="#B7BDF8",
    scrollbar="#71768F",
    scrollbar_hover="#A5ADCB",
    danger="#ED8796",
    warning="#EED49F",
    success="#A6DA95",
    artwork_blue="#485F70",
    artwork_green="#4E5F59",
    artwork_gold="#635E5C",
    artwork_coral="#665152",
    artwork_violet="#574E76",
    artwork_slate="#373B50",
    artwork_ink="#CAD3F5",
)

CATPPUCCIN_MOCHA_TOKENS = ThemeTokens(
    window="#1E1E2E",
    surface="#222333",
    surface_alt="#313244",
    surface_hover="#353648",
    surface_pressed="#3A3B4E",
    surface_selected="#323A53",
    text="#CDD6F4",
    text_secondary="#BAC2DE",
    text_disabled="#6C7086",
    border="#3D3E51",
    border_strong="#6A6D80",
    accent="#89B4FA",
    accent_hover="#B4BEFE",
    accent_pressed="#7DA3E2",
    accent_ink="#1E1E2E",
    focus="#B4BEFE",
    scrollbar="#6C7086",
    scrollbar_hover="#A6ADC8",
    danger="#F38BA8",
    warning="#F9E2AF",
    success="#A6E3A1",
    artwork_blue="#415A6A",
    artwork_green="#4A5D54",
    artwork_gold="#625C58",
    artwork_coral="#634E4C",
    artwork_violet="#554A6E",
    artwork_slate="#323445",
    artwork_ink="#CDD6F4",
)

DUNE_PLOVER_TOKENS = ThemeTokens(
    window="#F5EEDC",
    surface="#F7F1E3",
    surface_alt="#DED0B5",
    surface_hover="#DACBAD",
    surface_pressed="#D5C5A4",
    surface_selected="#DBDCCF",
    text="#3D392B",
    text_secondary="#565342",
    text_disabled="#8F876F",
    border="#C2B18E",
    border_strong="#98865F",
    accent="#456D67",
    accent_hover="#3E625D",
    accent_pressed="#375752",
    accent_ink="#F5EEDC",
    focus="#456D67",
    scrollbar="#8F876F",
    scrollbar_hover="#726C58",
    danger="#AA523E",
    warning="#896624",
    success="#52744F",
    artwork_blue="#ADBFC2",
    artwork_green="#B7C3AA",
    artwork_gold="#DAC49A",
    artwork_coral="#E4C09F",
    artwork_violet="#C3BCC7",
    artwork_slate="#CFC4AE",
    artwork_ink="#3D392B",
)

SEA_GLASS_TOKENS = ThemeTokens(
    window="#EDF6F7",
    surface="#E7F1F2",
    surface_alt="#C5DCE0",
    surface_hover="#C0D8DC",
    surface_pressed="#B9D3D7",
    surface_selected="#C6DEE4",
    text="#19363D",
    text_secondary="#31545C",
    text_disabled="#758D91",
    border="#9DBDC2",
    border_strong="#718D93",
    accent="#167C9C",
    accent_hover="#14708C",
    accent_pressed="#12637D",
    accent_ink="#F5FAFA",
    focus="#167C9C",
    scrollbar="#758D91",
    scrollbar_hover="#527178",
    danger="#B54654",
    warning="#96611C",
    success="#27785F",
    artwork_blue="#93C2D1",
    artwork_green="#9BC2B8",
    artwork_gold="#CEBC9E",
    artwork_coral="#D6BBA5",
    artwork_violet="#B9B8DA",
    artwork_slate="#B3C7CA",
    artwork_ink="#19363D",
)

GRAVITY_TOKENS = ThemeTokens(
    window="#030507",
    surface="#0E1D2E",
    surface_alt="#162A3E",
    surface_hover="#192E44",
    surface_pressed="#1C344B",
    surface_selected="#273B4E",
    text="#F2F7FB",
    text_secondary="#C4D6E4",
    text_disabled="#556A7E",
    border="#29465F",
    border_strong="#4C6C87",
    accent="#A9D8F5",
    accent_hover="#E4F4FF",
    accent_pressed="#96C2DD",
    accent_ink="#030507",
    focus="#E4F4FF",
    scrollbar="#556A7E",
    scrollbar_hover="#8EA8BB",
    danger="#E77C86",
    warning="#E1C47A",
    success="#87CDA3",
    artwork_blue="#395268",
    artwork_green="#325251",
    artwork_gold="#4D4F45",
    artwork_coral="#4D4845",
    artwork_violet="#404863",
    artwork_slate="#2D4254",
    artwork_ink="#F2F7FB",
)

NORTHERN_LIGHTS_TOKENS = ThemeTokens(
    window="#0B1726",
    surface="#102439",
    surface_alt="#19334A",
    surface_hover="#1B374D",
    surface_pressed="#1E3C52",
    surface_selected="#21424A",
    text="#E4F3F5",
    text_secondary="#C0DBE0",
    text_disabled="#567785",
    border="#224258",
    border_strong="#4B7388",
    accent="#78E0A4",
    accent_hover="#B0F4C8",
    accent_pressed="#6CC997",
    accent_ink="#0B1726",
    focus="#B0F4C8",
    scrollbar="#567785",
    scrollbar_hover="#91B5BF",
    danger="#F28FAC",
    warning="#F2CF7D",
    success="#78E0A4",
    artwork_blue="#2F5571",
    artwork_green="#2F5C59",
    artwork_gold="#54574D",
    artwork_coral="#53494A",
    artwork_violet="#434871",
    artwork_slate="#2D4759",
    artwork_ink="#E4F3F5",
)

ORCHID_TOKENS = ThemeTokens(
    window="#111018",
    surface="#252231",
    surface_alt="#332D40",
    surface_hover="#373045",
    surface_pressed="#3D334A",
    surface_selected="#3F2E4C",
    text="#F4EDF5",
    text_secondary="#D5C6DA",
    text_disabled="#756A7B",
    border="#4A4055",
    border_strong="#7B6887",
    accent="#C56BD8",
    accent_hover="#EDC6F3",
    accent_pressed="#B262C4",
    accent_ink="#111018",
    focus="#EDC6F3",
    scrollbar="#756A7B",
    scrollbar_hover="#AA9AAE",
    danger="#E18499",
    warning="#D9B56C",
    success="#A8CF9A",
    artwork_blue="#4D5068",
    artwork_green="#4C5650",
    artwork_gold="#5B4E43",
    artwork_coral="#5C4A46",
    artwork_violet="#564665",
    artwork_slate="#483F51",
    artwork_ink="#F4EDF5",
)

_THEME_TOKENS: dict[Theme, ThemeTokens] = {
    LightTheme.PORCELAIN: LIGHT_TOKENS,
    LightTheme.CATPPUCCIN_LATTE: CATPPUCCIN_LATTE_TOKENS,
    LightTheme.DUNE_PLOVER: DUNE_PLOVER_TOKENS,
    LightTheme.SEA_GLASS: SEA_GLASS_TOKENS,
    DarkTheme.SLATE: DARK_TOKENS,
    DarkTheme.ORIGINAL: ORIGINAL_DARK_TOKENS,
    DarkTheme.CATPPUCCIN_FRAPPE: CATPPUCCIN_FRAPPE_TOKENS,
    DarkTheme.CATPPUCCIN_MACCHIATO: CATPPUCCIN_MACCHIATO_TOKENS,
    DarkTheme.CATPPUCCIN_MOCHA: CATPPUCCIN_MOCHA_TOKENS,
    DarkTheme.GRAVITY: GRAVITY_TOKENS,
    DarkTheme.NORTHERN_LIGHTS: NORTHERN_LIGHTS_TOKENS,
    DarkTheme.ORCHID: ORCHID_TOKENS,
}


def tokens_for(theme: Theme) -> ThemeTokens:
    """Return semantic colors for one exact theme selection."""

    try:
        return _THEME_TOKENS[theme]
    except KeyError:
        raise ValueError(f"Unknown theme: {theme!r}") from None


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
