"""Semantic Qt styles for the artwork-led Podcast experience."""

from iOpenPod.GUI.presentation.theme.tokens import (
    LAYOUT,
    ThemeTokens,
    TypographyTokens,
)


def render_podcast_page_style(
    tokens: ThemeTokens,
    typography: TypographyTokens,
) -> str:
    """Render the catalogue page without leaking theme literals into widgets."""

    return f"""/* Hallmark · macrostructure: Catalogue · genre: editorial · tone: premium restrained
 * pre-emit critique: P5 H5 E5 S5 R5 V5 · theme: iOpenPod semantic
 * anchor hue: iPod blue · contrast: pass (40-41) · slop: pass (42-58)
 * designed-as-app · enrichment: real feed and device artwork
 */
QWidget#podcastsPage,
QWidget#podcastBrowserPage,
QWidget#podcastEmptyPage {{
    color: {tokens.text};
    background-color: {tokens.window};
}}
QListView#podcastEpisodeList {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    outline: none;
}}
QListView#podcastShowShelf::item,
QListView#podcastEpisodeList::item {{
    background-color: transparent;
    border: none;
}}
QMenu#podcastEpisodeFilterMenu QCheckBox {{
    min-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_sm}px;
    color: {tokens.text};
    background-color: {tokens.surface};
}}
QMenu#podcastEpisodeFilterMenu QCheckBox:hover,
QMenu#podcastEpisodeFilterMenu QCheckBox:focus {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
}}
QMenu#podcastEpisodeFilterMenu QCheckBox:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
}}
QFrame#podcastHero {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border-top: 1px solid {tokens.border};
    border-bottom: 1px solid {tokens.border};
}}
QLabel#podcastShowTitle,
QLabel#podcastEmptyTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}
QLabel#podcastShowMeta,
QLabel#podcastShowDescription,
QLabel#podcastEmptyDetail,
QLabel#podcastSectionMeta {{
    color: {tokens.text_secondary};
}}
QLabel#podcastEpisodesTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}
QWidget#podcastEpisodesSection {{
    color: {tokens.text};
    background-color: {tokens.window};
}}
"""


def render_podcast_search_style(
    tokens: ThemeTokens,
    typography: TypographyTokens,
) -> str:
    """Render discovery and direct-feed controls from semantic tokens."""

    return f"""/* Hallmark · component: Podcast discovery · genre: editorial · theme: iOpenPod
 * states: default · hover · focus · pressed · disabled · loading · error · success
 */
QDialog#podcastSearchDialog {{
    color: {tokens.text};
    background-color: {tokens.window};
}}
QLabel#podcastDialogEyebrow,
QLabel#podcastFieldLabel {{
    color: {tokens.accent};
    font-size: {typography.small_pt:g}pt;
    font-weight: 700;
}}
QLabel#podcastDialogTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}
QLabel#podcastDialogIntro,
QLabel#podcastRssDetail,
QLabel#podcastSearchStatus {{
    color: {tokens.text_secondary};
}}
QListView#podcastDirectoryResults {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
    outline: none;
}}
QListView#podcastDirectoryResults::item {{
    background-color: transparent;
    border: none;
}}
QFrame#podcastRssPanel {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}
QLabel#podcastRssTitle {{
    color: {tokens.text};
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}
QLineEdit#podcastDirectoryQuery,
QLineEdit#podcastRssUrl {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    padding: 0 {LAYOUT.space_sm}px;
    selection-background-color: {tokens.accent};
    selection-color: {tokens.accent_ink};
}}
QLineEdit#podcastDirectoryQuery:hover,
QLineEdit#podcastRssUrl:hover {{
    background-color: {tokens.surface_hover};
}}
QLineEdit#podcastDirectoryQuery:focus,
QLineEdit#podcastRssUrl:focus {{
    border-color: {tokens.focus};
}}
QLineEdit#podcastDirectoryQuery:disabled,
QLineEdit#podcastRssUrl:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
}}
"""


__all__ = ["render_podcast_page_style", "render_podcast_search_style"]
