"""Resolve authored theme palettes into documented application paints.

Theme files are deliberately limited to opaque color foundations. This module
is the single seam that defines every application-owned derivation: its source
roles, fixed alpha, and (where applicable) the backdrop it must be composed on.
It is pure Python so visual behavior can be tested without Qt.
"""

from __future__ import annotations

import colorsys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

PaintKind = Literal["opaque", "layer"]


class ThemeInput(Protocol):
    """The catalog data required to render a theme without importing it."""

    @property
    def type(self) -> Literal["light", "dark"]: ...

    @property
    def colors(self) -> Mapping[str, str]: ...

    @property
    def high_contrast(self) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class Color:
    """An sRGB color with an explicit alpha channel owned by the application."""

    red: int
    green: int
    blue: int
    alpha: int = 255

    def __post_init__(self) -> None:
        if any(channel not in range(256) for channel in (self.red, self.green, self.blue, self.alpha)):
            raise ValueError("Color channels must be between 0 and 255")

    @classmethod
    def from_hex(cls, value: str) -> Color:
        """Create an opaque color from a validated ``#RGB`` or ``#RRGGBB`` value."""

        normalized = value.strip().lower()
        if len(normalized) == 4 and normalized.startswith("#"):
            normalized = "#" + "".join(channel * 2 for channel in normalized[1:])
        if len(normalized) != 7 or not normalized.startswith("#"):
            raise ValueError(f"Not a hex color: {value!r}")
        try:
            return cls(*(int(normalized[index : index + 2], 16) for index in (1, 3, 5)))
        except ValueError as exc:
            raise ValueError(f"Not a hex color: {value!r}") from exc

    @classmethod
    def try_from_hex(cls, value: str) -> Color | None:
        """Parse a hex color or return ``None`` for a non-color preference."""

        try:
            return cls.from_hex(value)
        except ValueError:
            return None

    @property
    def rgb(self) -> tuple[int, int, int]:
        return self.red, self.green, self.blue

    @property
    def css(self) -> str:
        """Render the color for Qt stylesheets without leaking this internally."""

        if self.alpha == 255:
            return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"
        return f"rgba({self.red},{self.green},{self.blue},{self.alpha})"

    def with_alpha(self, alpha: int) -> Color:
        return Color(self.red, self.green, self.blue, alpha)

    def composite_over(self, backdrop: Color) -> Color:
        """Return this color composited over ``backdrop`` using source-over alpha."""

        source_alpha = self.alpha / 255
        backdrop_alpha = backdrop.alpha / 255
        output_alpha = source_alpha + (backdrop_alpha * (1.0 - source_alpha))
        if output_alpha == 0:
            return Color(0, 0, 0, 0)

        def compose(source: int, destination: int) -> int:
            value = ((source * source_alpha) + (destination * backdrop_alpha * (1.0 - source_alpha))) / output_alpha
            return _clamp_byte(value)

        return Color(
            compose(self.red, backdrop.red),
            compose(self.green, backdrop.green),
            compose(self.blue, backdrop.blue),
            _clamp_byte(output_alpha * 255),
        )

    def scaled(self, red_scale: float, green_scale: float, blue_scale: float) -> Color:
        """Scale channels while preserving opacity."""

        return Color(
            _clamp_byte(self.red * red_scale),
            _clamp_byte(self.green * green_scale),
            _clamp_byte(self.blue * blue_scale),
            self.alpha,
        )

    def lighten_toward_white(self, amount: float) -> Color:
        """Return a deterministic lighter variant for a custom accent."""

        amount = max(0.0, min(1.0, amount))
        return Color(
            int(self.red + ((255 - self.red) * amount)),
            int(self.green + ((255 - self.green) * amount)),
            int(self.blue + ((255 - self.blue) * amount)),
            self.alpha,
        )

    def mixed_with(self, other: Color, amount: float) -> Color:
        """Mix two opaque paints for a renderer-owned component recipe."""

        amount = max(0.0, min(1.0, amount))
        remaining = 1.0 - amount
        return Color(
            _clamp_byte((self.red * remaining) + (other.red * amount)),
            _clamp_byte((self.green * remaining) + (other.green * amount)),
            _clamp_byte((self.blue * remaining) + (other.blue * amount)),
            _clamp_byte((self.alpha * remaining) + (other.alpha * amount)),
        )

    def relative_luminance(self) -> float:
        def linear(channel: int) -> float:
            normalized = channel / 255
            return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

        return (0.2126 * linear(self.red)) + (0.7152 * linear(self.green)) + (0.0722 * linear(self.blue))

    def contrast_ratio(self, other: Color) -> float:
        lighter = max(self.relative_luminance(), other.relative_luminance())
        darker = min(self.relative_luminance(), other.relative_luminance())
        return (lighter + 0.05) / (darker + 0.05)

    def normalized_for_contrast(self, backdrop: Color, target_ratio: float) -> Color:
        """Preserve hue while finding the closest lightness at ``target_ratio``."""

        target_ratio = max(1.0, float(target_ratio))
        hue, lightness, saturation = colorsys.rgb_to_hls(
            self.red / 255.0,
            self.green / 255.0,
            self.blue / 255.0,
        )
        best = self
        best_score = (float("inf"), float("inf"))
        for step in range(256):
            candidate_lightness = step / 255.0
            red, green, blue = colorsys.hls_to_rgb(hue, candidate_lightness, saturation)
            candidate = Color(_clamp_byte(red * 255), _clamp_byte(green * 255), _clamp_byte(blue * 255))
            score = (abs(candidate.contrast_ratio(backdrop) - target_ratio), abs(candidate_lightness - lightness))
            if score < best_score:
                best = candidate
                best_score = score
        return best


@dataclass(frozen=True)
class Paint:
    """One resolved application paint and the recipe that produced it."""

    name: str
    color: Color
    kind: PaintKind
    recipe: str
    source_roles: tuple[str, ...]
    backdrop_role: str | None = None

    @property
    def css(self) -> str:
        return self.color.css

    @property
    def is_opaque(self) -> bool:
        return self.color.alpha == 255


@dataclass(frozen=True)
class ResolvedTheme:
    """The Theme Renderer output consumed by GUI adapters.

    ``paint()`` exposes derivation provenance for tests and GUI consumers.
    """

    theme_id: str
    is_dark: bool
    high_contrast: bool
    paints: Mapping[str, Paint]

    def paint(self, name: str) -> Paint:
        return self.paints[name]

    def composite(self, layer_name: str, backdrop_name: str | None = None) -> Paint:
        """Compose a layer over its declared or an explicit opaque backdrop."""

        layer = self.paint(layer_name)
        if layer.kind != "layer":
            raise ValueError(f"{layer_name} is already an opaque paint")
        target_backdrop = backdrop_name or layer.backdrop_role
        if target_backdrop is None:
            raise ValueError(f"{layer_name} requires an explicit backdrop")
        backdrop = self.paint(target_backdrop)
        if not backdrop.is_opaque:
            raise ValueError(f"{target_backdrop} is not an opaque backdrop")
        return Paint(
            name=f"{layer_name}_ON_{target_backdrop}",
            color=layer.color.composite_over(backdrop.color),
            kind="opaque",
            recipe=f"{layer_name} composited over {target_backdrop}",
            source_roles=layer.source_roles + backdrop.source_roles,
            backdrop_role=target_backdrop,
        )


@dataclass(frozen=True)
class ArtworkGridCardPaints:
    """Final opaque card paints derived from a piece of artwork."""

    normal_fill: Paint
    hover_fill: Paint


def render_artwork_grid_card_paints(
    theme: ResolvedTheme,
    artwork_rgb: tuple[int, int, int],
) -> ArtworkGridCardPaints:
    """Resolve a dynamic artwork tint into the grid card's opaque states.

    Artwork supplies its RGB value, while the application owns the state
    opacity and the card-surface backdrop. This keeps the result consistent
    for every theme and prevents widgets from inventing their own alpha rules.
    """

    backdrop = theme.paint("grid.card.fill")
    artwork = Color(*artwork_rgb)
    normal_alpha, hover_alpha = (30, 55) if theme.is_dark else (48, 82)
    source_roles = ("artwork_dominant_color",) + backdrop.source_roles
    return ArtworkGridCardPaints(
        normal_fill=Paint(
            "grid.card.artwork_fill",
            artwork.with_alpha(normal_alpha).composite_over(backdrop.color),
            "opaque",
            "artwork grid card tint",
            source_roles,
            "grid.card.fill",
        ),
        hover_fill=Paint(
            "grid.card.artwork_hover_fill",
            artwork.with_alpha(hover_alpha).composite_over(backdrop.color),
            "opaque",
            "artwork grid card hover tint",
            source_roles,
            "grid.card.fill",
        ),
    )


@dataclass(frozen=True)
class ContentHeroPaints:
    """Transparent effect layers for an artwork-tinted content hero."""

    header_tint: Paint
    header_border: Paint
    art_fill: Paint
    art_border: Paint
    action_fill: Paint
    action_hover: Paint
    action_pressed: Paint
    action_border: Paint


def render_content_hero_paints(
    theme: ResolvedTheme,
    artwork_rgb: tuple[int, int, int],
) -> ContentHeroPaints:
    """Resolve the shared artwork-driven hero effects used by content browsers.

    These layers are intentionally transparent because they are drawn over a
    dynamic artwork-gradient header. The fixed alpha values belong to the
    renderer, never to a theme file or individual widget stylesheet.
    """

    artwork = Color(*artwork_rgb)
    artwork_sources = ("artwork_dominant_color",)
    glass = Color(255, 255, 255) if theme.is_dark else Color(0, 0, 0)
    return ContentHeroPaints(
        header_tint=Paint(
            "effect.content_hero.header_tint",
            artwork.with_alpha(80),
            "layer",
            "content hero artwork tint",
            artwork_sources,
        ),
        header_border=Paint(
            "effect.content_hero.header_border",
            artwork.with_alpha(40),
            "layer",
            "content hero artwork border",
            artwork_sources,
        ),
        art_fill=Paint(
            "effect.content_hero.art_fill",
            artwork.with_alpha(30),
            "layer",
            "content hero artwork inset",
            artwork_sources,
        ),
        art_border=Paint(
            "effect.content_hero.art_border",
            artwork.with_alpha(50),
            "layer",
            "content hero artwork inset border",
            artwork_sources,
        ),
        action_fill=Paint(
            "effect.content_hero.action_fill",
            glass.with_alpha(18 if theme.is_dark else 20),
            "layer",
            "content hero action fill",
            ("app_white" if theme.is_dark else "app_black",),
        ),
        action_hover=Paint(
            "effect.content_hero.action_hover",
            glass.with_alpha(35 if theme.is_dark else 28),
            "layer",
            "content hero action hover",
            ("app_white" if theme.is_dark else "app_black",),
        ),
        action_pressed=Paint(
            "effect.content_hero.action_pressed",
            glass.with_alpha(12 if theme.is_dark else 14),
            "layer",
            "content hero action pressed",
            ("app_white" if theme.is_dark else "app_black",),
        ),
        action_border=Paint(
            "effect.content_hero.action_border",
            glass.with_alpha(15 if theme.is_dark else 24),
            "layer",
            "content hero action border",
            ("app_white" if theme.is_dark else "app_black",),
        ),
    )


@dataclass(frozen=True)
class TrackTitleBarPaints:
    """Resolved paints for a dynamically colored track-list title bar."""

    gradient_top: Paint
    gradient_middle: Paint | None
    gradient_bottom: Paint
    border: Paint | None
    title_text: Paint
    secondary_text: Paint
    icon_text: Paint
    button_fill: Paint
    button_hover: Paint
    button_pressed: Paint
    search_fill: Paint
    search_border: Paint
    search_text: Paint
    search_placeholder: Paint
    search_focus_fill: Paint
    search_focus_border: Paint
    search_focus_text: Paint


def render_track_title_bar_paints(
    theme: ResolvedTheme,
    base_rgb: tuple[int, int, int],
    *,
    text_rgb: tuple[int, int, int] | None = None,
    text_secondary_rgb: tuple[int, int, int] | None = None,
    contrast_ensured: bool = False,
) -> TrackTitleBarPaints:
    """Resolve the dynamic title-bar palette used by playlist and album views.

    Playlist colors and artwork supply RGB values only. All color mixing,
    contrast policy, gradients, and alpha stay in the renderer so every theme
    receives the same title-bar behaviour.
    """

    white = Color(255, 255, 255)
    black = Color(0, 0, 0)
    near_black = Color(18, 18, 24)
    base = Color(*base_rgb)
    dynamic_sources = ("artwork_dominant_color",) if contrast_ensured else ("content_accent",)

    if contrast_ensured:
        background = base
        title = theme.paint("text.primary").color
        secondary = theme.paint("text.secondary").color
        top_mix, bottom_mix = ((0.14, 0.24) if theme.is_dark else (0.08, 0.22))
        top_alpha, middle_alpha, bottom_alpha = ((92, 70, 60) if theme.is_dark else (132, 112, 96))
        top = background.mixed_with(white, top_mix)
        bottom = background.mixed_with(black, bottom_mix)
        gradient_top = _dynamic_layer("gradient_top", top, top_alpha, "title bar artwork gradient top", dynamic_sources)
        gradient_middle = _dynamic_layer("gradient_middle", background, middle_alpha, "title bar artwork gradient middle", dynamic_sources)
        gradient_bottom = _dynamic_layer("gradient_bottom", bottom, bottom_alpha, "title bar artwork gradient bottom", dynamic_sources)
        border = None
    else:
        background = base.normalized_for_contrast(
            theme.paint("canvas.default").color,
            4.5 if theme.high_contrast else 2.95,
        )
        title = Color(*text_rgb) if text_rgb is not None else _text_for_dynamic_background(background, white, near_black)
        secondary = Color(*text_secondary_rgb) if text_secondary_rgb is not None else title.mixed_with(background, 0.3)
        top = background.mixed_with(white, 0.08)
        bottom = background.mixed_with(black, 0.16)
        gradient_top = _dynamic_layer("gradient_top", top, 190, "title bar accent gradient top", dynamic_sources)
        gradient_middle = None
        gradient_bottom = _dynamic_layer("gradient_bottom", bottom, 178, "title bar accent gradient bottom", dynamic_sources)
        border_color = background.mixed_with(black, 0.28)
        border = _dynamic_layer("border", border_color, 130, "title bar accent border", dynamic_sources)

    title_paint = Paint("track.title.text", title, "opaque", "title bar primary text", ("dynamic_title_text",))
    icon_text = Paint("track.title.icon_text", secondary, "opaque", "title bar icon text", ("dynamic_title_secondary_text",))
    return TrackTitleBarPaints(
        gradient_top=gradient_top,
        gradient_middle=gradient_middle,
        gradient_bottom=gradient_bottom,
        border=border,
        title_text=title_paint,
        secondary_text=_dynamic_layer("secondary_text", secondary, 205, "title bar secondary text", icon_text.source_roles),
        icon_text=icon_text,
        button_fill=_dynamic_layer("button_fill", title, 18, "title bar button fill", title_paint.source_roles),
        button_hover=_dynamic_layer("button_hover", title, 30, "title bar button hover", title_paint.source_roles),
        button_pressed=_dynamic_layer("button_pressed", title, 24, "title bar button pressed", title_paint.source_roles),
        search_fill=_dynamic_layer("search_fill", title, 20, "title bar search fill", title_paint.source_roles),
        search_border=_dynamic_layer("search_border", title, 42, "title bar search border", title_paint.source_roles),
        search_text=Paint("track.title.search_text", secondary, "opaque", "title bar search text", icon_text.source_roles),
        search_placeholder=_dynamic_layer("search_placeholder", secondary, 220, "title bar search placeholder", icon_text.source_roles),
        search_focus_fill=_dynamic_layer("search_focus_fill", title, 32, "title bar focused search fill", title_paint.source_roles),
        search_focus_border=_dynamic_layer("search_focus_border", title, 88, "title bar focused search border", title_paint.source_roles),
        search_focus_text=title_paint,
    )


def _dynamic_layer(
    name: str,
    color: Color,
    alpha: int,
    recipe: str,
    source_roles: tuple[str, ...],
) -> Paint:
    return Paint(f"effect.track_title.{name}", color.with_alpha(alpha), "layer", recipe, source_roles)


def _text_for_dynamic_background(background: Color, white: Color, near_black: Color) -> Color:
    return white if white.contrast_ratio(background) >= near_black.contrast_ratio(background) else near_black


_DIRECT_PAINTS = {
    "BG_DARK": "background",
    "BG_MID": "background_alt",
    "SURFACE": "surface",
    "SURFACE_ALT": "surface_alt",
    "SURFACE_RAISED": "surface_raised",
    "SURFACE_HOVER": "surface_hover",
    "SURFACE_ACTIVE": "surface_active",
    "MENU_BG": "menu_background",
    "TEXT_PRIMARY": "text_primary",
    "TEXT_SECONDARY": "text_secondary",
    "TEXT_TERTIARY": "text_tertiary",
    "TEXT_DISABLED": "text_disabled",
    "BORDER": "border",
    "BORDER_SUBTLE": "border_subtle",
    "DIALOG_BG": "dialog_background",
    "TOOLTIP_BG": "tooltip_background",
    "DROPDOWN_BG": "menu_background",
    "GRIDLINE": "gridline",
    "STAR": "star",
    "DANGER": "danger",
    "SUCCESS": "success",
    "WARNING": "warning",
    "INFO": "info",
    "SYNC_CYAN": "sync_cyan",
    "SYNC_PURPLE": "sync_purple",
    "SYNC_MAGENTA": "sync_magenta",
    "SYNC_ORANGE": "sync_orange",
    "SYNC_FREED": "sync_freed",
    "PLAYLIST_SMART": "playlist_smart",
    "PLAYLIST_PODCAST": "playlist_podcast",
    "PLAYLIST_MASTER": "playlist_master",
    "PLAYLIST_REGULAR": "playlist_regular",
}
def render_theme(
    theme: ThemeInput,
    *,
    high_contrast: bool = False,
    accent_override: Color | None = None,
    accent_contrast_target: float = 3.35,
) -> ResolvedTheme:
    """Resolve a theme and preferences into named paints with provenance."""

    semantic = _resolved_semantic_colors(theme, high_contrast=high_contrast)
    is_dark = theme.type == "dark"
    paints: dict[str, Paint] = {
        token: _authored_paint(token, source_role, semantic)
        for token, source_role in _DIRECT_PAINTS.items()
    }

    background = paints["BG_DARK"].color
    accent = Color.from_hex(semantic["accent"])
    accent_light = Color.from_hex(semantic["accent_light"])
    if accent_override is not None:
        accent = accent_override.normalized_for_contrast(background, 4.5 if high_contrast else accent_contrast_target)
        accent_light = accent.lighten_toward_white(0.25)
        paints["PLAYLIST_REGULAR"] = Paint(
            name="PLAYLIST_REGULAR",
            color=accent,
            kind="opaque",
            recipe="custom accent",
            source_roles=("custom_accent",),
        )
    elif high_contrast:
        accent = accent.normalized_for_contrast(background, 4.5)
        accent_light = accent.lighten_toward_white(0.25)

    paints["ACCENT"] = Paint("ACCENT", accent, "opaque", "authored accent" if accent_override is None else "normalized custom accent", ("accent" if accent_override is None else "custom_accent",))
    paints["ACCENT_LIGHT"] = Paint("ACCENT_LIGHT", accent_light, "opaque", "authored accent light" if accent_override is None else "custom accent light", ("accent_light" if accent_override is None else "custom_accent",))
    _add_accent_paints(paints, accent, is_dark, high_contrast)
    _add_status_paints(paints, "DANGER", is_dark, high_contrast)
    _add_status_paints(paints, "SUCCESS", is_dark, high_contrast)
    _add_status_paints(paints, "WARNING", is_dark, high_contrast)
    _add_status_paints(paints, "INFO", is_dark, high_contrast)
    _add_effect_paints(paints, semantic, is_dark)
    _add_text_on_accent(paints, semantic, is_dark)
    _add_application_paints(paints, is_dark=is_dark)

    return ResolvedTheme(
        theme_id=getattr(theme, "id", "custom"),
        is_dark=is_dark,
        high_contrast=high_contrast,
        paints=paints,
    )


def _authored_paint(token: str, source_role: str, semantic: Mapping[str, str]) -> Paint:
    return Paint(token, Color.from_hex(semantic[source_role]), "opaque", "authored opaque role", (source_role,))


def _add_accent_paints(paints: dict[str, Paint], accent: Color, is_dark: bool, high_contrast: bool) -> None:
    dim, hover, press, border, muted, solid, solid_press, focus, selection = (80, 120, 60, 100, 35, 200, 160, 150, 90) if is_dark else (60, 100, 45, 80, 18, 180, 140, 130, 70)
    dark = accent.scaled(0.62, 0.64, 0.78)
    _add_layer(paints, "ACCENT_DIM", accent, dim, "accent subtle fill", backdrop_role="SURFACE")
    _add_layer(paints, "ACCENT_HOVER", accent, hover, "accent hover layer", backdrop_role="SURFACE_RAISED")
    _add_layer(paints, "ACCENT_PRESS", accent, press, "accent press layer", backdrop_role="SURFACE_RAISED")
    _add_layer(paints, "ACCENT_BORDER", accent, border, "accent border layer", backdrop_role="SURFACE_ALT")
    _add_layer(paints, "ACCENT_MUTED", accent, muted, "accent muted fill", backdrop_role="SURFACE")
    _add_layer(paints, "ACCENT_SOLID", accent, solid, "accent strong fill", backdrop_role="SURFACE_RAISED")
    _add_layer(paints, "ACCENT_SOLID_PRESS", accent, solid_press, "accent strong press fill", backdrop_role="SURFACE_RAISED")
    _add_layer(paints, "ACCENT_DARK", dark, border, "darkened accent layer", ("accent",), "BG_DARK")
    _add_layer(paints, "ACCENT_DARK_DIM", dark, 60 if is_dark else 40, "darkened accent subtle layer", ("accent",), "BG_DARK")
    _add_layer(paints, "BORDER_FOCUS", accent, 220 if high_contrast else focus, "accent focus ring", backdrop_role="SURFACE_ALT")
    _add_layer(paints, "SELECTION", accent, selection, "accent selection layer", backdrop_role="SURFACE")


def _add_status_paints(paints: dict[str, Paint], status: str, is_dark: bool, high_contrast: bool) -> None:
    color = paints[status].color
    if status == "DANGER":
        dim, hover, border = (30, 50, 120 if high_contrast else 80) if is_dark else (20, 35, 120 if high_contrast else 60)
    else:
        dim, hover, border = (40, 60, 120 if high_contrast else 80) if is_dark else (25, 40, 120 if high_contrast else 60)
    _add_layer(paints, f"{status}_DIM", color, dim, f"{status.lower()} subtle fill", (status.lower(),), "SURFACE")
    _add_layer(paints, f"{status}_HOVER", color, hover, f"{status.lower()} hover layer", (status.lower(),), "SURFACE_RAISED")
    _add_layer(paints, f"{status}_BORDER", color, border, f"{status.lower()} border layer", (status.lower(),), "SURFACE_ALT")


def _add_effect_paints(paints: dict[str, Paint], semantic: Mapping[str, str], is_dark: bool) -> None:
    _add_layer(paints, "OVERLAY", Color.from_hex(semantic["background"]), 220 if is_dark else 230, "modal scrim", ("background",))
    accent = paints["ACCENT"].color
    _add_layer(paints, "DROP_TARGET_SCRIM", Color.from_hex(semantic["background"]), 220 if is_dark else 230, "drop target scrim", ("background",))
    _add_layer(paints, "DROP_TARGET_TINT", accent, 18, "drop target interior tint", ("accent",))
    _add_layer(paints, "DROP_TARGET_BORDER", accent, 100, "drop target dashed border", ("accent",))
    shadow = Color(0, 0, 0)
    light, normal, deep = (25, 40, 60) if is_dark else (14, 22, 32)
    _add_layer(paints, "SHADOW_LIGHT", shadow, light, "elevation light shadow", ())
    _add_layer(paints, "SHADOW", shadow, normal, "elevation shadow", ())
    _add_layer(paints, "SHADOW_DEEP", shadow, deep, "elevation deep shadow", ())

    text_primary = paints["TEXT_PRIMARY"]
    scrollbar_alphas = (70, 110, 140) if is_dark else (55, 90, 120)
    for name, alpha, recipe in zip(
        ("SCROLLBAR_THUMB", "SCROLLBAR_THUMB_HOVER", "SCROLLBAR_THUMB_PRESS"),
        scrollbar_alphas,
        ("scrollbar thumb", "scrollbar hovered thumb", "scrollbar pressed thumb"),
        strict=True,
    ):
        _add_layer(
            paints,
            name,
            text_primary.color,
            alpha,
            recipe,
            text_primary.source_roles,
        )

    _add_layer(
        paints,
        "ARTWORK_CROP_MASK",
        Color(0, 0, 0),
        150,
        "artwork crop outside mask",
        ("app_black",),
    )
    _add_layer(
        paints,
        "ARTWORK_CROP_GRID",
        text_primary.color,
        95,
        "artwork crop guide grid",
        text_primary.source_roles,
    )
    _add_layer(
        paints,
        "ARTWORK_CROP_BORDER",
        text_primary.color,
        235,
        "artwork crop boundary",
        text_primary.source_roles,
    )


def _add_text_on_accent(paints: dict[str, Paint], semantic: Mapping[str, str], is_dark: bool) -> None:
    accent = paints["ACCENT"].color
    text = Color(255, 255, 255) if accent.relative_luminance() < 0.34 else Color.from_hex(semantic["background"] if is_dark else "#000000")
    paints["TEXT_ON_ACCENT"] = Paint(
        "TEXT_ON_ACCENT",
        text,
        "opaque",
        "contrast text for accent",
        ("accent", "background") if is_dark else ("accent",),
    )


def _add_text_on_fill(paints: dict[str, Paint], name: str, fill_name: str) -> None:
    """Choose guaranteed readable app-owned text for one opaque status fill."""

    fill = paints[fill_name]
    text = Color(255, 255, 255) if fill.color.relative_luminance() < 0.34 else Color(0, 0, 0)
    paints[name] = Paint(
        name,
        text,
        "opaque",
        f"contrast text for {fill_name.lower()} fill",
        fill.source_roles,
    )


def _add_application_paints(paints: dict[str, Paint], *, is_dark: bool) -> None:
    """Expose the renderer's stable application vocabulary.

    These are the paints new widgets should request. They are either authored
    opaque foundations or final opaque compositions; the old uppercase tokens
    remain separate compatibility inputs for existing widgets.
    """

    for name, source in {
        "canvas.default": "BG_DARK",
        "canvas.inset": "BG_MID",
        "surface.default": "SURFACE",
        "surface.inset": "SURFACE_ALT",
        "surface.raised": "SURFACE_RAISED",
        "surface.hover": "SURFACE_HOVER",
        "surface.active": "SURFACE_ACTIVE",
        "text.primary": "TEXT_PRIMARY",
        "text.secondary": "TEXT_SECONDARY",
        "text.tertiary": "TEXT_TERTIARY",
        "text.disabled": "TEXT_DISABLED",
        "border.default": "BORDER",
        "border.subtle": "BORDER_SUBTLE",
        "border.grid": "GRIDLINE",
        "control.primary.fill": "ACCENT",
        "control.primary.hover_fill": "ACCENT_LIGHT",
        "control.primary.text": "TEXT_ON_ACCENT",
        "control.secondary.fill": "SURFACE_RAISED",
        "control.secondary.pressed_fill": "SURFACE_ACTIVE",
        "control.quiet.pressed_fill": "SURFACE_ACTIVE",
        "status.danger.text": "DANGER",
        "status.success.text": "SUCCESS",
        "status.warning.text": "WARNING",
        "status.info.text": "INFO",
        "sync.change.add.text": "SUCCESS",
        "sync.change.remove.text": "DANGER",
        "sync.change.file.text": "SYNC_CYAN",
        "sync.change.metadata.text": "SYNC_PURPLE",
        "sync.change.artwork.text": "SYNC_MAGENTA",
        "sync.change.play_count.text": "INFO",
        "sync.change.rating.text": "WARNING",
        "sync.storage.current_fill": "ACCENT",
        "sync.storage.add_fill": "SUCCESS",
        "sync.storage.overflow_fill": "SYNC_ORANGE",
        "sync.storage.freed_fill": "SYNC_CYAN",
        "sync.storage.exceeded_fill": "DANGER",
        "playlist.smart": "PLAYLIST_SMART",
        "playlist.podcast": "PLAYLIST_PODCAST",
        "playlist.master": "PLAYLIST_MASTER",
        "playlist.regular": "PLAYLIST_REGULAR",
        "modal.background": "DIALOG_BG",
        "menu.background": "MENU_BG",
        "tooltip.background": "TOOLTIP_BG",
    }.items():
        _add_opaque_alias(paints, name, source)

    _add_composed_paint(paints, "control.primary.pressed_fill", "ACCENT_DARK", "ACCENT")
    _add_mixed_paint(
        paints,
        "chrome.sidebar.fill",
        "SURFACE",
        "SURFACE_RAISED",
        0.30,
        "elevated sidebar chrome",
    )
    _add_mixed_paint(
        paints,
        "control.secondary.hover_fill",
        "SURFACE_HOVER",
        "SURFACE_ACTIVE",
        0.50,
        "secondary control hover blend",
    )
    _add_opaque_alias(paints, "control.quiet.hover_fill", "control.secondary.hover_fill")
    _add_composed_paint(paints, "control.toggle.selected_fill", "ACCENT_DIM", "SURFACE_RAISED")
    _add_composed_paint(paints, "control.toggle.selected_hover_fill", "ACCENT_HOVER", "SURFACE_RAISED")
    _add_composed_paint(paints, "control.toggle.selected_pressed_fill", "ACCENT_PRESS", "SURFACE_RAISED")
    _add_composed_paint(paints, "control.toggle.selected_border", "ACCENT_BORDER", "SURFACE_RAISED")
    _add_composed_paint(paints, "focus.border", "BORDER_FOCUS", "SURFACE_ALT")
    _add_composed_paint(paints, "selection.fill", "SELECTION", "SURFACE")
    _add_composed_paint(paints, "table.row.fill", "SHADOW_LIGHT", "BG_DARK")
    _add_opaque_alias(paints, "table.row.alternate_fill", "SURFACE")
    _add_composed_paint(paints, "table.row.selected_fill", "SELECTION", "SURFACE")
    _add_composed_paint(paints, "status.danger.subtle_fill", "DANGER_DIM", "SURFACE")
    _add_composed_paint(paints, "status.danger.hover_fill", "DANGER_HOVER", "SURFACE_RAISED")
    _add_composed_paint(paints, "status.danger.border", "DANGER_BORDER", "SURFACE_ALT")
    _add_composed_paint(paints, "status.success.subtle_fill", "SUCCESS_DIM", "SURFACE")
    _add_composed_paint(paints, "status.success.hover_fill", "SUCCESS_HOVER", "SURFACE_RAISED")
    _add_composed_paint(paints, "status.success.border", "SUCCESS_BORDER", "SURFACE_ALT")
    _add_composed_paint(paints, "status.warning.subtle_fill", "WARNING_DIM", "SURFACE")
    _add_composed_paint(paints, "status.warning.hover_fill", "WARNING_HOVER", "SURFACE_RAISED")
    _add_composed_paint(paints, "status.warning.border", "WARNING_BORDER", "SURFACE_ALT")
    _add_composed_paint(paints, "status.info.subtle_fill", "INFO_DIM", "SURFACE")
    _add_composed_paint(paints, "status.info.hover_fill", "INFO_HOVER", "SURFACE_RAISED")
    _add_composed_paint(paints, "status.info.border", "INFO_BORDER", "SURFACE_ALT")
    for status in ("danger", "success", "warning", "info"):
        token = status.upper()
        _add_composed_paint(paints, f"status.{status}.badge_border", f"{token}_BORDER", token)
        _add_text_on_fill(paints, f"status.{status}.on_fill_text", token)
    _add_composed_paint(paints, "notice.info.fill", "INFO_DIM", "SURFACE")
    _add_composed_paint(paints, "notice.info.hover_fill", "INFO_HOVER", "SURFACE")
    _add_composed_paint(paints, "notice.info.border", "INFO_BORDER", "SURFACE")
    _add_composed_paint(paints, "device.picker.selected_fill", "ACCENT_DIM", "SURFACE_ALT")
    _add_opaque_alias(paints, "device.picker.selected_border", "ACCENT")
    _add_opaque_alias(paints, "data.accent.fill", "ACCENT")
    _add_composed_paint(paints, "data.accent.subtle_fill", "ACCENT_MUTED", "SURFACE")
    _add_opaque_alias(paints, "data.accent.border", "ACCENT_LIGHT")
    _add_opaque_alias(paints, "data.rating.text", "STAR")
    _add_composed_paint(paints, "sync.stage.current_fill", "ACCENT_MUTED", "SURFACE")
    _add_opaque_alias(paints, "sync.stage.current_border", "ACCENT")
    _add_composed_paint(paints, "sync.stage.failed_fill", "DANGER_DIM", "SURFACE")
    _add_opaque_alias(paints, "sync.stage.failed_border", "DANGER")
    _add_composed_paint(paints, "sync.plan.tab.selected_fill", "ACCENT_MUTED", "BG_DARK")
    _add_composed_paint(paints, "sync.plan.tab.selected_hover_fill", "ACCENT_DIM", "BG_DARK")
    _add_composed_paint(paints, "sync.plan.tab.selected_pressed_fill", "ACCENT_PRESS", "BG_DARK")
    _add_composed_paint(paints, "sync.plan.tab.selected_border", "ACCENT_BORDER", "BG_DARK")
    _add_composed_paint(paints, "editor.field.modified_fill", "ACCENT_MUTED", "SURFACE")
    _add_composed_paint(paints, "editor.field.modified_border", "ACCENT_BORDER", "SURFACE")
    _add_composed_paint(paints, "editor.table.selection_fill", "ACCENT_MUTED", "SURFACE_ALT")
    _add_sync_review_category_paints(paints, is_dark=is_dark)
    _add_podcast_paints(paints)
    _add_grid_paints(paints)
    _add_player_paints(paints, is_dark=is_dark)

    for name, source in {
        "effect.modal_scrim": "OVERLAY",
        "effect.elevation_light_shadow": "SHADOW_LIGHT",
        "effect.elevation_shadow": "SHADOW",
        "effect.elevation_deep_shadow": "SHADOW_DEEP",
        "effect.drop_target_scrim": "DROP_TARGET_SCRIM",
        "effect.drop_target_tint": "DROP_TARGET_TINT",
        "effect.drop_target_border": "DROP_TARGET_BORDER",
        "effect.scrollbar.thumb": "SCROLLBAR_THUMB",
        "effect.scrollbar.thumb_hover": "SCROLLBAR_THUMB_HOVER",
        "effect.scrollbar.thumb_press": "SCROLLBAR_THUMB_PRESS",
        "effect.artwork.crop_mask": "ARTWORK_CROP_MASK",
        "effect.artwork.crop_grid": "ARTWORK_CROP_GRID",
        "effect.artwork.crop_border": "ARTWORK_CROP_BORDER",
    }.items():
        _add_effect_alias(paints, name, source)


def _add_opaque_alias(paints: dict[str, Paint], name: str, source: str) -> None:
    paint = paints[source]
    if not paint.is_opaque:
        raise ValueError(f"{source} cannot be an opaque application paint")
    paints[name] = Paint(name, paint.color, "opaque", f"alias of {source}", paint.source_roles)


def _add_composed_paint(
    paints: dict[str, Paint],
    name: str,
    layer_name: str,
    backdrop_name: str,
) -> None:
    layer = paints[layer_name]
    backdrop = paints[backdrop_name]
    if layer.kind != "layer" or not backdrop.is_opaque:
        raise ValueError(f"Invalid composition: {layer_name} over {backdrop_name}")
    paints[name] = Paint(
        name,
        layer.color.composite_over(backdrop.color),
        "opaque",
        f"{layer_name} composited over {backdrop_name}",
        layer.source_roles + backdrop.source_roles,
        backdrop_name,
    )


def _add_grid_paints(paints: dict[str, Paint]) -> None:
    """Resolve opaque foundations for reusable content grid cards."""

    _add_opaque_alias(paints, "grid.card.fill", "SURFACE_RAISED")
    _add_opaque_alias(paints, "grid.card.hover_fill", "SURFACE_ACTIVE")
    _add_opaque_alias(paints, "grid.card.border", "BORDER_SUBTLE")
    _add_composed_paint(paints, "grid.card.selected_fill", "ACCENT_MUTED", "SURFACE_RAISED")
    _add_composed_paint(paints, "grid.card.selected_hover_fill", "ACCENT_DIM", "SURFACE_RAISED")
    _add_composed_paint(paints, "grid.card.selected_border", "ACCENT_BORDER", "SURFACE_RAISED")
    _add_opaque_alias(paints, "grid.art.background", "SURFACE_ALT")

    placeholder_tint = "_grid.art.placeholder_tint"
    _add_layer(
        paints,
        placeholder_tint,
        paints["ACCENT"].color,
        14,
        "grid artwork placeholder tint",
        ("accent",),
        "SURFACE_ALT",
    )
    _add_composed_paint(paints, "grid.art.placeholder_fill", placeholder_tint, "SURFACE_ALT")
    del paints[placeholder_tint]


def _add_podcast_paints(paints: dict[str, Paint]) -> None:
    """Resolve opaque episode-card states for the podcast browser."""

    _add_opaque_alias(paints, "podcast.episode.fill", "SURFACE")
    _add_opaque_alias(paints, "podcast.episode.border", "BORDER_SUBTLE")
    _add_composed_paint(paints, "podcast.episode.selected_fill", "ACCENT_MUTED", "SURFACE")
    _add_composed_paint(paints, "podcast.episode.selected_border", "ACCENT_BORDER", "SURFACE")
    _add_opaque_alias(paints, "podcast.episode.status_fill", "SURFACE_RAISED")


def _add_sync_review_category_paints(paints: dict[str, Paint], *, is_dark: bool) -> None:
    """Resolve the review's category treatments over its opaque card surface."""

    sources = {
        "add": "SUCCESS",
        "remove": "DANGER",
        "update_file": "SYNC_CYAN",
        "metadata": "SYNC_PURPLE",
        "artwork": "SYNC_MAGENTA",
        "playcount": "INFO",
        "rating": "WARNING",
        "playlist": "INFO",
        "integrity": "INFO",
        "error": "WARNING",
        "duplicate": "SYNC_ORANGE",
    }
    fill_alpha = 42 if is_dark else 26
    border_alpha = 86 if is_dark else 70
    for category, source in sources.items():
        prefix = f"sync.review.{category}"
        _add_opaque_alias(paints, f"{prefix}.text", source)
        fill_layer = f"_{prefix}.subtle_layer"
        border_layer = f"_{prefix}.border_layer"
        _add_layer(
            paints,
            fill_layer,
            paints[source].color,
            fill_alpha,
            f"sync review {category} subtle fill",
            paints[source].source_roles,
            "SURFACE",
        )
        _add_layer(
            paints,
            border_layer,
            paints[source].color,
            border_alpha,
            f"sync review {category} subtle border",
            paints[source].source_roles,
            "SURFACE",
        )
        _add_composed_paint(paints, f"{prefix}.subtle_fill", fill_layer, "SURFACE")
        _add_composed_paint(paints, f"{prefix}.subtle_border", border_layer, "SURFACE")
        del paints[fill_layer]
        del paints[border_layer]


def _add_player_paints(paints: dict[str, Paint], *, is_dark: bool) -> None:
    """Resolve the player chrome's opaque, theme-aware material recipes.

    The player deliberately uses a small set of bevelled gradients. Their
    stops are component paints, not widget-local blends or transparent layers:
    every stop is final and opaque before Qt receives it.
    """

    white = Color(255, 255, 255)
    black = Color(0, 0, 0)
    base = "DIALOG_BG"
    chrome_base_mix = "_player.chrome.base_mix"

    if is_dark:
        _add_mixed_paint(paints, "player.chrome.top", base, white, 0.10, "lightened player chrome top")
        _add_mixed_paint(paints, chrome_base_mix, base, "BG_MID", 0.50, "player chrome base and inset mix")
        _add_mixed_paint(paints, "player.chrome.middle", chrome_base_mix, white, 0.05, "lightened player chrome middle")
        _add_mixed_paint(paints, "player.chrome.bottom", "BG_MID", black, 0.14, "darkened player chrome bottom")
        _add_mixed_paint(paints, "player.surface.top", "SURFACE_RAISED", white, 0.10, "lightened player surface top")
        _add_mixed_paint(paints, "player.surface.middle", "SURFACE_ALT", white, 0.04, "lightened player surface middle")
        _add_mixed_paint(paints, "player.surface.bottom", "SURFACE", black, 0.16, "darkened player surface bottom")
        _add_mixed_paint(paints, "player.slider.groove.top", "SURFACE_ALT", black, 0.32, "darkened player slider groove top")
        _add_mixed_paint(paints, "player.slider.groove.middle", "SURFACE_RAISED", white, 0.04, "lightened player slider groove middle")
        _add_mixed_paint(paints, "player.slider.groove.bottom", "SURFACE_RAISED", white, 0.12, "lightened player slider groove bottom")
        _add_mixed_paint(paints, "player.slider.handle.top", "player.surface.top", "TEXT_PRIMARY", 0.36, "player slider handle top")
        _add_mixed_paint(paints, "player.slider.handle.middle", "player.surface.middle", "TEXT_PRIMARY", 0.24, "player slider handle middle")
        _add_mixed_paint(paints, "player.slider.handle.bottom", "player.surface.bottom", black, 0.12, "player slider handle bottom")
        fill_text_mix = 0.10
        fill_black_mix = 0.18
        inactive_star_mix = 0.45
    else:
        _add_mixed_paint(paints, "player.chrome.top", base, white, 0.58, "lightened player chrome top")
        _add_mixed_paint(paints, chrome_base_mix, base, "BG_MID", 0.40, "player chrome base and inset mix")
        _add_mixed_paint(paints, "player.chrome.middle", chrome_base_mix, black, 0.04, "darkened player chrome middle")
        _add_mixed_paint(paints, "player.chrome.bottom", "BG_MID", black, 0.12, "darkened player chrome bottom")
        _add_mixed_paint(paints, "player.surface.top", "SURFACE_RAISED", white, 0.38, "lightened player surface top")
        _add_mixed_paint(paints, "player.surface.middle", "SURFACE_ALT", black, 0.03, "darkened player surface middle")
        _add_mixed_paint(paints, "player.surface.bottom", "SURFACE", black, 0.12, "darkened player surface bottom")
        _add_mixed_paint(paints, "player.slider.groove.top", "SURFACE_ALT", black, 0.22, "darkened player slider groove top")
        _add_mixed_paint(paints, "player.slider.groove.middle", "SURFACE_RAISED", black, 0.06, "darkened player slider groove middle")
        _add_mixed_paint(paints, "player.slider.groove.bottom", "SURFACE_RAISED", white, 0.34, "lightened player slider groove bottom")
        _add_mixed_paint(paints, "player.slider.handle.top", "player.surface.top", white, 0.58, "player slider handle top")
        _add_mixed_paint(paints, "player.slider.handle.middle", "player.surface.middle", white, 0.28, "player slider handle middle")
        _add_mixed_paint(paints, "player.slider.handle.bottom", "player.surface.bottom", black, 0.16, "player slider handle bottom")
        fill_text_mix = 0.04
        fill_black_mix = 0.08
        inactive_star_mix = 0.45

    del paints[chrome_base_mix]
    _add_mixed_paint(paints, "player.surface.highlight", "player.surface.top", white, 0.28 if is_dark else 0.55, "player surface highlight")
    _add_mixed_paint(paints, "player.surface.border", "BORDER", "TEXT_TERTIARY", 0.22, "player surface border")
    _add_mixed_paint(paints, "player.art.fill", "player.surface.middle", "BG_DARK", 0.08, "player artwork fallback fill")
    _add_mixed_paint(paints, "player.art.border", "BORDER", "TEXT_TERTIARY", 0.18, "player artwork border")
    _add_mixed_paint(paints, "player.slider.fill.top", "ACCENT", "TEXT_PRIMARY", fill_text_mix, "player slider accent fill top")
    _add_mixed_paint(paints, "player.slider.fill.bottom", "ACCENT", black, fill_black_mix, "player slider accent fill bottom")
    _add_mixed_paint(paints, "player.star.inactive", "TEXT_TERTIARY", base, inactive_star_mix, "player inactive rating star")

    for name, source in {
        "player.control.hover_fill": "SURFACE_HOVER",
        "player.control.pressed_fill": "SURFACE_ACTIVE",
        "player.icon": "TEXT_SECONDARY",
        "player.icon.disabled": "TEXT_DISABLED",
        "player.text": "TEXT_PRIMARY",
        "player.text.secondary": "TEXT_SECONDARY",
        "player.text.tertiary": "TEXT_TERTIARY",
        "player.star.active": "STAR",
        "player.slider.border": "BORDER",
        "player.slider.disabled_fill": "BORDER_SUBTLE",
        "player.slider.disabled_progress_fill": "BORDER",
        "player.accent": "ACCENT",
    }.items():
        _add_opaque_alias(paints, name, source)


def _add_mixed_paint(
    paints: dict[str, Paint],
    name: str,
    first_name: str,
    second: str | Color,
    amount: float,
    recipe: str,
) -> None:
    """Add a final opaque paint by mixing two opaque renderer ingredients."""

    first = paints[first_name]
    if not first.is_opaque:
        raise ValueError(f"{first_name} cannot be mixed into an opaque component paint")
    if isinstance(second, str):
        second_paint = paints[second]
        if not second_paint.is_opaque:
            raise ValueError(f"{second} cannot be mixed into an opaque component paint")
        second_color = second_paint.color
        second_roles = second_paint.source_roles
    else:
        second_color = second
        second_roles = ("app_white" if second == Color(255, 255, 255) else "app_black",)
    paints[name] = Paint(
        name,
        first.color.mixed_with(second_color, amount),
        "opaque",
        recipe,
        first.source_roles + second_roles,
    )


def _add_effect_alias(paints: dict[str, Paint], name: str, source: str) -> None:
    paint = paints[source]
    if paint.kind != "layer" or paint.is_opaque:
        raise ValueError(f"{source} cannot be a transparent effect layer")
    paints[name] = Paint(name, paint.color, "layer", f"alias of {source}", paint.source_roles)


def _add_layer(
    paints: dict[str, Paint],
    name: str,
    color: Color,
    alpha: int,
    recipe: str,
    source_roles: tuple[str, ...] = ("accent",),
    backdrop_role: str | None = None,
) -> None:
    paints[name] = Paint(name, color.with_alpha(alpha), "layer", recipe, source_roles, backdrop_role)


def _resolved_semantic_colors(theme: ThemeInput, *, high_contrast: bool) -> dict[str, str]:
    colors = dict(theme.colors)
    if high_contrast:
        automatic = _AUTOMATIC_HIGH_CONTRAST_DARK if theme.type == "dark" else _AUTOMATIC_HIGH_CONTRAST_LIGHT
        for name, value in automatic.items():
            if name not in theme.high_contrast:
                colors[name] = value
        colors.update(theme.high_contrast)
    return _surface_color_fallbacks(colors, is_dark=theme.type == "dark")


def _surface_color_fallbacks(colors: dict[str, str], *, is_dark: bool) -> dict[str, str]:
    """Fill optional authoring roles without collapsing interaction states.

    Early JSON themes contained the compact foundation palette only.  In that
    shape, using ``surface_raised`` as the hover fallback made secondary
    controls render their normal and hover states identically.  The renderer
    therefore owns a small directional step for omitted interaction roles;
    authored ``surface_hover`` and ``surface_active`` remain untouched.
    """

    colors.setdefault("accent_light", Color.from_hex(colors["accent"]).lighten_toward_white(0.25).css)
    colors.setdefault("surface_alt", colors["surface"])
    colors.setdefault("surface_hover", _derived_surface_interaction_color(colors["surface_raised"], is_dark, 0.12 if is_dark else 0.08))
    colors.setdefault("surface_active", _derived_surface_interaction_color(colors["surface_hover"], is_dark, 0.06))
    colors.setdefault("menu_background", colors["surface_alt"])
    colors.setdefault("dialog_background", colors["background_alt"])
    colors.setdefault("tooltip_background", colors["surface_alt"])
    colors.setdefault("border_subtle", colors["surface_alt"])
    colors.setdefault("gridline", colors["border_subtle"])
    colors.setdefault("star", colors["warning"])
    colors.setdefault("sync_cyan", colors["info"])
    colors.setdefault("sync_purple", colors["accent"])
    colors.setdefault("sync_magenta", colors["accent_light"])
    colors.setdefault("sync_orange", colors["warning"])
    colors.setdefault("sync_freed", colors["success"])
    colors.setdefault("playlist_smart", colors["accent"])
    colors.setdefault("playlist_podcast", colors["success"])
    colors.setdefault("playlist_master", colors["text_tertiary"])
    colors.setdefault("playlist_regular", colors["accent"])
    return colors


def _derived_surface_interaction_color(value: str, is_dark: bool, amount: float) -> str:
    """Create an automatic interaction step for a compact theme palette."""

    endpoint = Color(255, 255, 255) if is_dark else Color(0, 0, 0)
    return Color.from_hex(value).mixed_with(endpoint, amount).css


_AUTOMATIC_HIGH_CONTRAST_DARK = {
    "text_primary": "#ffffff",
    "text_secondary": "#ffffff",
    "text_tertiary": "#ffffff",
    "text_disabled": "#ffffff",
    "border": "#ffffff",
    "border_subtle": "#ffffff",
    "gridline": "#ffffff",
}
_AUTOMATIC_HIGH_CONTRAST_LIGHT = {
    "text_primary": "#000000",
    "text_secondary": "#000000",
    "text_tertiary": "#000000",
    "text_disabled": "#000000",
    "border": "#000000",
    "border_subtle": "#000000",
    "gridline": "#000000",
}


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))
