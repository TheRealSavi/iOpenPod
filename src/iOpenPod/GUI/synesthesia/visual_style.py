"""Semantic visual tokens for the full-bleed Synesthesia experience."""

from __future__ import annotations

from dataclasses import dataclass

from iOpenPod.GUI.presentation.theme.tokens import resolve_typography


@dataclass(frozen=True, slots=True)
class SynesthesiaVisualTokens:
    canvas: str = "#02040B"
    panel: str = "rgba(7, 11, 21, 218)"
    panel_hover: str = "rgba(13, 21, 37, 232)"
    panel_pressed: str = "rgba(18, 31, 51, 238)"
    text: str = "#F4F7FF"
    text_secondary: str = "rgba(225, 232, 246, 190)"
    text_muted: str = "rgba(191, 203, 223, 140)"
    text_disabled: str = "rgba(191, 203, 223, 82)"
    rule: str = "rgba(151, 178, 216, 48)"
    rule_strong: str = "rgba(166, 195, 235, 94)"
    accent: str = "#86BFFF"
    accent_hover: str = "#A3CEFF"
    accent_pressed: str = "#68A8F0"
    accent_ink: str = "#07101C"
    focus: str = "#C2DDFF"
    danger: str = "#FF9A9E"
    success: str = "#91DEB0"


TOKENS = SynesthesiaVisualTokens()


def synesthesia_stylesheet() -> str:
    """Return native QSS using only semantic visual and typography tokens."""

    typography = resolve_typography()
    token = TOKENS
    return f"""
        /* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5
         * genre: atmospheric · tone: nocturnal cinematic precise
         * palette: iOpenPod blue signal on ink · structure: full-bleed field plate
         */
        #synesthesiaPage {{
            background: {token.canvas};
            color: {token.text};
            font-family: "{typography.body}";
        }}
        #synesthesiaOverlay {{ background: transparent; }}
        QFrame#synesthesiaAnnotation,
        QFrame#synesthesiaTransport {{
            background: {token.panel};
            border: 1px solid {token.rule};
            border-radius: 12px;
        }}
        #synesthesiaKicker,
        #synesthesiaSectionKicker,
        #synesthesiaReadout {{
            color: {token.accent};
            font-family: "{typography.mono}";
            font-size: {typography.small_pt}pt;
            font-weight: 650;
        }}
        #synesthesiaTrack {{
            color: {token.text};
            font-family: "{typography.display}";
            font-size: {typography.title_pt}pt;
            font-weight: 560;
        }}
        #synesthesiaSection {{
            color: {token.text};
            font-family: "{typography.display}";
            font-size: {typography.heading_pt}pt;
            font-weight: 540;
        }}
        #synesthesiaStatus {{ color: {token.text_secondary}; }}
        #synesthesiaSource,
        #synesthesiaTime {{
            color: {token.text_secondary};
            font-family: "{typography.mono}";
            font-size: {typography.small_pt}pt;
        }}
        #synesthesiaStatus[state="error"] {{ color: {token.danger}; }}
        #synesthesiaStatus[state="success"] {{ color: {token.success}; }}
        QPushButton#synesthesiaPrimaryAction,
        QPushButton#synesthesiaTransportAction {{
            min-height: 36px;
            padding: 0 16px;
            border-radius: 8px;
            border: 1px solid {token.rule_strong};
            color: {token.text};
            background: {token.panel};
        }}
        QPushButton#synesthesiaTransportAction {{
            min-width: 38px;
            max-width: 38px;
            padding: 0;
        }}
        QPushButton#synesthesiaPrimaryAction:hover,
        QPushButton#synesthesiaTransportAction:hover {{
            background: {token.panel_hover};
            border-color: {token.accent};
        }}
        QPushButton#synesthesiaPrimaryAction:pressed,
        QPushButton#synesthesiaTransportAction:pressed {{
            background: {token.panel_pressed};
            border-color: {token.accent_pressed};
        }}
        QPushButton#synesthesiaPrimaryAction:focus,
        QPushButton#synesthesiaTransportAction:focus {{
            border: 2px solid {token.focus};
        }}
        QPushButton#synesthesiaPrimaryAction:disabled,
        QPushButton#synesthesiaTransportAction:disabled {{
            color: {token.text_disabled};
            border-color: {token.rule};
            background: {token.panel};
        }}
        QProgressBar#synesthesiaProgress {{
            min-height: 3px;
            max-height: 3px;
            border: 0;
            background: {token.rule};
        }}
        QProgressBar#synesthesiaProgress::chunk {{ background: {token.accent}; }}
    """


__all__ = ["TOKENS", "SynesthesiaVisualTokens", "synesthesia_stylesheet"]
