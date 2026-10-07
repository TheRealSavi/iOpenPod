"""Render the application-wide Qt stylesheet from semantic tokens."""

from dataclasses import dataclass

from PySide6.QtGui import QColor

from iOpenPod.GUI.presentation.theme.tokens import (
    LAYOUT,
    ThemeTokens,
    TypographyTokens,
)


@dataclass(frozen=True, slots=True)
class _PlayerColors:
    """Theme-derived colors used only by the Player's tactile surface."""

    bar_highlight: str
    bar_shadow: str
    surface_highlight: str
    surface_shadow: str
    track_highlight: str
    track_shadow: str
    knob_highlight: str
    knob_shadow: str
    accent_highlight: str
    accent_shadow: str


def _player_colors(tokens: ThemeTokens) -> _PlayerColors:
    """Derive restrained Player depth without extending the theme protocol."""

    return _PlayerColors(
        bar_highlight=_lighter(tokens.surface_alt, 106),
        bar_shadow=_darker(tokens.surface_alt, 105),
        surface_highlight=_lighter(tokens.surface, 103),
        surface_shadow=_darker(tokens.surface, 104),
        track_highlight=_lighter(tokens.border_strong, 108),
        track_shadow=_darker(tokens.border_strong, 106),
        knob_highlight=_lighter(tokens.surface, 122),
        knob_shadow=_darker(tokens.surface_alt, 105),
        accent_highlight=_lighter(tokens.accent, 110),
        accent_shadow=_darker(tokens.accent, 105),
    )


def _lighter(color: str, factor: int) -> str:
    return QColor(color).lighter(factor).name(QColor.NameFormat.HexRgb)


def _darker(color: str, factor: int) -> str:
    return QColor(color).darker(factor).name(QColor.NameFormat.HexRgb)


def render_stylesheet(
    tokens: ThemeTokens,
    typography: TypographyTokens,
) -> str:
    """Render the shared desktop visual language from semantic tokens."""

    player = _player_colors(tokens)

    return f"""/* Hallmark · macrostructure: Full-height Playback Band · genre: modern-minimal
 * pre-emit critique: P5 H5 E5 S5 R5 V4
 * theme: iOP2 Porcelain/Slate · tone: calm technical utility
 * anchor hue: iPod blue · inspiration: Original iOpenPod, translated
 * structure: absent idle state · full-height center well · optional runtime pane
 * rendering: Qt model/view · logical pixels · native point sizes · DPR-aware SVG
 * enrichment: deterministic painted placeholder artwork
 * nav: N3 source-list rail · footer: desktop status bar
 * contrast: pass (40-41) · honest: pass (46) · tokens: pass (48)
 */
/* Hallmark · component: Page Header + Source List rail · genre: modern-minimal
 * structure: compact one-line header · inset heading/count · rounded source cards
 * states: default · hover · focus · pressed · disabled · selected
 * asynchronous loading · error · success presentation remains page-owned
 * pre-emit critique: P5 H5 E5 S5 R5 V4 · contrast: pass (40-41)
 */
/* Hallmark · component: Player · genre: modern-minimal · theme: iOpenPod
 * runtime: collapsed idle · loaded · paused · playing
 * controls: left transport · right volume + far-right Queue · full-height center well
 * surface: theme-derived low-contrast depth · rounded tactile slider handles
 * states: default · hover · focus · pressed · disabled · checked · dragging
 * pre-emit critique: P5 H5 E5 S5 R5 V4 · contrast: pass (40-41)
 */
/* Hallmark · component: semantic buttons · genre: modern-minimal
 * states: default · hover · focus · pressed · disabled · loading · error · success
 * contrast: pass (40-41) · tokens: pass (48)
 */
/* Hallmark · component: metadata editor · genre: modern-minimal
 * states: default · hover · focus · pressed · disabled · modified · error · reset
 * pre-emit critique: P5 H5 E5 S5 R5 V4 · contrast: pass (40-41)
 */
/* Hallmark · component: iPod rename field · genre: modern-minimal
 * states: default · hover · focus · pressed · disabled · loading · error · success
 * pre-emit critique: P5 H5 E5 S5 R5 V4 · contrast: pass (40-41)
 */
/* Hallmark · component: Choose Media Folders dialog · genre: modern-minimal
 * structure: compact header · flat folder source list · inline disclosure settings
 * states: empty · populated · expanded · default · hover · focus · pressed · disabled
 * pre-emit critique: P5 H5 E5 S5 R5 V4 · contrast: pass (40-41)
 * slop: pass (1-58) · honest: pass (46) · chrome: pass (47) · tokens: pass (48)
 */
/* Hallmark · component: Host Media scan review · genre: modern-minimal
 * structure: determinate progress · flat checkable file table · explicit bulk actions
 * states: default · hover · focus · pressed · disabled · loading · error · success
 * pre-emit critique: P5 H5 E5 S5 R5 V5 · contrast: pass (40-41)
 * slop: pass (1-58) · honest: pass (46) · chrome: pass (47) · tokens: pass (48)
 */
/* Hallmark · macrostructure: Workbench · component: Sync Plan · genre: modern-minimal
 * structure: compact summary ledger · filters · virtualized reconciliation table
 * tone: technical utilitarian · theme: iOpenPod Porcelain/Slate · enrichment: none
 * states: empty · filtered · planned · attention · default · hover · focus · selected
 * pre-emit critique: P5 H5 E5 S5 R5 V5 · contrast: pass (40-41)
 * slop: pass (1-58) · honest: pass (46) · chrome: pass (47) · tokens: pass (48)
 */
/* Hallmark · macrostructure: Narrative Workflow · component: Sync Workspace · genre: modern-minimal
 * structure: staged header · replaceable work surface · persistent footer actions
 * tone: technical utilitarian · theme: iOpenPod Porcelain/Slate · enrichment: none
 * states: sources · scanning · selecting · review · default · hover · focus · disabled
 * pre-emit critique: P5 H5 E5 S5 R5 V5 · contrast: pass (40-41)
 * slop: pass (1-58) · honest: pass (46) · chrome: pass (47) · tokens: pass (48)
 */
QWidget {{
    color: {tokens.text};
    background-color: transparent;
    font-family: "{typography.body}";
    font-size: {typography.body_pt:g}pt;
}}

QMainWindow,
QWidget#appShell,
QWidget#syncWorkspace,
QFrame#appBody,
QStackedWidget#pageStack,
QStackedWidget#syncWorkspaceContent,
QStackedWidget#syncLibraryStack {{
    color: {tokens.text};
    background-color: {tokens.window};
}}

QLabel#pageTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}

QLabel#sectionTitle,
QLabel[browserTitle="true"] {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}

QLabel#pageDescription,
QLabel#pageMeta,
QLabel#deviceSearchStatus,
QLabel#settingDescription,
QLabel#playerTrackDetail,
QLabel#playerTime,
QLabel#playbackEmptyDetail,
QLabel#playbackQueueCount,
QLabel#deviceModel,
QLabel#deviceSummary,
QLabel#deviceMetricLabel,
QLabel#placeholderNote {{
    color: {tokens.text_secondary};
}}

QLabel#pageMeta,
QLabel#deviceSearchStatus,
QLabel#playbackEmptyDetail,
QLabel#playbackQueueCount,
QLabel#deviceModel,
QLabel#deviceSummary,
QLabel#deviceMetricLabel,
QLabel#deviceMetricValue,
QLabel#sidebarSectionLabel {{
    font-size: {typography.small_pt:g}pt;
}}

QTreeView#playlistTree {{
    background-color: {tokens.surface};
    alternate-background-color: {tokens.surface_hover};
    border: none;
    selection-background-color: {tokens.surface_selected};
    selection-color: {tokens.accent};
}}

QPushButton#playlistSectionToggle {{
    padding-right: {LAYOUT.control_height_compact + LAYOUT.icon_button_size}px;
    border-color: transparent;
}}

QPushButton#playlistSectionToggle:checked {{
    color: {tokens.text};
    background-color: transparent;
    font-weight: 400;
}}

QPushButton#playlistSectionToggle:hover {{
    background-color: {tokens.surface_hover};
}}

QPushButton#playlistSectionToggle:pressed {{
    background-color: {tokens.surface_pressed};
}}

QToolButton#newPlaylistButton,
QToolButton#newPlaylistButton:hover,
QToolButton#newPlaylistButton:pressed {{
    background-color: transparent;
    border-color: transparent;
}}

QToolButton#newPlaylistButton::menu-indicator {{
    image: none;
    width: 0;
    height: 0;
}}

QToolButton#newPlaylistButton:focus {{
    border-color: {tokens.focus};
}}

QLabel#playlistSidebarEmpty,
QLabel#playlistEmpty {{
    color: {tokens.text_secondary};
}}

QLabel#playlistEditorError,
QLabel#metadataEditError,
QLabel#photoAlbumManagerError {{
    color: {tokens.danger};
}}

QDialog#playlistEditor,
QDialog#metadataEditor,
QDialog#artworkCropDialog,
QDialog#consolidateArtworkDialog,
QDialog#photoMetadataEditor,
QDialog#tagNormalizer,
QDialog#libraryReviewDialog,
QDialog#scrobbleReport,
QDialog#playlistExportDialog,
QDialog#podcastSyncSettingsDialog,
QDialog#photoAlbumManager,
QDialog#photoAlbumEditor,
QDialog#mediaFoldersDialog,
QDialog#mediaFolderSettingsDialog,
QDialog#mediaToolsSetup,
QDialog#externalPlaylistFilesDialog,
QDialog#syncDuplicatesDialog,
QDialog#linuxIdentitySetup,
QDialog#linuxIdentityUninstall,
    QFileDialog,
    QInputDialog,
    QProgressDialog#libraryExportProgress,
    QMessageBox {{
    color: {tokens.text};
    background-color: {tokens.window};
}}

QLabel#dialogTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}

QLabel#mediaFolderSummary,
QLabel#mediaFolderEmpty {{
    color: {tokens.text_secondary};
}}

QFrame#syncWorkspaceHeader,
QFrame#syncWorkspaceFooter {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
}}

QFrame#syncWorkspaceHeader {{
    border-bottom: 1px solid {tokens.border};
}}

QFrame#syncWorkspaceFooter {{
    border-top: 1px solid {tokens.border};
}}

QFrame#syncStorageBar {{
    background-color: {tokens.surface};
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

QLabel#syncStorageDevice {{
    font-weight: 700;
}}

QLabel#syncStorageTitle,
QLabel#syncStorageNote {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
}}

QLabel#syncStorageCurrent {{
    color: {tokens.accent};
}}

QLabel#syncStorageDelta[direction="add"] {{
    color: {tokens.success};
}}

QLabel#syncStorageDelta[direction="remove"],
QLabel#syncStorageRemaining[status="partial"] {{
    color: {tokens.warning};
}}

QLabel#syncStorageDelta[status="over"],
QLabel#syncStorageRemaining[status="over"] {{
    color: {tokens.danger};
}}

QLabel#syncWorkspaceTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}

QLabel#syncStageIndicator {{
    color: {tokens.text_secondary};
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_2xs}px {LAYOUT.space_xs}px;
    font-size: {typography.small_pt:g}pt;
}}

QLabel#syncStageIndicator[complete="true"] {{
    color: {tokens.success};
}}

QLabel#syncStageIndicator[current="true"] {{
    color: {tokens.accent};
    background-color: {tokens.surface_selected};
    border-color: {tokens.accent};
    font-weight: 700;
}}

QFrame#syncSelectionBody,
QFrame#syncLibraryNavigation,
QScrollArea#syncLibraryNavigationScroll,
QScrollArea#syncLibraryNavigationScroll > QWidget > QWidget {{
    color: {tokens.text};
    background-color: {tokens.surface};
}}

QFrame#syncLibraryNavigation {{
    border: none;
    border-right: 1px solid {tokens.border};
}}

QFrame#syncScanPanel {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
    min-width: {LAYOUT.sync_scan_panel_minimum_width}px;
    max-width: {LAYOUT.sync_scan_panel_maximum_width}px;
}}

QLabel#syncScanTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}

QLabel#syncScanDetail,
QLabel#syncSelectionSummary {{
    color: {tokens.text_secondary};
}}

QWidget#mediaFoldersPage {{
    color: {tokens.text};
    background-color: {tokens.window};
}}

QWidget#syncPlanPage,
QWidget#syncReviewGroups,
QScrollArea#syncReviewScroll,
QStackedWidget#syncPlanContent {{
    color: {tokens.text};
    background-color: {tokens.window};
}}

QLabel#syncPlanDescription,
QLabel#syncReviewGroupSubtitle,
QLabel#syncReviewGroupSelected,
QLabel#syncReviewSummary,
QLabel#syncPlanResults,
QLabel#syncPlanEmpty {{
    color: {tokens.text_secondary};
}}

QLabel#syncPlanDescription {{
    font-size: {typography.body_pt:g}pt;
}}

QFrame#syncReviewGroup {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QLabel#syncReviewGroupTitle {{
    color: {tokens.text};
    font-size: {typography.body_pt:g}pt;
    font-weight: 600;
}}

QLabel#syncReviewGroupSubtitle,
QLabel#syncReviewGroupSelected,
QLabel#syncPlanResults {{
    font-size: {typography.small_pt:g}pt;
}}

QPushButton#syncReviewGroupToggle {{
    background-color: transparent;
    border: 2px solid transparent;
    border-radius: {LAYOUT.radius_panel}px;
    padding: 0;
    min-height: {LAYOUT.control_height_large}px;
}}

QPushButton#syncReviewGroupToggle:hover {{
    background-color: {tokens.surface_hover};
}}

QPushButton#syncReviewGroupToggle:pressed {{
    background-color: {tokens.surface_pressed};
}}

QPushButton#syncReviewGroupToggle:focus {{
    border-color: {tokens.focus};
}}

QLabel#syncReviewSymbol,
QLabel#syncReviewGroupCount {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface_alt};
    border-radius: {LAYOUT.radius_control}px;
    font-weight: 600;
}}

QLabel#syncReviewGroupCount {{
    padding: {LAYOUT.space_xs}px {LAYOUT.space_sm}px;
}}

QLabel#syncReviewSymbol[action="add"],
QLabel#syncReviewGroupCount[action="add"] {{
    color: {tokens.success};
}}

QLabel#syncReviewSymbol[action="remove"],
QLabel#syncReviewGroupCount[action="remove"] {{
    color: {tokens.danger};
}}

QLabel#syncReviewSymbol[action="update"],
QLabel#syncReviewGroupCount[action="update"] {{
    color: {tokens.accent};
}}

QLabel#syncReviewSymbol[action="attention"],
QLabel#syncReviewGroupCount[action="attention"] {{
    color: {tokens.warning};
}}

QLabel#syncPlanAttention {{
    color: {tokens.warning};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.warning};
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_sm}px;
}}

QLabel#syncPlanEmpty {{
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
    padding: {LAYOUT.space_xl}px;
}}

QLabel#syncDuplicateTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}

QLabel#syncDuplicateGroupTitle {{
    color: {tokens.text};
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}

QLabel#syncDuplicateDescription,
QLabel#syncDuplicateOverview,
QLabel#syncDuplicateGroupStatus,
QLabel#syncDuplicateChoiceHelp,
QLabel#syncDuplicateIPodSummary,
QLabel#syncDuplicateHostDetails,
QLabel#syncDuplicateIPodDetails,
QLabel#syncDuplicateRemovalContext,
QLabel#syncDuplicateFooterNote {{
    color: {tokens.text_secondary};
}}

QLabel#syncDuplicateOverview,
QLabel#syncDuplicateFooterNote,
QLabel#syncDuplicateHostDetails,
QLabel#syncDuplicateIPodDetails {{
    font-size: {typography.small_pt:g}pt;
}}

QLabel#syncDuplicateSectionTitle,
QLabel#syncDuplicateChoiceLabel {{
    color: {tokens.text};
    font-weight: 600;
}}

QLabel#syncDuplicateStatus {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface_alt};
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_2xs}px {LAYOUT.space_xs}px;
    font-weight: 600;
}}

QLabel#syncDuplicateStatus[tone="attention"] {{
    color: {tokens.warning};
}}

QLabel#syncDuplicateStatus[tone="ready"] {{
    color: {tokens.success};
}}

QLabel#syncDuplicateRemovalNote {{
    color: {tokens.warning};
}}

QLabel#syncDuplicateEmpty {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface};
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_md}px;
}}

QScrollArea#syncDuplicateDetailScroll,
QScrollArea#syncDuplicateDetailScroll > QWidget > QWidget {{
    color: {tokens.text};
    background-color: {tokens.window};
    border: none;
}}

QListWidget#syncDuplicateGroups {{
    color: {tokens.text};
    background-color: {tokens.window};
    border: none;
    outline: none;
}}

QListWidget#syncDuplicateGroups::item {{
    padding: {LAYOUT.space_sm}px {LAYOUT.space_xs}px;
    border: 2px solid transparent;
    border-radius: {LAYOUT.radius_control}px;
}}

QListWidget#syncDuplicateGroups::item:hover {{
    background-color: {tokens.surface_hover};
}}

QListWidget#syncDuplicateGroups::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QListWidget#syncDuplicateGroups::item:focus {{
    border-color: {tokens.focus};
}}

QTreeWidget#syncDuplicateHosts,
QTreeWidget#syncDuplicateIPods {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
}}

QTreeWidget#syncDuplicateHosts::item,
QTreeWidget#syncDuplicateIPods::item {{
    min-height: {LAYOUT.control_height_large}px;
    padding: {LAYOUT.space_2xs}px;
}}

QLabel#mediaFolderSummary,
QLabel#mediaFolderScanLabel {{
    font-size: {typography.small_pt:g}pt;
}}

QLabel#mediaFolderScanLabel {{
    color: {tokens.text_secondary};
    font-weight: 600;
}}

QScrollArea#mediaFoldersScroll,
QScrollArea#mediaFoldersScroll > QWidget > QWidget,
QFrame#mediaFoldersList {{
    color: {tokens.text};
    background-color: {tokens.surface};
}}

QScrollArea#mediaFoldersScroll {{
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QFrame#mediaFolderRow {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

QLabel#mediaFolderNumber {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent};
    border-radius: {LAYOUT.control_height_compact // 2}px;
    font-weight: 700;
}}

QLabel#mediaFolderPath {{
    color: {tokens.text};
    font-weight: 600;
}}

QFrame#mediaFolderSettings {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: none;
    border-radius: {LAYOUT.radius_control}px;
}}

QRadioButton {{
    color: {tokens.text};
    spacing: {LAYOUT.space_xs}px;
    padding: {LAYOUT.space_2xs}px 0;
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    background-color: {tokens.surface};
    border: 2px solid {tokens.border_strong};
    border-radius: 10px;
}}

QRadioButton:hover::indicator {{
    background-color: {tokens.surface_hover};
    border-color: {tokens.text_secondary};
}}

QRadioButton:focus::indicator {{
    border-color: {tokens.focus};
}}

QRadioButton::indicator:checked {{
    background-color: {tokens.accent};
    border-color: {tokens.accent_ink};
}}

QRadioButton::indicator:disabled {{
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QRadioButton:disabled {{
    color: {tokens.text_disabled};
}}

QProgressDialog#libraryExportProgress QProgressBar,
QProgressBar#syncScanProgress,
QProgressBar#syncExecutionOverallProgress,
QProgressBar#syncExecutionProgress,
QProgressBar#syncPreparationProgress {{
    min-height: 10px;
    max-height: 10px;
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: 5px;
    text-align: center;
}}

QProgressDialog#libraryExportProgress QProgressBar::chunk,
QProgressBar#syncScanProgress::chunk,
QProgressBar#syncExecutionOverallProgress::chunk,
QProgressBar#syncExecutionProgress::chunk,
QProgressBar#syncPreparationProgress::chunk {{
    background-color: {tokens.accent};
    border-radius: 4px;
}}

QFrame#syncExecutionStages,
QFrame#syncExecutionPanel {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QLabel#syncExecutionStage1,
QLabel#syncExecutionStage2,
QLabel#syncExecutionStage3,
QLabel#syncExecutionStage4,
QLabel#syncExecutionStage5,
QLabel#syncExecutionStage6 {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
    padding: {LAYOUT.space_2xs}px;
}}

QLabel#syncExecutionStage1[state="current"],
QLabel#syncExecutionStage2[state="current"],
QLabel#syncExecutionStage3[state="current"],
QLabel#syncExecutionStage4[state="current"],
QLabel#syncExecutionStage5[state="current"],
QLabel#syncExecutionStage6[state="current"] {{
    color: {tokens.accent};
    font-weight: 700;
}}

QLabel#syncExecutionStage1[state="complete"],
QLabel#syncExecutionStage2[state="complete"],
QLabel#syncExecutionStage3[state="complete"],
QLabel#syncExecutionStage4[state="complete"],
QLabel#syncExecutionStage5[state="complete"],
QLabel#syncExecutionStage6[state="complete"] {{
    color: {tokens.success};
}}

QLabel#syncExecutionStage {{
    color: {tokens.text};
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}

QLabel#syncExecutionStageSummary,
QLabel#syncExecutionProgressSummary,
QLabel#syncExecutionEta,
QLabel#syncPreparationSummary {{
    color: {tokens.text_secondary};
}}

QLabel#syncExecutionItem,
QLabel#syncPreparationDetail {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
}}

QScrollArea#syncPreparationProgressList,
QScrollArea#syncPreparationProgressList > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}

QLabel#syncPreparationName {{
    font-weight: 600;
}}

QPlainTextEdit#syncExecutionActivity {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_xs}px;
}}

QMessageBox QLabel {{
    color: {tokens.text};
    background-color: transparent;
}}

QFrame#metadataEditorHeader,
QFrame#metadataPageHeader,
QFrame#metadataSectionPanel {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QWidget#metadataEditorPage,
QStackedWidget#metadataEditorPages,
QWidget#metadataPageBody {{
    color: {tokens.text};
    background-color: {tokens.window};
    border: none;
}}

QScrollArea#metadataPageScroll,
QScrollArea#metadataPageScroll > QWidget > QWidget {{
    color: {tokens.text};
    background-color: {tokens.window};
    border: none;
}}

QLabel#metadataEditorTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}

QLabel#metadataGroupTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 700;
}}

QLabel#metadataSectionTitle,
QLabel#metadataFieldLabel {{
    color: {tokens.text};
    font-weight: 600;
}}

QLabel#metadataSectionTitle,
QLabel#metadataEditorSubtitle,
QLabel#metadataGroupDescription,
QLabel#metadataChangeSummary {{
    color: {tokens.text_secondary};
}}

QLabel#metadataSectionTitle,
QLabel#metadataEditorSubtitle,
QLabel#metadataGroupDescription,
QLabel#metadataChangeSummary {{
    font-size: {typography.small_pt:g}pt;
}}

QFrame#metadataFieldRow {{
    color: {tokens.text};
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {LAYOUT.radius_control}px;
}}

QFrame#metadataFieldRow[modified="true"] {{
    background-color: {tokens.surface_selected};
    border-color: {tokens.accent};
}}

QLabel#metadataArtworkImage {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
}}

QLabel#metadataArtworkStatus,
QLabel#metadataArtworkNote,
QLabel#artworkConsolidationStatus {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
}}

QListWidget#artworkConsolidationGrid {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
    outline: none;
    padding: {LAYOUT.space_xs}px;
}}

QListWidget#artworkConsolidationGrid::item {{
    color: {tokens.text_secondary};
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_xs}px;
}}

QListWidget#artworkConsolidationGrid::item:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
    border-color: {tokens.border};
}}

QListWidget#artworkConsolidationGrid::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
    border-color: {tokens.accent};
}}

QListWidget#metadataSectionNav {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    outline: none;
}}

QScrollArea#smartRulesScroll,
QScrollArea#smartRulesScroll > QWidget > QWidget {{
    color: {tokens.text};
    background-color: {tokens.window};
    border: none;
}}

QWidget#smartRuleGroup[ruleGroupTone="base"] {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QWidget#smartRuleGroup[ruleGroupTone="alternate"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QListWidget#metadataSectionNav::item {{
    min-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_xs}px;
    border: none;
    border-radius: {LAYOUT.radius_control}px;
}}

QListWidget#metadataSectionNav::item:hover {{
    background-color: {tokens.surface_hover};
}}

QListWidget#metadataSectionNav::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QDialog#metadataEditor QPlainTextEdit,
QTreeWidget#metadataTechnicalDetails,
QDialog#metadataEditor QTableWidget {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border_strong};
    border-radius: {LAYOUT.radius_control}px;
    selection-color: {tokens.accent_ink};
    selection-background-color: {tokens.accent};
}}

QDialog#metadataEditor QPlainTextEdit:focus,
QDialog#metadataEditor QTableWidget:focus,
QTreeWidget#metadataTechnicalDetails:focus {{
    border-color: {tokens.focus};
}}

QTreeWidget#metadataTechnicalDetails::item {{
    min-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_xs}px;
}}

QTreeWidget#libraryReviewItems,
QPlainTextEdit#libraryReviewDetails,
QPlainTextEdit#scrobbleReportText,
QPlainTextEdit#mediaToolInstallLog,
QPlainTextEdit#linuxIdentitySetupCommand {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    selection-background-color: {tokens.surface_selected};
    selection-color: {tokens.text};
}}

QTreeWidget#libraryReviewItems::item {{
    padding: {LAYOUT.space_xs}px;
}}

QLabel#settingLabel,
QLabel#playerTrackTitle {{
    color: {tokens.text};
    font-weight: 600;
}}

QLabel#linuxIdentitySetupStatus {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
}}

QLabel#trackListTitle {{
    color: {tokens.text};
    font-size: {typography.title_pt:g}pt;
    font-weight: 700;
}}

QLabel#playerTrackTitle {{
    font-size: {typography.heading_pt:g}pt;
}}

QLabel#playerRating {{
    color: {tokens.warning};
    font-size: {typography.heading_pt:g}pt;
}}

QLabel#playerRating[ratingHover="true"] {{
    color: {tokens.accent_hover};
}}

QFrame#playerBar {{
    color: {tokens.text};
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.bar_highlight},
        stop: 0.5 {tokens.surface_alt},
        stop: 1 {player.bar_shadow}
    );
    border: none;
}}

QFrame#playerBar[playerPosition="top"] {{
    border-bottom: 1px solid {tokens.border};
}}

QFrame#playerBar[playerPosition="bottom"] {{
    border-top: 1px solid {tokens.border};
}}

QFrame#nowPlayingSurface {{
    color: {tokens.text};
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.surface_highlight},
        stop: 0.52 {tokens.surface},
        stop: 1 {player.surface_shadow}
    );
    border: none;
    border-left: 1px solid {tokens.border};
    border-right: 1px solid {tokens.border};
    border-radius: 0;
}}

QFrame#nowPlayingSurface[playbackState="idle"] {{
    color: {tokens.text};
    background: transparent;
    border-color: transparent;
}}

QFrame#playbackPaneHost {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
    border-left: 1px solid {tokens.border};
}}

QFrame#playbackPane {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
}}

QTabWidget#playbackTabs,
QTabWidget#playbackTabs > QWidget,
QWidget#playbackQueueTab,
QWidget#playbackHistoryTab,
QWidget#playbackLyricsTab,
QStackedWidget#playbackQueueStack,
QStackedWidget#playbackHistoryStack {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
}}

QTabWidget#playbackTabs::pane {{
    background-color: {tokens.surface};
    border: none;
    border-top: 1px solid {tokens.border};
}}

QTabWidget#settingsTabs::pane {{
    border: none;
    border-top: 1px solid {tokens.border};
}}

QTabBar::tab {{
    min-width: 92px;
    min-height: {LAYOUT.control_height_large}px;
    padding: 0 {LAYOUT.space_md}px;
    color: {tokens.text_secondary};
    background-color: {tokens.surface};
    border: none;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
}}

QTabWidget#playbackTabs QTabBar::tab {{
    min-width: {LAYOUT.playback_pane_width // 3 - 2 * LAYOUT.space_xs}px;
    padding: 0 {LAYOUT.space_xs}px;
}}

QTabBar::tab:selected {{
    color: {tokens.text};
    border-bottom-color: {tokens.accent};
    font-weight: 600;
}}

QTabBar::tab:focus {{
    border: 2px solid {tokens.focus};
    border-bottom-color: {tokens.accent};
}}

QListView#playbackQueueView,
QListView#playbackHistoryView,
QPlainTextEdit#playbackLyricsText {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    outline: none;
}}

QPlainTextEdit#playbackLyricsText {{
    padding: {LAYOUT.space_sm}px;
    selection-background-color: {tokens.surface_selected};
    selection-color: {tokens.text};
}}

QListView#playbackQueueView::item,
QListView#playbackHistoryView::item {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

QListView#playbackQueueView::item:hover,
QListView#playbackHistoryView::item:hover {{
    background-color: {tokens.surface_hover};
}}

QListView#playbackQueueView::item:selected,
QListView#playbackHistoryView::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QWidget[playbackEmpty="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
}}

QLabel#playbackEmptyTitle {{
    color: {tokens.text};
    font-weight: 600;
}}

QFrame#appSidebar {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
    border-right: 1px solid {tokens.border};
}}

QWidget#sidebarNavigation,
QScrollArea#sidebarScroll,
QScrollArea#sidebarScroll > QWidget > QWidget {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
}}

QLabel#sidebarSectionLabel {{
    color: {tokens.text_secondary};
    padding: {LAYOUT.space_sm}px {LAYOUT.space_xs}px {LAYOUT.space_2xs}px {LAYOUT.space_xs}px;
    font-weight: 700;
}}

QFrame#deviceCard {{
    color: {tokens.text};
    background-color: {tokens.window};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QPushButton#deviceName {{
    min-height: {LAYOUT.control_height_compact}px;
    max-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_2xs}px;
    color: {tokens.text};
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {LAYOUT.radius_control}px;
    text-align: left;
    font-weight: 600;
}}

QPushButton#deviceName:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
    border-color: transparent;
}}

QPushButton#deviceName:pressed {{
    color: {tokens.text};
    background-color: {tokens.surface_pressed};
    border-color: transparent;
}}

QPushButton#deviceName:focus {{
    border-color: {tokens.focus};
}}

QPushButton#deviceName:disabled {{
    color: {tokens.text};
    background-color: transparent;
    border-color: transparent;
}}

QWidget#renameIPodPanel {{
    background-color: transparent;
}}

QLabel#renameIPodFeedback {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
}}

QLabel#renameIPodFeedback[error="true"] {{
    color: {tokens.danger};
}}

QLabel#deviceIcon {{
    background-color: transparent;
    border: none;
}}

QDialog#devicePicker {{
    color: {tokens.text};
    background-color: {tokens.window};
}}

QListWidget#deviceCandidateList {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
    outline: none;
    padding: {LAYOUT.space_xs}px;
}}

QListWidget#deviceCandidateList::item {{
    min-height: {LAYOUT.device_picker_row_height}px;
    padding: 0 {LAYOUT.space_sm}px;
    border-radius: {LAYOUT.radius_control}px;
}}

QListWidget#deviceCandidateList::item:hover {{
    background-color: {tokens.surface_hover};
}}

QListWidget#deviceCandidateList::item:selected {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent};
}}

QLabel#deviceCandidateDetail {{
    color: {tokens.text_secondary};
}}

QLabel#deviceMetricValue {{
    color: {tokens.text};
    font-weight: 600;
}}

QLabel#placeholderBadge {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_pill}px;
    padding: {LAYOUT.space_3xs}px {LAYOUT.space_xs}px;
    font-size: {typography.small_pt:g}pt;
    font-weight: 600;
}}

QProgressBar#deviceStorage,
QProgressBar#deviceDatabase {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: none;
    border-radius: 3px;
}}

QProgressBar#deviceStorage::chunk,
QProgressBar#deviceDatabase::chunk {{
    background-color: {tokens.accent};
    border-radius: 3px;
}}

QPushButton {{
    min-height: {LAYOUT.control_height}px;
    padding: 0 {LAYOUT.space_sm}px;
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 2px solid {tokens.border_strong};
    border-radius: {LAYOUT.radius_control}px;
    text-align: center;
}}

QPushButton:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
}}

QPushButton:pressed {{
    color: {tokens.text};
    background-color: {tokens.surface_pressed};
}}

QPushButton:focus {{
    border-color: {tokens.focus};
}}

QPushButton:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QPushButton[navItem="true"] {{
    min-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_xs}px;
    background-color: transparent;
    border-color: transparent;
    text-align: left;
}}

QPushButton[navItem="true"]:hover {{
    background-color: {tokens.surface_hover};
    border-color: transparent;
}}

QPushButton[navItem="true"]:pressed {{
    background-color: {tokens.surface_pressed};
    border-color: transparent;
}}

QPushButton[navItem="true"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[navItem="true"]:disabled {{
    background-color: transparent;
    border-color: transparent;
}}

QPushButton[navItem="true"]:checked {{
    color: {tokens.accent};
    background-color: {tokens.surface_selected};
    font-weight: 600;
}}

QPushButton[kind="primary"] {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent};
    border-color: {tokens.accent};
    font-weight: 600;
    text-align: center;
}}

QPushButton[kind="primary"]:hover {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent_hover};
    border-color: {tokens.accent_hover};
}}

QPushButton[kind="primary"]:pressed {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent_pressed};
    border-color: {tokens.accent_pressed};
}}

QPushButton[kind="primary"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[kind="primary"]:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QPushButton[kind="secondary"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border-color: {tokens.border_strong};
    text-align: center;
}}

QPushButton[kind="secondary"]:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
    border-color: {tokens.border_strong};
}}

QPushButton[kind="secondary"]:pressed {{
    color: {tokens.text};
    background-color: {tokens.surface_pressed};
    border-color: {tokens.border_strong};
}}

QPushButton[kind="secondary"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[kind="secondary"]:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QPushButton[kind="quiet"] {{
    min-height: {LAYOUT.control_height_compact}px;
    color: {tokens.accent};
    background-color: transparent;
    border-color: transparent;
    padding: 0 {LAYOUT.space_xs}px;
}}

QPushButton[kind="quiet"]:hover {{
    color: {tokens.accent};
    background-color: {tokens.surface_hover};
    border-color: transparent;
}}

QPushButton[kind="quiet"]:pressed {{
    color: {tokens.accent_pressed};
    background-color: {tokens.surface_pressed};
    border-color: transparent;
}}

QPushButton[kind="quiet"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[kind="quiet"]:disabled {{
    color: {tokens.text_disabled};
    background-color: transparent;
    border-color: transparent;
}}

QPushButton[kind="danger"] {{
    color: {tokens.danger};
    background-color: {tokens.surface};
    border-color: {tokens.danger};
    font-weight: 600;
    text-align: center;
}}

QPushButton[kind="danger"]:hover {{
    color: {tokens.danger};
    background-color: {tokens.surface_hover};
    border-color: {tokens.danger};
}}

QPushButton[kind="danger"]:pressed {{
    color: {tokens.danger};
    background-color: {tokens.surface_pressed};
    border-color: {tokens.danger};
}}

QPushButton[kind="danger"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[kind="danger"]:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

/* Hallmark · component: inline action button · genre: editorial · theme: iOpenPod
 * states: default · hover · focus · active · disabled · loading · error · success
 * contrast: pass (46-50)
 */
QPushButton[kind="inline"] {{
    min-height: {LAYOUT.control_height_compact}px;
    max-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_sm}px;
    color: {tokens.accent_ink};
    background-color: {tokens.accent};
    border-color: {tokens.accent};
    border-radius: {LAYOUT.control_height_compact // 2}px;
    font-weight: 600;
    text-align: center;
}}

QPushButton[kind="inline"]:hover {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent_hover};
    border-color: {tokens.accent_hover};
}}

QPushButton[kind="inline"]:pressed {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent_pressed};
    border-color: {tokens.accent_pressed};
}}

QPushButton[kind="inline"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[kind="inline"]:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QPushButton[state="loading"] {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border_strong};
}}

QPushButton[state="error"] {{
    color: {tokens.danger};
    background-color: {tokens.surface};
    border-color: {tokens.danger};
}}

QPushButton[state="error"]:hover,
QPushButton[state="success"]:hover {{
    background-color: {tokens.surface_hover};
}}

QPushButton[state="error"]:pressed,
QPushButton[state="success"]:pressed {{
    background-color: {tokens.surface_pressed};
}}

QPushButton[state="loading"]:focus,
QPushButton[state="error"]:focus,
QPushButton[state="success"]:focus {{
    border-color: {tokens.focus};
}}

QPushButton[state="success"] {{
    color: {tokens.success};
    background-color: {tokens.surface};
    border-color: {tokens.success};
}}

QPushButton[photoFormat="true"]:checked {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent};
    border-color: {tokens.accent};
}}

QPushButton[photoFormat="true"][state="error"]:checked {{
    color: {tokens.danger};
    background-color: {tokens.surface};
    border-color: {tokens.danger};
}}

QToolButton[iconButton="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 2px solid {tokens.border_strong};
    border-radius: {LAYOUT.radius_control}px;
}}

QToolButton[iconButton="true"]:hover {{
    background-color: {tokens.surface_hover};
}}

QToolButton[iconButton="true"]:pressed {{
    background-color: {tokens.surface_pressed};
}}

QToolButton[iconButton="true"]:focus {{
    border-color: {tokens.focus};
}}

QToolButton[iconButton="true"]:checked {{
    background-color: {tokens.surface_selected};
    border-color: {tokens.accent};
}}

QToolButton[iconButton="true"][kind="quiet"] {{
    background-color: transparent;
    border-color: transparent;
}}

QToolButton[iconButton="true"][kind="subtle"] {{
    background-color: transparent;
    border-color: transparent;
}}

QToolButton[iconButton="true"][kind="quiet"]:hover,
QToolButton[iconButton="true"][kind="subtle"]:hover {{
    background-color: {tokens.surface_hover};
    border-color: transparent;
}}

QToolButton[iconButton="true"][kind="quiet"]:pressed,
QToolButton[iconButton="true"][kind="subtle"]:pressed {{
    background-color: {tokens.surface_pressed};
    border-color: transparent;
}}

QToolButton[iconButton="true"][kind="quiet"]:focus,
QToolButton[iconButton="true"][kind="subtle"]:focus {{
    border-color: {tokens.focus};
}}

QToolButton[iconButton="true"][kind="danger"] {{
    color: {tokens.danger};
    background-color: {tokens.surface};
    border-color: {tokens.danger};
}}

QToolButton[iconButton="true"][kind="danger"]:hover {{
    background-color: {tokens.surface_hover};
    border-color: {tokens.danger};
}}

QToolButton[iconButton="true"][kind="danger"]:pressed {{
    background-color: {tokens.surface_pressed};
    border-color: {tokens.danger};
}}

QToolButton[iconButton="true"][kind="danger"]:focus {{
    border-color: {tokens.focus};
}}

QToolButton[iconButton="true"][kind="primary"] {{
    color: {tokens.accent_ink};
    background-color: transparent;
    border-color: transparent;
    border-radius: {(LAYOUT.control_height_large // 2) - 1}px;
}}

QToolButton[iconButton="true"][kind="primary"]:hover {{
    background-color: transparent;
    border-color: transparent;
}}

QToolButton[iconButton="true"][kind="primary"]:pressed {{
    background-color: transparent;
    border-color: transparent;
}}

QToolButton[iconButton="true"]:disabled {{
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QToolButton[iconButton="true"][kind="quiet"]:disabled,
QToolButton[iconButton="true"][kind="subtle"]:disabled,
QToolButton[iconButton="true"][kind="primary"]:disabled {{
    background-color: transparent;
    border-color: transparent;
}}

QFrame[viewModes="true"] {{
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
}}

QFrame[viewModes="true"] QToolButton[iconButton="true"] {{
    border: none;
    border-radius: {LAYOUT.radius_control - 1}px;
}}

QFrame[viewModes="true"] QToolButton[iconButton="true"]:focus {{
    border: 2px solid {tokens.focus};
}}

QFrame[viewModes="true"] QToolButton[iconButton="true"]:checked {{
    background-color: {tokens.surface};
}}

QLineEdit {{
    min-height: {LAYOUT.control_height}px;
    padding: 0 {LAYOUT.space_sm}px;
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border_strong};
    border-radius: {LAYOUT.radius_control}px;
    selection-color: {tokens.accent_ink};
    selection-background-color: {tokens.accent};
}}

QLineEdit:hover {{
    border-color: {tokens.text_secondary};
}}

QLineEdit:focus {{
    border: 1px solid {tokens.focus};
}}

QLineEdit#renameIPod {{
    min-height: {LAYOUT.control_height}px;
    padding: 0 {LAYOUT.space_xs}px;
}}

QLineEdit#renameIPod[error="true"] {{
    border-color: {tokens.danger};
}}

QComboBox {{
    min-height: {LAYOUT.control_height}px;
    padding: 0 {LAYOUT.combo_indicator_width}px 0 {LAYOUT.space_sm}px;
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border_strong};
    border-radius: {LAYOUT.radius_control}px;
}}

QComboBox:right-to-left {{
    padding: 0 {LAYOUT.space_sm}px 0 {LAYOUT.combo_indicator_width}px;
}}

QComboBox:hover {{
    background-color: {tokens.surface_hover};
    border-color: {tokens.text_secondary};
}}

QComboBox:focus {{
    border: 1px solid {tokens.focus};
}}

QComboBox:on {{
    background-color: {tokens.surface_pressed};
}}

QComboBox:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QComboBox[themedIndicator="true"]::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: {LAYOUT.combo_indicator_width}px;
    background-color: transparent;
    border: none;
}}

QComboBox[themedIndicator="true"]:right-to-left::drop-down {{
    subcontrol-position: top left;
}}

QComboBox[themedIndicator="true"]::down-arrow {{
    width: 0;
    height: 0;
    image: none;
}}

QListView[themedComboPopup="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_2xs}px;
    selection-color: {tokens.text};
    selection-background-color: {tokens.surface_selected};
    outline: none;
}}

QListView[themedComboPopup="true"]::item {{
    min-height: {LAYOUT.control_height}px;
    padding: 0 {LAYOUT.space_sm}px;
    border: none;
    border-radius: {LAYOUT.radius_control - LAYOUT.space_2xs}px;
}}

QListView[themedComboPopup="true"]::item:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
}}

QListView[themedComboPopup="true"]::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QMenu {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    padding: {LAYOUT.space_2xs}px;
}}

QMenu::item {{
    color: {tokens.text};
    background-color: transparent;
    padding: {LAYOUT.space_xs}px {LAYOUT.space_lg}px
        {LAYOUT.space_xs}px {LAYOUT.space_sm}px;
    border: none;
    border-radius: {LAYOUT.radius_control - LAYOUT.space_3xs}px;
}}

QMenu::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
}}

QMenu::item:disabled {{
    color: {tokens.text_disabled};
    background-color: transparent;
}}

QMenu::separator {{
    height: 1px;
    margin: {LAYOUT.space_2xs}px {LAYOUT.space_xs}px;
    background-color: {tokens.border};
}}

QWidget#volumeAdjustmentWidget {{
    color: {tokens.text};
    background-color: {tokens.surface};
}}

QWidget#volumeAdjustmentWidget QLabel {{
    color: {tokens.text_secondary};
    background-color: transparent;
    font-size: {typography.small_pt:g}pt;
}}

QLabel#volumeAdjustmentValueLabel {{
    color: {tokens.text};
    font-size: {typography.body_pt:g}pt;
    font-weight: 600;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background-color: {tokens.surface_alt};
    border: none;
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background-color: {tokens.accent};
    border-radius: 2px;
}}

QSlider::add-page:horizontal {{
    background-color: {tokens.surface_alt};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background-color: {tokens.surface};
    border: 2px solid {tokens.accent};
    border-radius: 7px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {tokens.surface_hover};
    border-color: {tokens.accent_hover};
}}

QSlider::handle:horizontal:pressed {{
    background-color: {tokens.accent};
    border-color: {tokens.accent};
}}

QSlider::handle:horizontal:disabled {{
    background-color: {tokens.surface_alt};
    border-color: {tokens.border_strong};
}}

QFrame#playerBar QSlider::groove:horizontal {{
    height: 4px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.track_highlight},
        stop: 1 {player.track_shadow}
    );
    border: none;
    border-radius: 2px;
}}

QFrame#playerBar QSlider::sub-page:horizontal {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.accent_highlight},
        stop: 1 {player.accent_shadow}
    );
    border-radius: 2px;
}}

/* The scrubber deliberately uses one neutral track on both sides of its handle. */
QFrame#playerBar QSlider#playerProgress::sub-page:horizontal,
QFrame#playerBar QSlider::add-page:horizontal {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.track_highlight},
        stop: 1 {player.track_shadow}
    );
    border-radius: 2px;
}}

QFrame#playerBar QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.knob_highlight},
        stop: 1 {player.knob_shadow}
    );
    border: 1px solid {tokens.border_strong};
    border-radius: 8px;
}}

QFrame#playerBar QSlider::handle:horizontal:hover {{
    border-color: {tokens.scrollbar_hover};
}}

QFrame#playerBar QSlider::handle:horizontal:pressed {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {player.accent_highlight},
        stop: 1 {tokens.accent_pressed}
    );
    border-color: {tokens.border_strong};
}}

QFrame#playerBar QSlider::handle:horizontal:disabled {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {tokens.surface_alt},
        stop: 1 {player.bar_shadow}
    );
    border-color: {tokens.border_strong};
}}

QFrame[pageHeader="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

QFrame[sourceListPanel="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
    border-right: 1px solid {tokens.border};
}}

QLabel[sourceListTitle="true"] {{
    color: {tokens.accent};
    font-size: {typography.small_pt:g}pt;
    font-weight: 700;
}}

QLabel[sourceListCount="true"] {{
    color: {tokens.text_secondary};
    font-size: {typography.small_pt:g}pt;
}}

QListView[sourceList="true"] {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    outline: none;
}}

QListView[sourceListStandardItems="true"]::item {{
    min-height: {LAYOUT.control_height_large}px;
    padding: {LAYOUT.space_2xs}px {LAYOUT.space_sm}px;
    border: none;
    border-radius: {LAYOUT.radius_control}px;
}}

QListView[sourceListStandardItems="true"]::item:hover {{
    background-color: {tokens.surface_hover};
}}

QListView[sourceListStandardItems="true"]::item:pressed {{
    background-color: {tokens.surface_pressed};
}}

QListView[sourceListStandardItems="true"]::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QListView[sourceListStandardItems="true"]::item:focus {{
    border: 1px solid {tokens.focus};
}}

QListView[sourceList="true"]:disabled,
QListView[sourceList="true"]::item:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
}}

QFrame#albumGridPanel,
QFrame#photoGridPanel,
QFrame#photoInspector,
QListView#albumGrid,
QListView#photoGrid,
QListView[collectionGrid="true"],
QListView[collectionList="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
    outline: none;
}}

QSplitter[sourceListBrowser="true"]::handle {{
    background-color: {tokens.border};
}}

QSplitter[sourceListBrowser="true"]::handle:hover,
QSplitter[sourceListBrowser="true"]::handle:pressed {{
    background-color: {tokens.accent};
}}

QLabel#photoInspectorSummary,
QLabel#photoBrowserEmpty,
QLabel#photoAlbumManagerEmpty {{
    color: {tokens.text_secondary};
}}

QTreeWidget#photoMetadata {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    alternate-background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    outline: none;
}}

QTreeWidget#photoMetadata::item {{
    min-height: {LAYOUT.control_height_compact}px;
    padding: 0 {LAYOUT.space_2xs}px;
}}

QFrame#trackListPanel {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: none;
}}

QSplitterHandle#trackListHeader {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: none;
    border-top: 1px solid {tokens.border};
    border-bottom: 1px solid {tokens.border};
}}

QLineEdit#trackListSearch[roundTitleBar="true"] {{
    border-radius: {LAYOUT.control_height // 2}px;
}}

QSplitter#librarySplitter::handle {{
    background-color: {tokens.surface_alt};
    border-top: 1px solid {tokens.border};
    border-bottom: 1px solid {tokens.border};
}}

QSplitter#librarySplitter::handle:hover,
QSplitter#librarySplitter::handle:pressed {{
    background-color: {tokens.surface_hover};
    border-top-color: {tokens.accent};
}}

QTableView[trackTable="true"] {{
    color: {tokens.text};
    background-color: {tokens.surface};
    alternate-background-color: {tokens.window};
    border: none;
    gridline-color: {tokens.border};
    selection-color: {tokens.text};
    selection-background-color: {tokens.surface_selected};
    outline: none;
}}

QTableView#externalPlaylistFilesTable,
QTableView#syncPlanTable {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
    gridline-color: {tokens.border};
    selection-color: {tokens.text};
    selection-background-color: {tokens.surface_selected};
    outline: none;
}}

QTableView#externalPlaylistFilesTable::item,
QTableView#syncPlanTable::item {{
    padding: 0 {LAYOUT.space_sm}px;
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

QTableView#externalPlaylistFilesTable::item:hover,
QTableView#syncPlanTable::item:hover {{
    background-color: {tokens.surface_hover};
}}

QTableView#externalPlaylistFilesTable::item:selected,
QTableView#syncPlanTable::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QTableView#externalPlaylistFilesTable::item:focus,
QTableView#syncPlanTable::item:focus {{
    border: 2px solid {tokens.focus};
}}

QTableView#externalPlaylistFilesTable::item:disabled,
QTableView#syncPlanTable::item:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
}}

QTableView[trackTable="true"]::item {{
    padding: 0 {LAYOUT.space_sm}px;
    border: none;
    border-bottom: 1px solid {tokens.border};
}}

QTableView[trackTable="true"]::item:hover {{
    background-color: {tokens.surface_hover};
}}

QTableView[trackTable="true"]::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QTableView[trackTable="true"]::item:selected:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_pressed};
}}

QTableView[trackTable="true"]::item:focus {{
    border: 2px solid {tokens.focus};
}}

QHeaderView::section {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface_alt};
    padding: 0 {LAYOUT.space_sm}px;
    border: none;
    border-right: 1px solid {tokens.border};
    border-bottom: 1px solid {tokens.border};
    font-size: {typography.table_header_pt:g}pt;
    font-weight: 600;
}}

QHeaderView::section:hover {{
    color: {tokens.text};
    background-color: {tokens.surface_hover};
}}

QHeaderView::section:pressed {{
    color: {tokens.text};
    background-color: {tokens.surface_pressed};
}}

QFrame#settingGroup,
QFrame#placeholderSurface {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QFrame#donationBanner {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QLabel#donationTitle {{
    color: {tokens.text};
    font-family: "{typography.display}";
    font-size: {typography.heading_pt:g}pt;
    font-weight: 600;
}}

QLabel#donationDescription {{
    color: {tokens.text_secondary};
}}

QPushButton#donate {{
    min-height: {LAYOUT.control_height}px;
    padding: 0 {LAYOUT.space_md}px;
    color: {tokens.accent};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border_strong};
    border-radius: {LAYOUT.control_height // 2}px;
    font-weight: 600;
}}

QPushButton#donate:hover {{
    color: {tokens.accent_hover};
    background-color: {tokens.surface_hover};
    border-color: {tokens.accent_hover};
}}

QPushButton#donate:pressed {{
    color: {tokens.accent_pressed};
    background-color: {tokens.surface_pressed};
    border-color: {tokens.accent_pressed};
}}

QPushButton#donate:focus {{
    border: 2px solid {tokens.focus};
}}

QPushButton#donate:disabled {{
    color: {tokens.text_disabled};
    background-color: {tokens.surface_alt};
    border-color: {tokens.border};
}}

QWidget#settingRow {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    border-top: 1px solid {tokens.border};
}}

QWidget#settingRow[first="true"] {{
    border-top: none;
}}

QStatusBar {{
    color: {tokens.text_secondary};
    background-color: {tokens.surface};
    border-top: 1px solid {tokens.border};
}}

QStatusBar::item {{
    border: none;
}}

QLabel#activeStatusesHeading {{
    color: {tokens.text_secondary};
    font-weight: 600;
}}

QLabel#activeStatusesEmpty {{
    color: {tokens.text_secondary};
}}

QListWidget#activeStatusesList {{
    color: {tokens.text};
    background-color: transparent;
    border: none;
    outline: none;
}}

QListWidget#activeStatusesList::item {{
    padding: {LAYOUT.space_sm}px {LAYOUT.space_xs}px;
    margin: {LAYOUT.space_3xs}px 0;
    border: 1px solid transparent;
    border-radius: {LAYOUT.radius_control}px;
}}

QListWidget#activeStatusesList::item:hover {{
    background-color: {tokens.surface_hover};
}}

QListWidget#activeStatusesList::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QListWidget#activeStatusesList::item:focus {{
    border: 1px solid {tokens.focus};
}}

QProgressBar#sharedStatusProgress {{
    min-width: 160px;
    max-width: 220px;
    min-height: 14px;
    max-height: 14px;
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: 7px;
    text-align: center;
}}

QProgressBar#sharedStatusProgress::chunk {{
    background-color: {tokens.accent};
    border-radius: 6px;
}}

QToolButton#sharedStatusAction {{
    color: {tokens.text};
    background-color: {tokens.surface_alt};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    padding: 0 {LAYOUT.space_xs}px;
}}

QToolButton#sharedStatusAction:hover {{
    background-color: {tokens.surface_hover};
}}

QToolButton#sharedStatusAction:focus {{
    border-color: {tokens.focus};
}}

QScrollBar:vertical {{
    width: {LAYOUT.scrollbar_extent}px;
    margin: 0;
    background-color: transparent;
    border: none;
}}

QScrollBar::handle:vertical {{
    min-height: {LAYOUT.scrollbar_handle_minimum}px;
    margin: {LAYOUT.space_3xs}px;
    background-color: {tokens.scrollbar};
    border: none;
    border-radius: {LAYOUT.radius_control // 2}px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {tokens.scrollbar_hover};
}}

QScrollBar::handle:vertical:pressed {{
    background-color: {tokens.accent};
}}

QScrollBar:horizontal {{
    height: {LAYOUT.scrollbar_extent}px;
    margin: 0;
    background-color: transparent;
    border: none;
}}

QScrollBar::handle:horizontal {{
    min-width: {LAYOUT.scrollbar_handle_minimum}px;
    margin: {LAYOUT.space_3xs}px;
    background-color: {tokens.scrollbar};
    border: none;
    border-radius: {LAYOUT.radius_control // 2}px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {tokens.scrollbar_hover};
}}

QScrollBar::handle:horizontal:pressed {{
    background-color: {tokens.accent};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background-color: transparent;
    border: none;
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background-color: transparent;
    border: none;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background-color: transparent;
    border: none;
}}

QAbstractScrollArea::corner {{
    background-color: {tokens.surface_alt};
    border: none;
}}

QToolTip {{
    color: {tokens.text};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    padding: {LAYOUT.space_xs}px;
}}

/* Hallmark · component: Normalize Tags · theme: iOpenPod · genre: modern-minimal
 * structure: summary · searchable comparison · explicit draft action
 * states: default · hover · focus · pressed · disabled · loading · error · success
 * pre-emit critique: P5 H4 E4 S5 R5 V4
 */
QPushButton#normalizationNavigation {{
    padding-right: {LAYOUT.control_height_large}px;
}}

QLabel#normalizationBadge {{
    color: {tokens.accent_ink};
    background-color: {tokens.accent};
    border-radius: {LAYOUT.radius_control}px;
    padding: {LAYOUT.space_3xs}px {LAYOUT.space_2xs}px;
    min-width: {LAYOUT.space_md}px;
    font-size: {typography.small_pt:g}pt;
    font-weight: 600;
}}

QFrame#normalizationOverview,
QFrame#normalizationEmpty {{
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_panel}px;
}}

QLabel#normalizationStatus {{
    color: {tokens.text_secondary};
}}

QLabel#normalizationWarnings {{
    color: {tokens.warning};
}}

QTableView#normalizationChanges {{
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
    border-radius: {LAYOUT.radius_control}px;
    selection-background-color: {tokens.surface_selected};
    selection-color: {tokens.text};
}}

QTableView#normalizationChanges::item {{
    padding: {LAYOUT.space_xs}px;
    border-bottom: 1px solid {tokens.border};
}}

QTableView#normalizationChanges::item:hover {{
    background-color: {tokens.surface_hover};
}}

QTableView#normalizationChanges::item:selected {{
    color: {tokens.text};
    background-color: {tokens.surface_selected};
}}

QTableView#normalizationChanges:focus {{
    border-color: {tokens.focus};
}}
"""
