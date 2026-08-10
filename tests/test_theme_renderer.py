from iopenpod.infrastructure.theme_catalog import bundled_theme_directory, load_theme_catalog
from iopenpod.infrastructure.theme_renderer import (
    Color,
    render_artwork_grid_card_paints,
    render_content_hero_paints,
    render_theme,
    render_track_title_bar_paints,
)


def test_authored_surface_is_an_opaque_paint_with_a_documented_source() -> None:
    theme = load_theme_catalog(bundled_theme_directory()).get("catppuccin-mocha")

    paint = render_theme(theme).paint("SURFACE")

    assert paint.css == "#222333"
    assert paint.kind == "opaque"
    assert paint.source_roles == ("surface",)
    assert paint.recipe == "authored opaque role"


def test_derived_selection_is_an_explicit_layer_that_can_be_composed() -> None:
    theme = load_theme_catalog().get("dark")
    rendered = render_theme(theme)

    selection = rendered.paint("SELECTION")
    composed = rendered.composite("SELECTION")

    assert selection.kind == "layer"
    assert selection.source_roles == ("accent",)
    assert selection.color.alpha == 90
    assert selection.backdrop_role == "SURFACE"
    assert composed.kind == "opaque"
    assert composed.backdrop_role == "SURFACE"
    assert composed.css == "#2c4c7c"


def test_component_paints_are_final_opaque_colors_and_effects_remain_layers() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    for name in (
        "control.primary.pressed_fill",
        "control.toggle.selected_fill",
        "control.toggle.selected_hover_fill",
        "control.toggle.selected_pressed_fill",
        "control.toggle.selected_border",
        "focus.border",
        "selection.fill",
        "table.row.selected_fill",
        "status.danger.subtle_fill",
        "status.success.subtle_fill",
        "status.warning.subtle_fill",
        "status.info.subtle_fill",
        "data.accent.fill",
        "data.accent.subtle_fill",
        "data.accent.border",
        "data.rating.text",
        "notice.info.fill",
        "notice.info.hover_fill",
        "notice.info.border",
        "device.picker.selected_fill",
        "device.picker.selected_border",
        "sync.stage.current_fill",
        "sync.stage.current_border",
        "sync.stage.failed_fill",
        "sync.stage.failed_border",
        "sync.plan.tab.selected_fill",
        "sync.plan.tab.selected_hover_fill",
        "sync.plan.tab.selected_pressed_fill",
        "sync.plan.tab.selected_border",
        "sync.change.add.text",
        "sync.change.remove.text",
        "sync.change.file.text",
        "sync.change.metadata.text",
        "sync.change.artwork.text",
        "sync.change.play_count.text",
        "sync.change.rating.text",
        "editor.field.modified_fill",
        "editor.field.modified_border",
        "editor.table.selection_fill",
        "sync.storage.current_fill",
        "sync.storage.add_fill",
        "sync.storage.overflow_fill",
        "sync.storage.freed_fill",
        "sync.storage.exceeded_fill",
        "grid.card.fill",
        "grid.card.hover_fill",
        "grid.card.border",
        "grid.card.selected_fill",
        "grid.card.selected_hover_fill",
        "grid.card.selected_border",
        "grid.art.background",
        "grid.art.placeholder_fill",
        "podcast.episode.fill",
        "podcast.episode.border",
        "podcast.episode.selected_fill",
        "podcast.episode.selected_border",
        "podcast.episode.status_fill",
        "status.danger.badge_border",
        "status.danger.on_fill_text",
        "status.success.badge_border",
        "status.success.on_fill_text",
    ):
        assert rendered.paint(name).kind == "opaque"
        assert rendered.paint(name).is_opaque

    selection = rendered.paint("selection.fill")
    assert selection.recipe == "SELECTION composited over SURFACE"
    assert selection.source_roles == ("accent", "surface")
    assert selection.backdrop_role == "SURFACE"

    scrim = rendered.paint("effect.modal_scrim")
    assert scrim.kind == "layer"
    assert scrim.source_roles == ("background",)


def test_artwork_grid_card_states_are_renderer_owned_opaque_compositions() -> None:
    dark = render_theme(load_theme_catalog().get("dark"))
    light = render_theme(load_theme_catalog().get("light"))

    dark_paints = render_artwork_grid_card_paints(dark, (86, 112, 144))
    light_paints = render_artwork_grid_card_paints(light, (86, 112, 144))

    assert dark_paints.normal_fill.css == "#2f3247"
    assert dark_paints.hover_fill.css == "#33394f"
    assert light_paints.normal_fill.css == "#c4c8d3"
    assert light_paints.hover_fill.css == "#b2bac8"
    assert all(
        paint.is_opaque
        for paint in (
            dark_paints.normal_fill,
            dark_paints.hover_fill,
            light_paints.normal_fill,
            light_paints.hover_fill,
        )
    )
    assert dark_paints.hover_fill.recipe == "artwork grid card hover tint"
    assert dark_paints.hover_fill.source_roles == ("artwork_dominant_color", "surface_raised")


def test_dynamic_content_hero_layers_keep_their_app_owned_alpha_recipes() -> None:
    dark = render_content_hero_paints(render_theme(load_theme_catalog().get("dark")), (86, 112, 144))
    light = render_content_hero_paints(render_theme(load_theme_catalog().get("light")), (86, 112, 144))

    assert dark.header_tint.css == "rgba(86,112,144,80)"
    assert dark.header_border.css == "rgba(86,112,144,40)"
    assert dark.art_fill.css == "rgba(86,112,144,30)"
    assert dark.art_border.css == "rgba(86,112,144,50)"
    assert dark.action_fill.css == "rgba(255,255,255,18)"
    assert light.action_fill.css == "rgba(0,0,0,20)"
    assert light.action_hover.css == "rgba(0,0,0,28)"
    assert all(
        paint.kind == "layer"
        for paint in (
            dark.header_tint,
            dark.header_border,
            dark.art_fill,
            dark.art_border,
            dark.action_fill,
            dark.action_hover,
            dark.action_pressed,
            dark.action_border,
        )
    )


def test_track_title_bar_recipes_keep_dynamic_gradient_and_control_alpha_in_renderer() -> None:
    theme = render_theme(load_theme_catalog().get("dark"))

    playlist = render_track_title_bar_paints(theme, (64, 156, 255))
    artwork = render_track_title_bar_paints(theme, (64, 156, 255), contrast_ensured=True)

    assert playlist.gradient_top.color.alpha == 190
    assert playlist.gradient_middle is None
    assert playlist.gradient_bottom.color.alpha == 178
    assert playlist.border is not None and playlist.border.color.alpha == 130
    assert artwork.gradient_top.color.alpha == 92
    assert artwork.gradient_middle is not None and artwork.gradient_middle.color.alpha == 70
    assert artwork.gradient_bottom.color.alpha == 60
    assert artwork.border is None
    assert playlist.title_text.is_opaque
    assert playlist.icon_text.is_opaque
    assert playlist.button_hover.color.alpha == 30
    assert playlist.search_focus_border.color.alpha == 88


def test_table_rows_have_distinct_opaque_primary_and_alternate_paints() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    primary = rendered.paint("table.row.fill")
    alternate = rendered.paint("table.row.alternate_fill")

    assert primary.is_opaque
    assert alternate.is_opaque
    assert primary.css == rendered.composite("SHADOW_LIGHT", "BG_DARK").css
    assert alternate.css == rendered.paint("surface.default").css
    assert alternate.css != primary.css


def test_dark_builtins_use_the_same_composed_table_stripe_recipe() -> None:
    bundled = load_theme_catalog(bundled_theme_directory())
    themes = (
        load_theme_catalog().get("dark"),
        bundled.get("catppuccin-mocha"),
        bundled.get("catppuccin-macchiato"),
        bundled.get("catppuccin-frappe"),
    )

    for theme in themes:
        rendered = render_theme(theme)
        primary = rendered.paint("table.row.fill")
        alternate = rendered.paint("table.row.alternate_fill")

        assert primary.recipe == "SHADOW_LIGHT composited over BG_DARK"
        assert alternate.recipe == "alias of SURFACE"
        assert max(
            abs(left - right)
            for left, right in zip(primary.color.rgb, alternate.color.rgb, strict=True)
        ) >= 6


def test_podcast_episode_cards_use_a_content_surface_distinct_from_secondary_controls() -> None:
    catalog = load_theme_catalog(bundled_theme_directory())

    for theme in catalog.themes.values():
        rendered = render_theme(theme)
        episode = rendered.paint("podcast.episode.fill")
        more_button = rendered.paint("control.secondary.fill")

        assert episode.css != more_button.css
        assert episode.source_roles == ("surface",)
        assert rendered.paint("podcast.episode.selected_fill").backdrop_role == "SURFACE"
        assert rendered.paint("podcast.episode.status_fill").source_roles == ("surface_raised",)


def test_secondary_and_quiet_button_hovers_have_a_perceptible_default_dark_step() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    normal = rendered.paint("control.secondary.fill")
    hover = rendered.paint("control.secondary.hover_fill")

    assert hover.recipe == "secondary control hover blend"
    assert rendered.paint("control.quiet.hover_fill").css == hover.css
    assert max(
        abs(left - right)
        for left, right in zip(normal.color.rgb, hover.color.rgb, strict=True)
    ) >= 10


def test_sidebar_chrome_has_a_distinct_structural_surface_in_default_dark() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    sidebar = rendered.paint("chrome.sidebar.fill")
    canvas = rendered.paint("canvas.inset")

    assert sidebar.is_opaque
    assert sidebar.recipe == "elevated sidebar chrome"
    assert max(
        abs(left - right)
        for left, right in zip(sidebar.color.rgb, canvas.color.rgb, strict=True)
    ) >= 6


def test_drop_target_effects_are_the_only_transparent_drop_feedback_paints() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    for name, alpha in (
        ("effect.drop_target_scrim", 220),
        ("effect.drop_target_tint", 18),
        ("effect.drop_target_border", 100),
    ):
        paint = rendered.paint(name)
        assert paint.kind == "layer"
        assert paint.color.alpha == alpha


def test_scene_effects_keep_their_alpha_recipes_in_the_renderer() -> None:
    dark = render_theme(load_theme_catalog().get("dark"))
    light = render_theme(load_theme_catalog().get("light"))

    for name, alpha in (
        ("effect.artwork.crop_mask", 150),
        ("effect.artwork.crop_grid", 95),
        ("effect.artwork.crop_border", 235),
    ):
        paint = dark.paint(name)
        assert paint.kind == "layer"
        assert paint.color.alpha == alpha

    for name, dark_alpha, light_alpha in (
        ("effect.scrollbar.thumb", 70, 55),
        ("effect.scrollbar.thumb_hover", 110, 90),
        ("effect.scrollbar.thumb_press", 140, 120),
    ):
        assert dark.paint(name).kind == light.paint(name).kind == "layer"
        assert dark.paint(name).color.alpha == dark_alpha
        assert light.paint(name).color.alpha == light_alpha
        assert dark.paint(name).source_roles == ("text_primary",)


def test_sync_review_category_paints_are_opaque_card_compositions() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    for category in (
        "add",
        "remove",
        "update_file",
        "metadata",
        "artwork",
        "playcount",
        "rating",
        "playlist",
        "integrity",
        "error",
        "duplicate",
    ):
        assert rendered.paint(f"sync.review.{category}.text").is_opaque
        fill = rendered.paint(f"sync.review.{category}.subtle_fill")
        border = rendered.paint(f"sync.review.{category}.subtle_border")
        assert fill.is_opaque and border.is_opaque
        assert fill.backdrop_role == border.backdrop_role == "SURFACE"


def test_player_chrome_recipes_are_final_opaque_component_paints() -> None:
    rendered = render_theme(load_theme_catalog().get("dark"))

    player_paints = {
        name: paint
        for name, paint in rendered.paints.items()
        if name.startswith("player.")
    }

    assert player_paints
    assert all(paint.kind == "opaque" and paint.is_opaque for paint in player_paints.values())
    assert "player.chrome.base_mix" not in player_paints
    assert "lightened player chrome top" == player_paints["player.chrome.top"].recipe


def test_custom_accent_is_normalized_once_then_drives_all_accent_paints() -> None:
    theme = load_theme_catalog().get("dark")

    rendered = render_theme(theme, accent_override=Color.from_hex("#d94040"))

    assert rendered.paint("ACCENT").source_roles == ("custom_accent",)
    assert rendered.paint("ACCENT_LIGHT").source_roles == ("custom_accent",)
    assert rendered.paint("ACCENT_DIM").color.rgb == rendered.paint("ACCENT").color.rgb
    assert rendered.paint("playlist.regular").color.rgb == rendered.paint("ACCENT").color.rgb


def test_theme_authored_accent_light_is_not_replaced_by_a_generic_derivation() -> None:
    theme = load_theme_catalog(bundled_theme_directory()).get("catppuccin-mocha")

    rendered = render_theme(theme)

    assert rendered.paint("ACCENT").css == "#89b4fa"
    assert rendered.paint("ACCENT_LIGHT").css == "#b4befe"
    assert rendered.paint("TEXT_ON_ACCENT").css == "#1e1e2e"
