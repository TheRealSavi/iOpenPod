"""Semantic Qt styles for the Backup Snapshot browser."""

from iOpenPod.GUI.presentation.theme.tokens import (
    LAYOUT,
    ThemeTokens,
    TypographyTokens,
)


def render_backup_page_style(
    tokens: ThemeTokens,
    typography: TypographyTokens,
) -> str:
    """Render the archive browser using the application theme contract."""

    return f"""/* Hallmark · macrostructure: Saved backup list · genre: quiet desktop utility
 * pre-emit critique: P4 H5 E4 S5 R5 V4 · theme: iOpenPod semantic
 * design-system: docs/gui-design-language.md
 * structure: iPod source list · device context · compact cards with optional details
 */
QWidget#backupsPage,
QWidget#backupBrowserPage,
QWidget#backupEmptyPage,
QWidget#backupDetail,
QWidget#backupSnapshotHost {{
    color: {tokens.text};
    background-color: {tokens.window};
}}
QFrame#backupRecoveryBanner {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
    border: none;
    border-bottom: 1px solid {tokens.warning};
}}
QLabel#backupRecoveryText {{
    color: {tokens.text};
    font-weight: 600;
}}
QLabel#backupDeviceName,
QLabel#backupEmptyTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}
QLabel#backupDeviceModel,
QLabel#backupDeviceSummary,
QLabel#backupSnapshotsCount,
QLabel#backupSnapshotSummary,
QLabel#backupProgressFile,
QLabel#backupEmptyDetail,
QLabel#backupArchiveEmpty {{
    color: {tokens.text_secondary};
}}
QFrame#backupHero {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border-bottom: 1px solid {tokens.border};
}}
QLabel#backupSnapshotsLabel,
QLabel#backupSnapshotDate,
QLabel#backupProgressTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}
QFrame#backupSnapshotCard,
QFrame#backupProgressPanel {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}
QLabel#backupSnapshotNote {{
    color: {tokens.text};
}}
QLabel#backupSnapshotInvalid {{
    color: {tokens.danger};
}}
"""


__all__ = ["render_backup_page_style"]
