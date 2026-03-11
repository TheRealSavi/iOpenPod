"""
Sync Review Widget - GUI for reviewing and executing sync plans.

Shows the diff between PC library and iPod with:
- Tracks to add (on PC, not on iPod)
- Tracks to remove (on iPod, not on PC)
- Tracks to update (PC file changed)
- New iPod plays to scrobble
"""

from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QRectF
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QStackedWidget, QMessageBox,
    QFileDialog, QDialog, QScrollArea, QCheckBox,
)
from PyQt6.QtGui import QFont, QColor, QPainter
from pathlib import Path
import shutil

from SyncEngine.fingerprint_diff_engine import SyncPlan, SyncItem, SyncAction, FingerprintDiffEngine
from SyncEngine.pc_library import PCLibrary
from SyncEngine.eta import ETATracker

from .formatters import format_size as _format_size, format_duration_mmss as _format_duration
from ..glyphs import glyph_pixmap
from ..styles import Colors, FONT_FAMILY, Metrics, btn_css, scrollbar_css, scaled, font_scaled

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SyncWorker(QThread):
    """Background worker for computing sync diff."""
    progress = pyqtSignal(str, int, int, str)  # stage, current, total, message
    finished = pyqtSignal(object)  # SyncPlan
    error = pyqtSignal(str)

    def __init__(self, pc_folder: str, ipod_tracks: list, ipod_path: str = "",
                 supports_video: bool = True, supports_podcast: bool = True):
        super().__init__()
        self.pc_folder = pc_folder
        self.ipod_tracks = ipod_tracks
        self.ipod_path = ipod_path
        self.supports_video = supports_video
        self.supports_podcast = supports_podcast

    def run(self):
        try:
            # Initialize PC library scanner
            pc_library = PCLibrary(self.pc_folder)

            # Create fingerprint-based diff engine
            diff_engine = FingerprintDiffEngine(
                pc_library, self.ipod_path,
                supports_video=self.supports_video,
                supports_podcast=self.supports_podcast,
            )

            # Compute diff with progress callback and cancellation support
            plan = diff_engine.compute_diff(
                self.ipod_tracks,
                progress_callback=lambda stage, cur, tot, msg: self.progress.emit(stage, cur, tot, msg),
                is_cancelled=self.isInterruptionRequested,
            )

            if not self.isInterruptionRequested():
                self.finished.emit(plan)
        except Exception as e:
            if self.isInterruptionRequested():
                return  # Suppressed — user cancelled
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class SyncExecuteWorker(QThread):
    """Background worker for executing sync plan."""
    progress = pyqtSignal(object)  # SyncProgress
    finished = pyqtSignal(object)  # SyncResult
    error = pyqtSignal(str)

    def __init__(self, ipod_path: str, plan, *, skip_backup: bool = False):
        super().__init__()
        self.ipod_path = ipod_path
        self.plan = plan
        self.skip_backup = skip_backup
        self._skip_backup_requested = False

    def request_skip_backup(self):
        """Signal the worker to skip the in-progress backup and proceed to sync."""
        self._skip_backup_requested = True

    def run(self):
        try:
            from SyncEngine.sync_executor import SyncExecutor, SyncProgress
            from SyncEngine.mapping import MappingManager
            from ..settings import get_settings

            settings = get_settings()

            # ── Pre-sync backup ───────────────────────────────────────
            if not self.skip_backup:
                try:
                    self.progress.emit(SyncProgress("backup", 0, 0, message="Creating pre-sync backup…"))
                    from SyncEngine.backup_manager import (
                        BackupManager, get_device_identifier,
                        get_device_display_name,
                    )
                    from ..app import DeviceManager

                    device = DeviceManager.get_instance()
                    device_id = get_device_identifier(
                        self.ipod_path, device.discovered_ipod,
                    )
                    device_name = get_device_display_name(device.discovered_ipod)

                    manager = BackupManager(
                        device_id=device_id,
                        backup_dir=settings.backup_dir,
                        device_name=device_name,
                    )

                    def on_backup_progress(prog):
                        self.progress.emit(SyncProgress(
                            "backup", prog.current, prog.total, message=prog.message,
                        ))

                    snap = manager.create_backup(
                        ipod_path=self.ipod_path,
                        progress_callback=on_backup_progress,
                        is_cancelled=lambda: self.isInterruptionRequested() or self._skip_backup_requested,
                        max_backups=settings.max_backups,
                    )

                    if snap is None and self.isInterruptionRequested():
                        return  # Cancelled entire operation

                    # If snap is None due to skip/no-changes, GC orphaned blobs
                    if snap is None:
                        try:
                            manager.garbage_collect()
                        except Exception:
                            pass
                    else:
                        logger.info("Pre-sync backup created: %s", snap.id)
                except Exception as e:
                    logger.warning("Pre-sync backup failed (continuing sync): %s", e)
                    import traceback as _tb
                    _tb.print_exc()

            # ── Execute sync ──────────────────────────────────────────

            # Use custom transcode cache dir if configured
            cache_dir = Path(settings.transcode_cache_dir) if settings.transcode_cache_dir else None

            # Initialize executor
            executor = SyncExecutor(self.ipod_path, cache_dir=cache_dir,
                                    max_workers=settings.sync_workers)

            # Reuse the mapping loaded during compute_diff (avoids duplicate
            # load / "No mapping file found" log).  Falls back to fresh load
            # if the plan somehow doesn't carry one.
            if self.plan.mapping is not None:
                mapping = self.plan.mapping
            else:
                mapping_manager = MappingManager(self.ipod_path)
                mapping = mapping_manager.load()

            # Progress callback
            def on_progress(prog: SyncProgress):
                self.progress.emit(prog)

            # Execute sync — executor saves mapping internally on success
            result = executor.execute(
                plan=self.plan,
                mapping=mapping,
                progress_callback=on_progress,
                dry_run=False,
                is_cancelled=self.isInterruptionRequested,
                write_back_to_pc=settings.write_back_to_pc,
                aac_bitrate=settings.aac_bitrate,
            )

            self.finished.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


# ── Category color palette ──────────────────────────────────────────────────

_CAT_COLORS = {
    "add": Colors.SUCCESS,
    "remove": Colors.DANGER,
    "update_file": Colors.SYNC_CYAN,
    "metadata": Colors.SYNC_PURPLE,
    "artwork": Colors.SYNC_MAGENTA,
    "playcount": Colors.INFO,
    "rating": Colors.WARNING,
    "playlist": Colors.INFO,
    "integrity": Colors.INFO,
    "error": Colors.WARNING,
    "duplicate": Colors.SYNC_ORANGE,
}

# ── Media type classification for sync items ────────────────────────────────

# Map from media type bitmask to (label, svg_icon_name) for sync review grouping
_MEDIA_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "music": ("Music", "music"),
    "podcast": ("Podcasts", "broadcast"),
    "audiobook": ("Audiobooks", "book"),
    "video": ("Videos", "video"),
    "music_video": ("Music Videos", "video"),
    "tv_show": ("TV Shows", "monitor"),
    "other": ("Other", "music"),
}


def _classify_media_type(item: SyncItem) -> str:
    """Classify a SyncItem into a media type bucket.

    Uses pc_track for ADD actions, ipod_track for REMOVE actions.
    Returns a key from _MEDIA_TYPE_LABELS.
    """
    track = item.pc_track
    ipod = item.ipod_track

    # From PC track — check high-level flags first
    if track:
        if track.is_podcast:
            return "podcast"
        if track.is_audiobook:
            return "audiobook"
        if track.is_video:
            if track.video_kind == "tv_show":
                return "tv_show"
            if track.video_kind == "music_video":
                return "music_video"
            return "video"
        return "music"

    # From iPod track dict — use media_type bitmask
    if ipod:
        mt = ipod.get("media_type", 1)
        if mt & 0x04:
            return "podcast"
        if mt & 0x08:
            return "audiobook"
        if mt & 0x40:
            return "tv_show"
        if mt & 0x20:
            return "music_video"
        if mt & 0x02:
            return "video"
        if mt == 0 or mt & 0x01:
            return "music"

    return "music"  # default


def _group_by_media_type(items: list[SyncItem]) -> list[tuple[str, list[SyncItem]]]:
    """Group sync items by media type, returning (type_key, items) pairs.

    Returns groups in a stable display order, only including non-empty groups.
    """
    groups: dict[str, list[SyncItem]] = {}
    for item in items:
        key = _classify_media_type(item)
        groups.setdefault(key, []).append(item)

    # Return in preferred display order
    order = ["music", "podcast", "audiobook", "video", "music_video", "tv_show", "other"]
    result = []
    for key in order:
        if key in groups:
            result.append((key, groups[key]))
    return result


def _rating_to_stars(rating: int) -> str:
    """Convert rating (0-100) to star display."""
    if rating <= 0:
        return "☆☆☆☆☆"
    stars = (rating + 10) // 20
    stars = max(0, min(5, stars))
    return "★" * stars + "☆" * (5 - stars)


# ── StorageBarWidget ─────────────────────────────────────────────────────────


class _StorageBarWidget(QWidget):
    """Custom-painted segmented bar: [current used | sync delta | free]."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(scaled(10))
        self._total: int = 1
        self._current_used: int = 0
        self._sync_delta: int = 0  # positive = adding, negative = removing

    def set_values(self, total: int, current_used: int, sync_delta: int):
        self._total = max(total, 1)
        self._current_used = max(current_used, 0)
        self._sync_delta = sync_delta
        self.update()

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        r = h / 2  # corner radius

        # Background track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(Colors.BORDER_SUBTLE))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        total = self._total
        used_frac = min(self._current_used / total, 1.0)
        projected = self._current_used + self._sync_delta
        proj_frac = max(0.0, min(projected / total, 1.0))
        overflow = projected > total

        if self._sync_delta >= 0:
            # Adding: [current_used=blue][delta=green/red][free=bg]
            used_px = used_frac * w
            delta_px = proj_frac * w - used_px

            # Current used (accent blue)
            if used_px > 0:
                p.setBrush(QColor(Colors.ACCENT))
                p.drawRoundedRect(QRectF(0, 0, used_px, h), r, r)
                # Square off right edge if there's a delta after
                if delta_px > 0 and used_px > r:
                    p.drawRect(QRectF(used_px - r, 0, r, h))

            # Sync delta (green = fits, warm orange = overflow)
            if delta_px > 0:
                color = QColor(Colors.SYNC_ORANGE) if overflow else QColor(Colors.SUCCESS)
                p.setBrush(color)
                right_edge = used_px + delta_px
                p.drawRoundedRect(QRectF(used_px, 0, delta_px, h), r, r)
                # Square off left edge
                if used_px > 0:
                    p.drawRect(QRectF(used_px, 0, min(delta_px, r), h))
                # Square off right edge if hitting end
                if right_edge < w - r:
                    pass  # natural rounded right
                elif right_edge >= w:
                    p.drawRect(QRectF(max(right_edge - r, used_px), 0, r, h))

            # Overflow stripe extending to full width
            if overflow:
                p.setBrush(QColor(Colors.DANGER))
                p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
                # Redraw used and delta on top
                if used_px > 0:
                    p.setBrush(QColor(Colors.ACCENT))
                    p.drawRoundedRect(QRectF(0, 0, used_px, h), r, r)
                    if used_px > r:
                        p.drawRect(QRectF(used_px - r, 0, r, h))
                p.setBrush(QColor(Colors.SYNC_ORANGE))
                full_delta_px = w - used_px
                p.drawRoundedRect(QRectF(used_px, 0, full_delta_px, h), r, r)
                if used_px > 0:
                    p.drawRect(QRectF(used_px, 0, min(full_delta_px, r), h))
        else:
            # Removing: [projected_used=blue][freed=teal][free=bg]
            freed_frac = min(abs(self._sync_delta) / total, used_frac)
            proj_used_px = proj_frac * w
            freed_px = freed_frac * w

            if proj_used_px > 0:
                p.setBrush(QColor(Colors.ACCENT))
                p.drawRoundedRect(QRectF(0, 0, proj_used_px, h), r, r)
                if freed_px > 0 and proj_used_px > r:
                    p.drawRect(QRectF(proj_used_px - r, 0, r, h))

            if freed_px > 0:
                p.setBrush(QColor(Colors.SYNC_CYAN))  # teal for freed space
                start = proj_used_px
                p.drawRoundedRect(QRectF(start, 0, freed_px, h), r, r)
                if proj_used_px > 0:
                    p.drawRect(QRectF(start, 0, min(freed_px, r), h))

        p.end()


# ── SyncTrackRow ────────────────────────────────────────────────────────────

class SyncTrackRow(QFrame):
    """A two-line row representing one sync item inside a category card."""

    toggled = pyqtSignal()  # emitted when the checkbox changes

    def __init__(self, item: SyncItem, accent: str, checkable: bool = True, parent=None):
        super().__init__(parent)
        self.sync_item = item
        self._accent = accent
        self._checkable = checkable

        self.setStyleSheet(f"""
            SyncTrackRow {{
                background: transparent;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
                padding: 0;
            }}
            SyncTrackRow:hover {{
                background: {Colors.SURFACE};
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor if checkable else Qt.CursorShape.ArrowCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(scaled(14), scaled(8), scaled(14), scaled(8))
        row.setSpacing(scaled(10))

        # Checkbox
        self.cb = QCheckBox(self)
        self.cb.setChecked(True)
        self.cb.setVisible(checkable)
        self.cb.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: {scaled(16)}px; height: {scaled(16)}px;
                border: 2px solid {Colors.TEXT_DISABLED};
                border-radius: {scaled(3)}px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                border-color: {accent};
                background: {accent};
            }}
        """)
        self.cb.toggled.connect(self.toggled.emit)
        row.addWidget(self.cb)

        # Two-line text block
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(scaled(2))

        self.title_label = QLabel(self)
        self.title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background:transparent;")
        text_col.addWidget(self.title_label)

        self.detail_label = QLabel(self)
        self.detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.detail_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background:transparent;")
        text_col.addWidget(self.detail_label)

        row.addLayout(text_col, 1)

        # Right-side badge / duration
        self.badge_label = QLabel(self)
        self.badge_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.badge_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background:transparent;")
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.badge_label)

        self._populate(item)

    def _populate(self, item: SyncItem):
        track = item.pc_track
        ipod = item.ipod_track

        if item.action == SyncAction.ADD_TO_IPOD and track:
            self.title_label.setText(track.title or track.filename)
            parts = [track.artist or "Unknown", track.album or "Unknown"]
            if track.size:
                parts.append(_format_size(track.size))
            parts.append(track.extension.upper())
            # Media type indicator for non-music items
            if track.is_podcast:
                parts.append("Podcast")
            elif track.is_audiobook:
                parts.append("Audiobook")
            elif track.is_video:
                kind_labels = {"movie": "Movie", "tv_show": "TV Show",
                               "music_video": "Music Video"}
                parts.append(kind_labels.get(track.video_kind, "Video"))
            self.detail_label.setText(" · ".join(parts))
            self.badge_label.setText(_format_duration(track.duration_ms))

        elif item.action == SyncAction.REMOVE_FROM_IPOD:
            if ipod:
                self.title_label.setText(ipod.get("Title", "Unknown"))
                parts = [ipod.get("Artist", "Unknown"), ipod.get("Album", "Unknown")]
                if ipod.get("size"):
                    parts.append(_format_size(ipod["size"]))
                # Media type indicator for non-music items
                mt = ipod.get("media_type", 1)
                if mt & 0x04:
                    parts.append("Podcast")
                elif mt & 0x08:
                    parts.append("Audiobook")
                elif mt & 0x40:
                    parts.append("TV Show")
                elif mt & 0x20:
                    parts.append("Music Video")
                elif mt & 0x02:
                    parts.append("Movie")
                # Show removal reason from the description
                reason = item.description or ""
                if reason:
                    # Extract the reason prefix (before the colon + name)
                    reason_short = reason.split(":")[0] if ":" in reason else reason
                    parts.append(reason_short)
                self.detail_label.setText(" · ".join(parts))
                self.badge_label.setText(_format_duration(ipod.get("length", 0)))
            else:
                self.title_label.setText(item.description or "Unknown track")
                self.detail_label.setText(f"Orphaned mapping (dbid={item.dbid})")

        elif item.action == SyncAction.UPDATE_FILE and track:
            self.title_label.setText(track.title or track.filename)
            parts = [track.artist or "Unknown", track.album or "Unknown", _format_size(track.size)]
            self.detail_label.setText(" · ".join(parts))
            self.badge_label.setText(_format_duration(track.duration_ms))

        elif item.action == SyncAction.UPDATE_METADATA:
            is_gui_edit = track is None  # GUI edits have no pc_track
            if track:
                self.title_label.setText(track.title or track.filename)
                self.badge_label.setText(_format_duration(track.duration_ms))
            elif ipod:
                self.title_label.setText(ipod.get("Title", "Unknown"))
                self.badge_label.setText(_format_duration(ipod.get("length", 0)))
            changes = item.metadata_changes
            diff_parts = []
            source = "iOpenPod" if is_gui_edit else "PC"
            for field_name, (pc_val, ipod_val) in changes.items():
                diff_parts.append(f'{field_name}: "{ipod_val}" → "{pc_val}"')
            prefix = f"[{source}]  " if diff_parts else ""
            self.detail_label.setText(prefix + ("  |  ".join(diff_parts) if diff_parts else "metadata changed"))

        elif item.action == SyncAction.UPDATE_ARTWORK and track:
            self.title_label.setText(track.title or track.filename)
            new_h, old_h = item.new_art_hash, item.old_art_hash
            if not new_h and old_h:
                art_lbl = "Art removed"
            elif new_h and not old_h:
                art_lbl = "Art added"
            else:
                art_lbl = "Art changed"
            self.detail_label.setText(f"{track.artist or 'Unknown'} · {track.album or 'Unknown'} · {art_lbl}")
            self.badge_label.setText(_format_duration(track.duration_ms))

        elif item.action == SyncAction.SYNC_PLAYCOUNT and track:
            self.title_label.setText(track.title or track.filename)
            stats = []
            if item.play_count_delta > 0:
                ipod_total = ipod.get("play_count_1", 0) if ipod else 0
                prev = max(ipod_total - item.play_count_delta, 0)
                stats.append(f"{prev} → {ipod_total} plays")
            if item.skip_count_delta > 0:
                ipod_skips = ipod.get("skip_count", 0) if ipod else 0
                prev_skips = max(ipod_skips - item.skip_count_delta, 0)
                stats.append(f"{prev_skips} → {ipod_skips} skips")
            self.detail_label.setText(
                f"{track.artist or 'Unknown'} · {track.album or 'Unknown'} · {' '.join(stats)}"
            )
            self.badge_label.setText(_format_duration(track.duration_ms))

        elif item.action == SyncAction.SYNC_RATING:
            is_gui_edit = track is None
            ipod_stars = _rating_to_stars(item.ipod_rating)
            pc_stars = _rating_to_stars(item.pc_rating)
            result_stars = _rating_to_stars(item.new_rating)
            if track:
                self.title_label.setText(track.title or track.filename)
                artist = track.artist or "Unknown"
                album = track.album or "Unknown"
                self.badge_label.setText(_format_duration(track.duration_ms))
            elif ipod:
                self.title_label.setText(ipod.get("Title", "Unknown"))
                artist = ipod.get("Artist", "Unknown")
                album = ipod.get("Album", "Unknown")
                self.badge_label.setText(_format_duration(ipod.get("length", 0)))
            else:
                self.title_label.setText("Unknown")
                artist = "Unknown"
                album = "Unknown"

            # Strategy display name
            _strat_labels = {
                "ipod_wins": "iPod wins",
                "pc_wins": "PC wins",
                "highest": "Highest",
                "lowest": "Lowest",
                "average": "Average",
            }
            source = "iOpenPod" if is_gui_edit else _strat_labels.get(item.rating_strategy, item.rating_strategy or "iPod wins")

            # Determine which side "won"
            gold = _CAT_COLORS["rating"]
            dim = Colors.TEXT_TERTIARY
            pc_clr = gold if item.new_rating == item.pc_rating else dim
            ipod_clr = gold if item.new_rating == item.ipod_rating else dim

            self.detail_label.setText(
                f'<span style="color:{dim}">{artist} · {album}</span>'
                f'<br/>'
                f'<span style="color:{pc_clr}">PC {pc_stars}</span>'
                f'<span style="color:{dim}">  ·  </span>'
                f'<span style="color:{ipod_clr}">iPod {ipod_stars}</span>'
                f'<span style="color:{dim}">  →  </span>'
                f'<span style="color:{gold}">{result_stars}</span>'
                f'<span style="color:{dim}">  ({source})</span>'
            )
            self.detail_label.setTextFormat(Qt.TextFormat.RichText)
            self.detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))

        # Tooltip
        tt_lines = []
        if track:
            tt_lines += [
                f"Title: {track.title or track.filename}",
                f"Artist: {track.artist or 'Unknown'}",
                f"Album: {track.album or 'Unknown'}",
                f"Path: {track.path}",
            ]
        elif ipod:
            tt_lines += [
                f"Title: {ipod.get('Title', 'Unknown')}",
                f"Artist: {ipod.get('Artist', 'Unknown')}",
                f"iPod Location: {ipod.get('Location', 'Unknown')}",
            ]
        self.setToolTip("\n".join(tt_lines))

    def is_checked(self) -> bool:
        return self.cb.isChecked()

    def set_checked(self, state: bool):
        self.cb.setChecked(state)

    def mousePressEvent(self, a0):
        if self._checkable and a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.cb.setChecked(not self.cb.isChecked())
        super().mousePressEvent(a0)


# ── InfoRow (non-checkable, for duplicates/errors/playlists) ────────────────

class _InfoRow(QFrame):
    """Simple two-line info row (no checkbox)."""

    def __init__(self, title: str, detail: str, accent: str, badge: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _InfoRow {{
                background: transparent;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        row = QHBoxLayout(self)
        row.setContentsMargins(scaled(40), scaled(4), scaled(14), scaled(4))
        row.setSpacing(scaled(10))

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(scaled(1))

        t = QLabel(title, self)
        t.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        t.setStyleSheet(f"color: {accent}; background:transparent;")
        text_col.addWidget(t)

        if detail:
            d = QLabel(detail, self)
            d.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            d.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background:transparent;")
            d.setWordWrap(True)
            text_col.addWidget(d)

        row.addLayout(text_col, 1)

        if badge:
            b = QLabel(badge, self)
            b.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            b.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background:transparent;")
            b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(b)


# ── SyncCategoryCard ────────────────────────────────────────────────────────

class SyncCategoryCard(QFrame):
    """Collapsible card for one category of sync actions."""

    selection_changed = pyqtSignal()

    def __init__(
        self,
        icon: str,
        title: str,
        count: int,
        accent: str,
        size_bytes: int = 0,
        checkable: bool = True,
        start_expanded: bool = False,
        start_checked: bool = True,
        subtitle: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._accent = accent
        self._expanded = start_expanded
        self._checkable = checkable
        self._start_checked = start_checked
        self._track_rows: list[SyncTrackRow] = []

        self.setStyleSheet(f"""
            SyncCategoryCard {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-left: 3px solid {accent};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──────────────────────────────────────────────
        self._header_frame = QFrame(self)
        self._header_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_frame.setStyleSheet("background: transparent; border: none;")
        hdr = QHBoxLayout(self._header_frame)
        hdr.setContentsMargins(scaled(14), scaled(10), scaled(14), scaled(10))
        hdr.setSpacing(scaled(10))

        # Select-all checkbox (only for checkable cards)
        self._select_all_cb = QCheckBox(self._header_frame)
        self._select_all_cb.setChecked(start_checked)
        self._select_all_cb.setVisible(checkable)
        self._select_all_cb.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: {scaled(16)}px; height: {scaled(16)}px;
                border: 2px solid {Colors.TEXT_DISABLED};
                border-radius: {scaled(3)}px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                border-color: {accent};
                background: {accent};
            }}
            QCheckBox::indicator:indeterminate {{
                border-color: {accent};
                background: rgba({self._rgb(accent)},60);
            }}
        """)
        self._select_all_cb.stateChanged.connect(self._on_select_all_state_changed)
        hdr.addWidget(self._select_all_cb)

        # Icon
        icon_lbl = QLabel(self._header_frame)
        icon_lbl.setFixedSize(scaled(22), scaled(22))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        svg_px = glyph_pixmap(icon, font_scaled(16), accent)
        if svg_px:
            icon_lbl.setPixmap(svg_px)
        else:
            icon_lbl.setText(icon)
            icon_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_SM))
        icon_lbl.setStyleSheet("background:transparent;")
        hdr.addWidget(icon_lbl)

        # Title
        title_lbl = QLabel(title, self._header_frame)
        title_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_XL, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; background:transparent;")
        hdr.addWidget(title_lbl)

        # Title + subtitle column
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(0)
        title_col.addWidget(title_lbl)
        if subtitle:
            sub_lbl = QLabel(subtitle, self._header_frame)
            sub_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
            sub_lbl.setStyleSheet(f"color:{Colors.TEXT_TERTIARY}; background:transparent;")
            title_col.addWidget(sub_lbl)
        hdr.addLayout(title_col, 1)

        # Count pill
        count_lbl = QLabel(str(count), self._header_frame)
        count_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
        count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_lbl.setFixedHeight(scaled(20))
        count_lbl.setMinimumWidth(scaled(28))
        count_lbl.setStyleSheet(f"""
            background: {accent};
            color: {Colors.BG_DARK};
            border-radius: {scaled(10)}px;
            padding: 0 {scaled(6)}px;
        """)
        hdr.addWidget(count_lbl)

        # Size info
        if size_bytes != 0:
            sign = "+" if size_bytes > 0 else "-"
            sz_lbl = QLabel(f"{sign}{_format_size(abs(size_bytes))}", self._header_frame)
            sz_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
            sz_lbl.setStyleSheet(f"color:{accent}; background:transparent;")
            hdr.addWidget(sz_lbl)

        # Chevron
        self._chevron = QLabel("▾" if start_expanded else "▸", self._header_frame)
        self._chevron.setFont(QFont(FONT_FAMILY, Metrics.FONT_XXL))
        self._chevron.setStyleSheet(f"color:{Colors.TEXT_TERTIARY}; background:transparent;")
        hdr.addWidget(self._chevron)

        outer.addWidget(self._header_frame)

        # ── Body (expandable) ───────────────────────────────────
        self._body = QWidget(self)
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        self._body_layout = body_lay
        self._body.setVisible(start_expanded)

        outer.addWidget(self._body)

        # Make header clickable — use installEventFilter pattern
        self._header_frame.installEventFilter(self)

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _rgb(color: str) -> str:
        """Convert '#rrggbb' or 'rgba(r,g,b,a)' to 'r,g,b'."""
        if color.startswith("rgba(") or color.startswith("rgb("):
            # Extract numbers from rgb()/rgba()
            inner = color.split("(", 1)[1].rstrip(")")
            parts = [p.strip() for p in inner.split(",")]
            return f"{parts[0]},{parts[1]},{parts[2]}"
        h = color.lstrip("#")
        return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"

    def eventFilter(self, a0, a1):
        from PyQt6.QtCore import QEvent
        if a0 is self._header_frame and a1 is not None and a1.type() == QEvent.Type.MouseButtonPress:
            self._toggle_expanded()
            return True
        return super().eventFilter(a0, a1)

    def _toggle_expanded(self, _ev=None):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._chevron.setText("▾" if self._expanded else "▸")

    def _on_select_all_state_changed(self, state: int):
        # When user clicks while in mixed state, force to checked
        if state == Qt.CheckState.PartiallyChecked.value:
            return
        checked = state == Qt.CheckState.Checked.value
        self._select_all_cb.setTristate(False)
        for row in self._track_rows:
            row.cb.blockSignals(True)
            row.set_checked(checked)
            row.cb.blockSignals(False)
        self.selection_changed.emit()

    def _on_row_toggled(self):
        """Update the select-all checkbox tri-state and emit."""
        checked = sum(1 for r in self._track_rows if r.is_checked())
        total = len(self._track_rows)
        self._select_all_cb.blockSignals(True)
        if checked == total:
            self._select_all_cb.setTristate(False)
            self._select_all_cb.setChecked(True)
        elif checked == 0:
            self._select_all_cb.setTristate(False)
            self._select_all_cb.setChecked(False)
        else:
            self._select_all_cb.setTristate(True)
            self._select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self._select_all_cb.blockSignals(False)
        self.selection_changed.emit()

    # ── public API ──────────────────────────────────────────────

    def add_track_row(self, item: SyncItem) -> SyncTrackRow:
        row = SyncTrackRow(item, self._accent, checkable=self._checkable, parent=self)
        if not self._start_checked:
            row.set_checked(False)
        row.toggled.connect(self._on_row_toggled)
        self._body_layout.addWidget(row)
        self._track_rows.append(row)
        return row

    def add_info_row(self, title: str, detail: str = "", badge: str = ""):
        self._body_layout.addWidget(_InfoRow(title, detail, self._accent, badge, parent=self))

    def get_checked_items(self) -> list[SyncItem]:
        return [r.sync_item for r in self._track_rows if r.is_checked()]

    def set_all_checked(self, state: bool):
        self._select_all_cb.blockSignals(True)
        self._select_all_cb.setChecked(state)
        self._select_all_cb.blockSignals(False)
        for r in self._track_rows:
            r.cb.blockSignals(True)
            r.set_checked(state)
            r.cb.blockSignals(False)

    def checked_count(self) -> int:
        return sum(1 for r in self._track_rows if r.is_checked())

    def total_count(self) -> int:
        return len(self._track_rows)


class SyncReviewWidget(QWidget):
    """
    Main widget for reviewing sync differences.

    Shows a tree view of all pending sync actions grouped by type,
    with checkboxes to include/exclude individual items.
    """

    sync_requested = pyqtSignal(object)  # Emits list[SyncItem]
    skip_backup_signal = pyqtSignal()     # Skip the in-progress pre-sync backup
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan: Optional[SyncPlan] = None
        self._cancelled = False
        self._ipod_tracks_cache: list = []
        self._eta_tracker = ETATracker()
        self._skip_presync_backup: bool = False
        self._pending_sync_items: list = []
        self._is_auto_presync: bool = False
        self._completed_stages: list = []
        self._current_exec_stage = ""
        # Debounce timer for selection count updates (avoids O(n²) on bulk toggles)
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(0)  # fires on next event loop iteration
        self._count_timer.timeout.connect(self._do_update_selection_count)
        self._playlist_card: SyncCategoryCard | None = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(self)
        header.setStyleSheet(f"""
            QFrame {{
                background: {Colors.OVERLAY};
                border-bottom: 1px solid {Colors.BORDER};
            }}
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(scaled(16), scaled(12), scaled(16), scaled(12))

        title = QLabel("Sync Review", header)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self.summary_label = QLabel("", header)
        self.summary_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent;")
        header_layout.addWidget(self.summary_label)

        layout.addWidget(header)

        # Stacked widget for loading/content states
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack, 1)

        # Loading state
        loading_widget = QWidget(self.stack)
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.loading_label = QLabel("Scanning library...", loading_widget)
        self.loading_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: {Metrics.FONT_TITLE}px;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.loading_label)

        self.progress_bar = QProgressBar(loading_widget)
        self.progress_bar.setFixedWidth(scaled(300))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {Colors.BORDER_SUBTLE};
                border: none;
                border-radius: {scaled(4)}px;
                height: {scaled(6)}px;
            }}
            QProgressBar::chunk {{
                background: {Colors.ACCENT};
                border-radius: {scaled(3)}px;
            }}
        """)
        loading_layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        self.progress_detail = QLabel("", loading_widget)
        self.progress_detail.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; font-size: {Metrics.FONT_LG}px;")
        self.progress_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.progress_detail)

        self.eta_label = QLabel("", loading_widget)
        self.eta_label.setStyleSheet(f"color: {Colors.ACCENT}; font-size: {Metrics.FONT_LG}px;")
        self.eta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(self.eta_label)

        # Hint label (shown only during automatic pre-sync backup stage)
        self._backup_hint = QLabel(
            "Pre-sync backups are enabled. "
            "You can turn this off in Settings \u2192 Backups.",
            loading_widget,
        )
        self._backup_hint.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; font-size: {Metrics.FONT_MD}px;"
        )
        self._backup_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._backup_hint.setVisible(False)
        loading_layout.addWidget(self._backup_hint)

        self.stack.addWidget(loading_widget)  # Index 0

        # Content state — card-based scroll area
        content_widget = QWidget(self.stack)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Summary stats bar
        self._stats_bar = QFrame(content_widget)
        self._stats_bar.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        stats_lay = QHBoxLayout(self._stats_bar)
        stats_lay.setContentsMargins(scaled(16), scaled(8), scaled(16), scaled(8))
        stats_lay.setSpacing(scaled(16))
        self._stats_layout = stats_lay
        self._stats_pills: list[QLabel] = []
        stats_lay.addStretch()
        content_layout.addWidget(self._stats_bar)

        # iPod storage bar (image + name + custom segmented bar)
        self._storage_frame = QFrame(content_widget)
        self._storage_frame.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        storage_outer = QHBoxLayout(self._storage_frame)
        storage_outer.setContentsMargins(scaled(16), scaled(8), scaled(16), scaled(8))
        storage_outer.setSpacing(scaled(12))

        # iPod image
        self._storage_ipod_img = QLabel(self._storage_frame)
        self._storage_ipod_img.setFixedSize(scaled(32), scaled(32))
        self._storage_ipod_img.setStyleSheet("background: transparent;")
        storage_outer.addWidget(self._storage_ipod_img)

        # Right side: name + bar + detail text stacked vertically
        storage_right = QVBoxLayout()
        storage_right.setSpacing(scaled(3))

        # Top row: iPod name on left, detail text on right
        storage_top = QHBoxLayout()
        storage_top.setSpacing(scaled(8))
        self._storage_name = QLabel("iPod", self._storage_frame)
        self._storage_name.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        self._storage_name.setStyleSheet(f"color:{Colors.TEXT_PRIMARY}; background:transparent;")
        storage_top.addWidget(self._storage_name)
        storage_top.addStretch()
        self._storage_detail = QLabel("", self._storage_frame)
        self._storage_detail.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._storage_detail.setStyleSheet(f"color:{Colors.TEXT_TERTIARY}; background:transparent;")
        storage_top.addWidget(self._storage_detail)
        storage_right.addLayout(storage_top)

        # Custom painted segmented bar
        self._storage_bar = _StorageBarWidget(self._storage_frame)
        storage_right.addWidget(self._storage_bar)

        # Legend row beneath bar
        legend_row = QHBoxLayout()
        legend_row.setSpacing(scaled(12))
        self._legend_labels: list[QLabel] = []
        for color_hex, text in [
            (Colors.ACCENT, "Current"),
            (Colors.SUCCESS, "Sync adds"),
            (Colors.SYNC_FREED, "Freed"),
        ]:
            dot = QLabel(f"<span style='color:{color_hex};'>●</span> {text}", self._storage_frame)
            dot.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
            dot.setStyleSheet(f"color:{Colors.TEXT_TERTIARY}; background:transparent;")
            legend_row.addWidget(dot)
            self._legend_labels.append(dot)
        legend_row.addStretch()
        storage_right.addLayout(legend_row)

        storage_outer.addLayout(storage_right, 1)

        # Internal state for live recalculation
        self._disk_total: int = 0
        self._disk_used: int = 0
        self._plan_net_change: int = 0  # net change from full plan (all items)

        self._storage_frame.setVisible(False)  # shown when plan arrives
        content_layout.addWidget(self._storage_frame)

        # Scroll area for category cards
        self._scroll = QScrollArea(content_widget)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            {scrollbar_css()}
        """)

        self._cards_container = QWidget(self._scroll)
        self._cards_container.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(scaled(16), scaled(12), scaled(16), scaled(12))
        self._cards_layout.setSpacing(scaled(10))
        self._cards_layout.addStretch()  # push cards to top

        self._scroll.setWidget(self._cards_container)
        content_layout.addWidget(self._scroll, 1)

        # Track all cards for selection management
        self._category_cards: list[SyncCategoryCard] = []

        self.stack.addWidget(content_widget)  # Index 1

        # Empty state
        empty_widget = QWidget(self.stack)
        empty_layout = QVBoxLayout(empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(scaled(8))

        empty_icon = QLabel("✓", empty_widget)
        empty_icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_XL))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet(f"color: {Colors.SUCCESS}; background: transparent;")
        empty_layout.addWidget(empty_icon)

        empty_text = QLabel("Everything is in sync!", empty_widget)
        empty_text.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE))
        empty_text.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_text)

        self.empty_stats = QLabel("", empty_widget)
        self.empty_stats.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; font-size: {Metrics.FONT_XL}px;")
        self.empty_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_stats)

        self.stack.addWidget(empty_widget)  # Index 2

        # Results state (sync completion)
        results_widget = QWidget(self.stack)
        results_layout = QVBoxLayout(results_widget)
        results_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.setSpacing(scaled(12))

        self.result_icon = QLabel("", results_widget)
        self.result_icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_XL))
        self.result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.result_icon)

        self.result_title = QLabel("", results_widget)
        self.result_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO, QFont.Weight.Bold))
        self.result_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.result_title)

        self.result_details = QLabel("", results_widget)
        self.result_details.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: {Metrics.FONT_XXL}px;")
        self.result_details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_details.setWordWrap(True)
        self.result_details.setMaximumWidth(scaled(500))
        results_layout.addWidget(self.result_details, alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(results_widget)  # Index 3

        # Pre-sync backup prompt (Index 4)
        presync_widget = QWidget(self.stack)
        presync_layout = QVBoxLayout(presync_widget)
        presync_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presync_layout.setSpacing(scaled(16))

        self._presync_icon = QLabel("", presync_widget)
        _px = glyph_pixmap("download", Metrics.FONT_ICON_XL, Colors.ACCENT)
        if _px:
            self._presync_icon.setPixmap(_px)
        else:
            self._presync_icon.setText("●")
            self._presync_icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_ICON_XL))
        self._presync_icon.setStyleSheet(f"color: {Colors.ACCENT}; background: transparent;")
        self._presync_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presync_layout.addWidget(self._presync_icon)

        self._presync_title = QLabel("", presync_widget)
        self._presync_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self._presync_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        self._presync_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presync_layout.addWidget(self._presync_title)

        self._presync_text = QLabel("", presync_widget)
        self._presync_text.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: {Metrics.FONT_XL}px;")
        self._presync_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._presync_text.setWordWrap(True)
        self._presync_text.setMaximumWidth(scaled(460))
        presync_layout.addWidget(self._presync_text, alignment=Qt.AlignmentFlag.AlignCenter)

        presync_layout.addSpacing(scaled(8))

        presync_btn_row = QHBoxLayout()
        presync_btn_row.setSpacing(scaled(12))
        presync_btn_row.addStretch()

        # "Skip Backup & Sync Now" / "Sync Without Backup" — secondary action
        self._presync_skip_btn = QPushButton("Skip Backup & Sync Now", presync_widget)
        self._presync_skip_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            radius=Metrics.BORDER_RADIUS_SM,
            padding="8px 20px",
        ))
        self._presync_skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._presync_skip_btn.clicked.connect(self._presync_skip)
        presync_btn_row.addWidget(self._presync_skip_btn)

        # "Back Up & Sync" — primary action
        self._presync_backup_btn = QPushButton("Back Up & Sync", presync_widget)
        self._presync_backup_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ACCENT};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_ON_ACCENT};
                padding: {scaled(8)}px {scaled(24)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.ACCENT_LIGHT};
            }}
        """)
        self._presync_backup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._presync_backup_btn.clicked.connect(self._presync_backup)
        presync_btn_row.addWidget(self._presync_backup_btn)

        presync_btn_row.addStretch()
        presync_layout.addLayout(presync_btn_row)

        self._presync_hint = QLabel("", presync_widget)
        self._presync_hint.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; font-size: {Metrics.FONT_MD}px;"
        )
        self._presync_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        presync_layout.addWidget(self._presync_hint)

        self.stack.addWidget(presync_widget)  # Index 4

        # Footer with action buttons
        footer = QFrame(self)
        footer.setStyleSheet(f"""
            QFrame {{
                background: {Colors.OVERLAY};
                border-top: 1px solid {Colors.BORDER};
            }}
        """)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(scaled(16), scaled(10), scaled(16), scaled(10))

        # Select all / none buttons
        self.select_all_btn = QPushButton("Select All", footer)
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn = QPushButton("Select None", footer)
        self.select_none_btn.clicked.connect(self._select_none)

        for btn in [self.select_all_btn, self.select_none_btn]:
            btn.setStyleSheet(btn_css(
                bg=Colors.SURFACE_RAISED,
                bg_hover=Colors.SURFACE_ACTIVE,
                bg_press=Colors.SURFACE_ALT,
                border=f"1px solid {Colors.BORDER}",
                radius=Metrics.BORDER_RADIUS_SM,
                padding="5px 12px",
            ))

        footer_layout.addWidget(self.select_all_btn)
        footer_layout.addWidget(self.select_none_btn)

        # Expand / Collapse All
        self.expand_all_btn = QPushButton("Expand All", footer)
        self.expand_all_btn.clicked.connect(self._expand_all)
        self.collapse_all_btn = QPushButton("Collapse All", footer)
        self.collapse_all_btn.clicked.connect(self._collapse_all)
        for btn in [self.expand_all_btn, self.collapse_all_btn]:
            btn.setStyleSheet(btn_css(
                bg=Colors.SURFACE_RAISED,
                bg_hover=Colors.SURFACE_ACTIVE,
                bg_press=Colors.SURFACE_ALT,
                border=f"1px solid {Colors.BORDER}",
                radius=Metrics.BORDER_RADIUS_SM,
                padding="5px 12px",
            ))
        footer_layout.addWidget(self.expand_all_btn)
        footer_layout.addWidget(self.collapse_all_btn)

        footer_layout.addStretch()

        # Selection summary
        self.selection_label = QLabel("", footer)
        self.selection_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        footer_layout.addWidget(self.selection_label)

        footer_layout.addSpacing(scaled(20))

        # Cancel and Apply buttons
        self.cancel_btn = QPushButton("Cancel", footer)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            radius=Metrics.BORDER_RADIUS_SM,
            padding="7px 20px",
        ))

        self.apply_btn = QPushButton("Apply Sync", footer)
        self.apply_btn.clicked.connect(self._apply_sync)
        self.apply_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ACCENT};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_ON_ACCENT};
                padding: {scaled(7)}px {scaled(24)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.ACCENT_LIGHT};
            }}
            QPushButton:disabled {{
                background: {Colors.ACCENT_PRESS};
                color: {Colors.TEXT_DISABLED};
            }}
        """)

        footer_layout.addWidget(self.cancel_btn)
        footer_layout.addWidget(self.apply_btn)

        layout.addWidget(footer)

    # Map internal stage names → user-friendly labels
    _STAGE_LABELS = {
        "scan": "Scanning libraries",
        "scan_pc": "Scanning PC library",
        "scan_ipod": "Scanning iPod library",
        "load_mapping": "Loading iPod mapping",
        "integrity": "Checking iPod integrity",
        "fingerprint": "Computing fingerprints",
        "duplicates": "Checking for duplicates",
        "diff": "Comparing libraries",
        "add": "Copying tracks to iPod",
        "remove": "Removing tracks from iPod",
        "update_file": "Re-syncing changed files",
        "update_metadata": "Updating metadata",
        "quality_change": "Re-syncing quality changes",
        "sound_check": "Computing Sound Check",
        "sync_playcount": "Recording iPod play counts",
        "sync_rating": "Syncing ratings",
        "playlists": "Updating playlists",
        "write_database": "Writing iPod database",
        "backup": "Creating pre-sync backup",
        "transcode": "Transcoding",
        "scrobble": "Scrobbling to ListenBrainz",
    }

    def _friendly_stage(self, stage: str) -> str:
        return self._STAGE_LABELS.get(stage, stage.replace("_", " ").title())

    def _set_footer_for_state(self, state: str):
        """Update footer button visibility for the current state.

        States: 'loading', 'plan', 'empty', 'executing', 'results', 'presync'
        """
        show_plan_btns = (state == "plan")
        self.select_all_btn.setVisible(show_plan_btns)
        self.select_none_btn.setVisible(show_plan_btns)
        self.expand_all_btn.setVisible(show_plan_btns)
        self.collapse_all_btn.setVisible(show_plan_btns)
        self.selection_label.setVisible(show_plan_btns)
        self.apply_btn.setVisible(show_plan_btns)

        if state == "loading":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "plan":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "empty":
            self.cancel_btn.setText("Done")
            self.cancel_btn.setEnabled(True)
        elif state == "executing":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "presync":
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)
        elif state == "results":
            self.cancel_btn.setText("Done")
            self.cancel_btn.setEnabled(True)

    def show_loading(self):
        """Show loading state."""
        self.stack.setCurrentIndex(0)
        self.loading_label.setText("Scanning library...")
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.eta_label.setText("")
        self._eta_tracker.start()
        self._set_footer_for_state("loading")

    def update_progress(self, stage: str, current: int, total: int, message: str):
        """Update progress indicator."""
        friendly = self._friendly_stage(stage)
        if total > 0 and message:
            self.loading_label.setText(f"{friendly} ({current}/{total})")
            self.progress_detail.setText(message)
        else:
            self.loading_label.setText(friendly)
            self.progress_detail.setText(message)

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self._eta_tracker.update(stage, current, total)
            self.eta_label.setText(self._eta_tracker.format_stage_progress(stage, current, total))
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self.eta_label.setText("")

    def show_plan(self, plan: SyncPlan):
        """Display the sync plan as styled category cards."""
        self._plan = plan
        self._category_cards.clear()
        self._playlist_card = None
        self._storage_frame.setVisible(False)  # reset until updated

        # Clear previous cards
        while self._cards_layout.count() > 1:  # keep the stretch
            w = self._cards_layout.takeAt(0)
            wgt = w.widget() if w else None
            if wgt:
                wgt.deleteLater()

        # Clear stats pills
        stats_lay = self._stats_layout
        while stats_lay.count() > 1:  # keep stretch
            w = stats_lay.takeAt(0)
            wgt = w.widget() if w else None
            if wgt:
                wgt.deleteLater()

        if not plan.has_changes:
            self.stack.setCurrentIndex(2)  # Empty state
            stats = f"{plan.matched_tracks} tracks matched"
            if plan.total_pc_tracks:
                stats = f"{plan.total_pc_tracks} PC tracks · {plan.total_ipod_tracks} iPod tracks · {stats}"
            if plan.fingerprint_errors:
                stats += f" · <span style='color: {Colors.WARNING};'>{len(plan.fingerprint_errors)} files skipped (fingerprint errors)</span>"
            ir = plan.integrity_report
            if ir and not ir.is_clean:
                fixes = len(ir.missing_files) + len(ir.stale_mappings) + len(ir.orphan_files)
                stats += f" · <span style='color: {Colors.INFO};'>{fixes} integrity fixes applied</span>"
            self.summary_label.setText(stats)
            self.summary_label.setTextFormat(Qt.TextFormat.RichText)
            self.empty_stats.setText(stats)
            self.empty_stats.setTextFormat(Qt.TextFormat.RichText)
            self._set_footer_for_state("empty")
            return

        # ── Show content ────────────────────────────────────────────
        self.stack.setCurrentIndex(1)
        self._set_footer_for_state("plan")

        # ── Summary stats pills ─────────────────────────────────────
        def _add_pill(text: str, color: str):
            pill = QLabel(text, self._stats_bar)
            pill.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
            pill.setStyleSheet(
                f"color:{color}; background:rgba({SyncCategoryCard._rgb(color)},15); "
                f"border:1px solid rgba({SyncCategoryCard._rgb(color)},40); "
                f"border-radius:{scaled(10)}px; padding:{scaled(2)}px {scaled(10)}px;"
            )
            stats_lay.insertWidget(stats_lay.count() - 1, pill)  # before stretch

        if plan.to_add:
            _add_pill(f"+ {len(plan.to_add)} new", _CAT_COLORS["add"])
        if plan.to_remove:
            _add_pill(f"− {len(plan.to_remove)} remove", _CAT_COLORS["remove"])
        if plan.to_update_file:
            _add_pill(f"{len(plan.to_update_file)} re-sync", _CAT_COLORS["update_file"])
        if plan.to_update_metadata:
            _add_pill(f"{len(plan.to_update_metadata)} metadata", _CAT_COLORS["metadata"])
        if plan.to_update_artwork:
            _add_pill(f"{len(plan.to_update_artwork)} artwork", _CAT_COLORS["artwork"])
        if plan.to_sync_playcount:
            _add_pill(f"♪ {len(plan.to_sync_playcount)} plays", _CAT_COLORS["playcount"])
        if plan.to_sync_rating:
            _add_pill(f"★ {len(plan.to_sync_rating)} ratings", _CAT_COLORS["rating"])

        # Net size pill
        if plan.storage.bytes_to_add or plan.storage.bytes_to_remove:
            net = plan.storage.bytes_to_add - plan.storage.bytes_to_remove
            sign = "+" if net >= 0 else "-"
            _add_pill(f"net {sign}{_format_size(abs(net))}", Colors.TEXT_SECONDARY)

        # Build header summary
        total_changes = sum([
            len(plan.to_add), len(plan.to_remove),
            len(plan.to_update_metadata), len(plan.to_update_file),
            len(plan.to_update_artwork),
            len(plan.to_sync_playcount), len(plan.to_sync_rating),
        ])
        summary_text = (
            f"{plan.total_pc_tracks} PC tracks · "
            f"{plan.total_ipod_tracks} iPod tracks · "
            f"{total_changes} changes"
        )
        if plan.fingerprint_errors:
            summary_text += f" · <span style='color: {Colors.WARNING};'>{len(plan.fingerprint_errors)} skipped</span>"
        self.summary_label.setText(summary_text)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)

        # ── iPod storage bar ─────────────────────────────────────────
        self._update_storage_bar(plan)

        insert_idx = 0  # where to insert next card (before the stretch)

        def _insert_card(card: SyncCategoryCard):
            nonlocal insert_idx
            self._cards_layout.insertWidget(insert_idx, card)
            insert_idx += 1

        # ── Integrity fixes ─────────────────────────────────────────
        ir = plan.integrity_report
        if ir and not ir.is_clean:
            fix_count = len(ir.missing_files) + len(ir.stale_mappings) + len(ir.orphan_files)
            card = SyncCategoryCard("shield-warning", "Integrity Fixes (auto-repaired)", fix_count,
                                    _CAT_COLORS["integrity"], checkable=False, start_expanded=False,
                                    parent=self._cards_container)
            for t in ir.missing_files:
                card.add_info_row(t.get("Title", "Unknown"),
                                  f"{t.get('Artist', 'Unknown')} · File missing from iPod")
            for fp, dbid in ir.stale_mappings:
                card.add_info_row(f"Stale mapping (dbid={dbid})", "Removed from mapping")
            for orphan in ir.orphan_files[:20]:
                card.add_info_row(orphan.name, "Orphan file deleted")
            if len(ir.orphan_files) > 20:
                card.add_info_row(f"...and {len(ir.orphan_files) - 20} more")
            _insert_card(card)

        # ── Add to iPod ─────────────────────────────────────────────
        if plan.to_add:
            groups = _group_by_media_type(plan.to_add)
            use_subgroups = len(groups) > 1  # Only sub-group when multiple types exist

            if use_subgroups:
                for type_key, group_items in groups:
                    label, icon = _MEDIA_TYPE_LABELS[type_key]
                    group_size = sum((it.pc_track.size if it.pc_track else 0) for it in group_items)
                    card = SyncCategoryCard(
                        "plus", f"Add {label} to iPod", len(group_items),
                        _CAT_COLORS["add"], size_bytes=group_size,
                        subtitle=f"New {label.lower()} found on PC — will be copied to iPod",
                        parent=self._cards_container,
                    )
                    for item in group_items:
                        card.add_track_row(item)
                    card.selection_changed.connect(self._schedule_selection_update)
                    self._category_cards.append(card)
                    _insert_card(card)
            else:
                card = SyncCategoryCard("plus", "Add to iPod", len(plan.to_add),
                                        _CAT_COLORS["add"], size_bytes=plan.storage.bytes_to_add,
                                        subtitle="New tracks found on PC — will be copied to iPod",
                                        parent=self._cards_container)
                for item in plan.to_add:
                    card.add_track_row(item)
                card.selection_changed.connect(self._schedule_selection_update)
                self._category_cards.append(card)
                _insert_card(card)

        # ── Remove from iPod ────────────────────────────────────────
        if plan.to_remove:
            groups = _group_by_media_type(plan.to_remove)
            use_subgroups = len(groups) > 1

            if use_subgroups:
                for type_key, group_items in groups:
                    label, icon = _MEDIA_TYPE_LABELS[type_key]
                    group_size = sum(
                        (it.ipod_track.get("size", 0) if it.ipod_track else 0)
                        for it in group_items
                    )
                    card = SyncCategoryCard(
                        "minus", f"Remove {label} from iPod", len(group_items),
                        _CAT_COLORS["remove"], size_bytes=-group_size,
                        start_checked=False,
                        subtitle=f"{label} no longer in PC library — will be deleted from iPod",
                        parent=self._cards_container,
                    )
                    for item in group_items:
                        card.add_track_row(item)
                    card.selection_changed.connect(self._schedule_selection_update)
                    self._category_cards.append(card)
                    _insert_card(card)
            else:
                card = SyncCategoryCard("minus", "Remove from iPod", len(plan.to_remove),
                                        _CAT_COLORS["remove"], size_bytes=-plan.storage.bytes_to_remove,
                                        start_checked=False,
                                        subtitle="No longer in PC library — will be deleted from iPod",
                                        parent=self._cards_container)
                for item in plan.to_remove:
                    card.add_track_row(item)
                card.selection_changed.connect(self._schedule_selection_update)
                self._category_cards.append(card)
                _insert_card(card)

        # ── Re-sync changed files ───────────────────────────────────
        if plan.to_update_file:
            card = SyncCategoryCard("refresh", "Re-sync Changed Files", len(plan.to_update_file),
                                    _CAT_COLORS["update_file"], size_bytes=plan.storage.bytes_to_update,
                                    subtitle="Audio file changed on PC — will be re-copied to iPod",
                                    parent=self._cards_container)
            for item in plan.to_update_file:
                card.add_track_row(item)
            card.selection_changed.connect(self._schedule_selection_update)
            self._category_cards.append(card)
            _insert_card(card)

        # ── Update metadata ─────────────────────────────────────────
        if plan.to_update_metadata:
            card = SyncCategoryCard("edit", "Update Metadata", len(plan.to_update_metadata),
                                    _CAT_COLORS["metadata"], start_expanded=False,
                                    subtitle="Tags changed on PC — title, artist, etc. updated without re-copying",
                                    parent=self._cards_container)
            for item in plan.to_update_metadata:
                card.add_track_row(item)
            card.selection_changed.connect(self._schedule_selection_update)
            self._category_cards.append(card)
            _insert_card(card)

        # ── Update artwork ──────────────────────────────────────────
        if plan.to_update_artwork:
            card = SyncCategoryCard("download", "Update Artwork", len(plan.to_update_artwork),
                                    _CAT_COLORS["artwork"], start_expanded=False,
                                    subtitle="Album art changed on PC — will be re-extracted",
                                    parent=self._cards_container)
            for item in plan.to_update_artwork:
                card.add_track_row(item)
            card.selection_changed.connect(self._schedule_selection_update)
            self._category_cards.append(card)
            _insert_card(card)

        # ── Sync play counts ────────────────────────────────────────
        if plan.to_sync_playcount:
            card = SyncCategoryCard("music", "iPod Play Counts", len(plan.to_sync_playcount),
                                    _CAT_COLORS["playcount"], start_expanded=False,
                                    subtitle="New plays detected on iPod — will be scrobbled to ListenBrainz",
                                    parent=self._cards_container)
            for item in plan.to_sync_playcount:
                card.add_track_row(item)
            card.selection_changed.connect(self._schedule_selection_update)
            self._category_cards.append(card)
            _insert_card(card)

        # ── Sync ratings ────────────────────────────────────────────
        if plan.to_sync_rating:
            # Show active strategy in subtitle
            _strat_subtitles = {
                "ipod_wins": "iPod rating wins when different",
                "pc_wins": "PC rating wins when different",
                "highest": "Highest rating is kept",
                "lowest": "Lowest rating is kept",
                "average": "Ratings are averaged",
            }
            try:
                from ..settings import get_settings
                strat = get_settings().rating_conflict_strategy
            except Exception:
                strat = "ipod_wins"
            subtitle = _strat_subtitles.get(strat, "Rating differs between PC and iPod")
            subtitle += "  ·  Change strategy in Settings"

            card = SyncCategoryCard("star", "Rating Sync", len(plan.to_sync_rating),
                                    _CAT_COLORS["rating"], start_expanded=False,
                                    subtitle=subtitle,
                                    parent=self._cards_container)
            for item in plan.to_sync_rating:
                card.add_track_row(item)
            card.selection_changed.connect(self._schedule_selection_update)
            self._category_cards.append(card)
            _insert_card(card)

        # ── Playlist changes ────────────────────────────────────────
        pl_total = len(plan.playlists_to_add) + len(plan.playlists_to_edit) + len(plan.playlists_to_remove)
        if pl_total:
            card = SyncCategoryCard("annotation-dots", "Playlist Changes", pl_total,
                                    _CAT_COLORS["playlist"], checkable=True, start_expanded=True,
                                    subtitle="Playlist additions, updates, and removals",
                                    parent=self._cards_container)
            for pl in plan.playlists_to_add:
                pl_type = "Smart" if pl.get("smart_playlist_data") else "Regular"
                card.add_info_row(pl.get("Title", "Untitled"), f"Add · {pl_type}")
            for pl in plan.playlists_to_edit:
                pl_type = "Smart" if pl.get("smart_playlist_data") else "Regular"
                card.add_info_row(pl.get("Title", "Untitled"), f"Update · {pl_type}")
            for pl in plan.playlists_to_remove:
                card.add_info_row(pl.get("Title", "Untitled"), "Remove")
            card.selection_changed.connect(self._schedule_selection_update)
            self._category_cards.append(card)
            self._playlist_card = card
            _insert_card(card)

        # ── Fingerprint errors ──────────────────────────────────────
        if plan.fingerprint_errors:
            card = SyncCategoryCard("warning-triangle", "Fingerprint Errors", len(plan.fingerprint_errors),
                                    _CAT_COLORS["error"], checkable=False, start_expanded=False,
                                    parent=self._cards_container)
            for filepath, error_msg in plan.fingerprint_errors[:50]:
                card.add_info_row(os.path.basename(filepath), error_msg)
            if len(plan.fingerprint_errors) > 50:
                card.add_info_row(f"...and {len(plan.fingerprint_errors) - 50} more")
            _insert_card(card)

        # ── Duplicates ──────────────────────────────────────────────
        if plan.duplicates:
            dup_count = plan.duplicate_count
            card = SyncCategoryCard(
                "warning-triangle", f"Duplicates ({len(plan.duplicates)} groups)",
                dup_count, _CAT_COLORS["duplicate"], checkable=False, start_expanded=False,
                parent=self._cards_container,
            )
            for fingerprint, tracks in plan.duplicates.items():
                parts = fingerprint.split("|")
                if len(parts) >= 3:
                    group_title = f"{parts[2].title()} — {parts[0].title()}"
                else:
                    group_title = fingerprint
                card.add_info_row(group_title, f"{len(tracks)} copies · first file synced, rest skipped")
                for track in tracks:
                    short_dir = os.path.dirname(track.path).replace("\\", "/")
                    dp = short_dir.split("/")
                    short_dir = ".../" + "/".join(dp[-3:]) if len(dp) > 3 else short_dir
                    card.add_info_row(
                        f"  {track.filename}", f"{short_dir} · {_format_size(track.size)}",
                    )
            _insert_card(card)

        self._do_update_selection_count()
        self.apply_btn.setEnabled(True)
        self.apply_btn.setToolTip("")

    # ── Storage bar helper ──────────────────────────────────────────────

    def _update_storage_bar(self, plan: SyncPlan):
        """Update the iPod storage bar with model image, name, and segmented bar."""
        try:
            from ..app import DeviceManager
            from ..ipod_images import get_ipod_image
            from SyncEngine.backup_manager import get_device_display_name

            device_manager = DeviceManager.get_instance()
            ipod_path = device_manager.device_path
            if not ipod_path:
                self._storage_frame.setVisible(False)
                return

            # Disk usage
            usage = shutil.disk_usage(ipod_path)
            self._disk_total = usage.total
            self._disk_used = usage.used

            # Full plan net change (baseline before selection filtering)
            self._plan_net_change = (
                plan.storage.bytes_to_add
                + plan.storage.bytes_to_update
                - plan.storage.bytes_to_remove
            )

            # iPod model image and name
            ipod = device_manager.discovered_ipod
            if ipod:
                pix = get_ipod_image(
                    ipod.model_family, ipod.generation,
                    size=scaled(32), color=ipod.color,
                )
                if pix and not pix.isNull():
                    self._storage_ipod_img.setPixmap(pix)
                self._storage_name.setText(
                    get_device_display_name(ipod)
                )
            else:
                self._storage_name.setText("iPod")

            # Initial bar render with full plan delta
            self._render_storage(self._plan_net_change)
            self._storage_frame.setVisible(True)
        except Exception:
            self._storage_frame.setVisible(False)

    def _render_storage(self, net_change: int):
        """Render the storage bar and detail text for a given net change."""
        total = self._disk_total
        used = self._disk_used
        projected = used + net_change
        free_after = max(total - projected, 0)

        self._storage_bar.set_values(total, used, net_change)

        # Update legend visibility
        adding = net_change > 0
        removing = net_change < 0
        # legend order: Current, Sync adds, Freed
        self._legend_labels[0].setVisible(True)
        self._legend_labels[1].setVisible(adding)
        self._legend_labels[2].setVisible(removing)

        if projected > total:
            over = projected - total
            self._storage_detail.setStyleSheet(
                f"color:{Colors.DANGER}; font-size:{Metrics.FONT_MD}px; "
                f"font-family:{FONT_FAMILY}; background:transparent;"
            )
            self._storage_detail.setText(
                f"{_format_size(projected)} / {_format_size(total)} "
                f"— {_format_size(over)} over capacity!"
            )
        else:
            net_sign = "+" if net_change >= 0 else "-"
            self._storage_detail.setStyleSheet(
                f"color:{Colors.TEXT_TERTIARY}; font-size:{Metrics.FONT_MD}px; "
                f"font-family:{FONT_FAMILY}; background:transparent;"
            )
            self._storage_detail.setText(
                f"{_format_size(projected)} / {_format_size(total)} "
                f"({_format_size(free_after)} free, "
                f"net {net_sign}{_format_size(abs(net_change))})"
            )

    def show_executing(self):
        """Show executing state - similar to loading but for sync execution."""
        self._cancelled = False
        self._completed_stages = []  # Track completed stage names
        self._current_exec_stage = ""
        self._eta_tracker.start()
        self.stack.setCurrentIndex(0)  # Loading view
        self.loading_label.setText("Starting sync...")
        self.progress_detail.setText("Preparing...")
        self.progress_bar.setRange(0, 0)  # Indeterminate initially
        self.eta_label.setText("")
        self._backup_hint.setVisible(False)
        self._set_footer_for_state("executing")

    # ── Pre-sync backup prompt ──────────────────────────────────────────

    def _show_presync_prompt(self):
        """Show the pre-sync backup prompt page.

        Only shown when backup_before_sync is OFF — asks if the user
        wants to create a backup before syncing.
        """
        self._presync_title.setText("Back Up Before Syncing?")
        self._presync_text.setText(
            "Would you like to create a backup before syncing?\n"
            "This protects your iPod data in case anything goes wrong."
        )
        self._presync_backup_btn.setText("Back Up & Sync")
        self._presync_skip_btn.setText("Sync Without Backup")
        self._presync_skip_btn.setVisible(True)
        self._presync_hint.setText("")

        self.stack.setCurrentIndex(4)
        self._set_footer_for_state("presync")

    def _presync_backup(self):
        """User chose to back up before syncing (from the OFF prompt)."""
        self._is_auto_presync = False
        self._skip_presync_backup = False
        self.sync_requested.emit(self._pending_sync_items)

    def _presync_skip(self):
        """User chose to sync without backup (from the OFF prompt)."""
        self._skip_presync_backup = True
        self.sync_requested.emit(self._pending_sync_items)

    def update_execute_progress(self, prog):
        """Update progress during sync execution.

        Args:
            prog: SyncProgress object (or compatible) with stage, current,
                  total, message, worker_lines, size_progress fields.
        """
        stage = prog.stage
        current = prog.current
        total = prog.total
        message = getattr(prog, 'message', '') or ''
        worker_lines = getattr(prog, 'worker_lines', None)
        size_progress = getattr(prog, 'size_progress', None)

        # Transcode is a sub-stage — show its percentage without changing
        # the headline or stage history.
        if stage == "transcode":
            # Show transcode detail under the current stage label
            detail_parts = []
            for s in self._completed_stages[-4:]:
                detail_parts.append(f"<span style='color: {Colors.TEXT_TERTIARY};'>\u2713 {s}</span>")
            if message:
                detail_parts.append(f"<span style='color: {Colors.TEXT_PRIMARY};'>{message}</span>")
            self.progress_detail.setText("<br>".join(detail_parts))
            self.progress_detail.setTextFormat(Qt.TextFormat.RichText)
            if total > 0:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(current)
            return

        friendly = self._friendly_stage(stage)

        # Track stage transitions for the log
        if stage != self._current_exec_stage:
            if self._current_exec_stage:
                self._completed_stages.append(self._friendly_stage(self._current_exec_stage))
            self._current_exec_stage = stage

        # During the backup stage, repurpose the footer cancel as "Skip"
        is_backup = (stage == "backup")
        self._backup_hint.setVisible(is_backup and self._is_auto_presync)
        if is_backup:
            self.cancel_btn.setText("Skip Backup & Sync")
            self.cancel_btn.setEnabled(True)
        else:
            # Leaving backup stage — reset footer cancel to normal
            self.cancel_btn.setText("Cancel")
            self.cancel_btn.setEnabled(True)

        self.loading_label.setText(friendly)

        # Build detail text: completed stages + per-worker lines or message
        detail_parts = []
        for s in self._completed_stages[-4:]:  # Show last 4 completed stages
            detail_parts.append(f"<span style='color: {Colors.TEXT_TERTIARY};'>\u2713 {s}</span>")

        if worker_lines:
            for line in worker_lines:
                detail_parts.append(f"<span style='color: {Colors.TEXT_PRIMARY};'>{line}</span>")
        elif message:
            detail_parts.append(f"<span style='color: {Colors.TEXT_PRIMARY};'>{message}</span>")

        self.progress_detail.setText("<br>".join(detail_parts))
        self.progress_detail.setTextFormat(Qt.TextFormat.RichText)

        # Use size-weighted progress for the bar when available
        if size_progress is not None and total > 0:
            self.progress_bar.setRange(0, 10000)
            self.progress_bar.setValue(int(size_progress * 10000))
            # ETA from elapsed time and overall fraction — stable because
            # it doesn't depend on per-worker callback timing.
            eta = ""
            if size_progress > 0.01:
                stats = self._eta_tracker.current_stage_stats
                if stats is None:
                    self._eta_tracker.update(stage, 0, 1)
                    stats = self._eta_tracker.current_stage_stats
                if stats:
                    elapsed = stats.elapsed
                    remaining = elapsed / size_progress * (1.0 - size_progress)
                    eta = ETATracker._format_duration(remaining)
            parts = [f"{current} of {total}"]
            if eta:
                parts.append(eta)
            self.eta_label.setText(" \u00b7 ".join(parts))
        elif total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self._eta_tracker.update(stage, current, total)
            self.eta_label.setText(self._eta_tracker.format_stage_progress(stage, current, total))
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate
            self.eta_label.setText("")

    def show_result(self, result):
        """Show sync completion results in a styled view."""
        self.stack.setCurrentIndex(3)  # Results view
        self._set_footer_for_state("results")

        success = getattr(result, 'success', True)
        errors = getattr(result, 'errors', [])

        # Title
        def _set_result(glyph_name: str, fallback: str, color: str, title: str) -> None:
            px = glyph_pixmap(glyph_name, Metrics.FONT_ICON_XL, color)
            if px:
                self.result_icon.setPixmap(px)
            else:
                self.result_icon.setText(fallback)
            self.result_icon.setStyleSheet(f"color: {color}; background: transparent;")
            self.result_title.setText(title)
            self.result_title.setStyleSheet(f"color: {color};")

        if success and not errors:
            _set_result("check-circle", "✓", Colors.SUCCESS, "Sync Complete")
        elif not success:
            _set_result("close-circle", "✕", Colors.DANGER, "Sync Failed")
        elif errors:
            _set_result("warning-triangle", "△", Colors.WARNING, "Sync Completed with Errors")
        else:
            _set_result("close-circle", "✕", Colors.DANGER, "Sync Failed")

        # Build results text
        lines = []
        added = getattr(result, 'tracks_added', 0)
        removed = getattr(result, 'tracks_removed', 0)
        updated_meta = getattr(result, 'tracks_updated_metadata', 0)
        updated_file = getattr(result, 'tracks_updated_file', 0)
        playcounts = getattr(result, 'playcounts_synced', 0)
        ratings = getattr(result, 'ratings_synced', 0)

        if added:
            lines.append(f"<span style='color: {Colors.SUCCESS};'>Added {added} track{'s' if added != 1 else ''}</span>")
        if removed:
            lines.append(f"<span style='color: {Colors.DANGER};'>Removed {removed} track{'s' if removed != 1 else ''}</span>")
        if updated_file:
            lines.append(f"<span style='color: {Colors.INFO};'>Re-synced {updated_file} track{'s' if updated_file != 1 else ''}</span>")
        if updated_meta:
            lines.append(f"<span style='color: {Colors.INFO};'>Updated metadata for {updated_meta} track{'s' if updated_meta != 1 else ''}</span>")
        if playcounts:
            lines.append(f"<span style='color: {Colors.INFO};'>Recorded play counts for {playcounts} track{'s' if playcounts != 1 else ''}</span>")
        scrobbles = getattr(result, 'scrobbles_submitted', 0)
        if scrobbles:
            lines.append(f"<span style='color: {Colors.INFO};'>Scrobbled {scrobbles} play{'s' if scrobbles != 1 else ''} to ListenBrainz</span>")
        if ratings:
            lines.append(f"<span style='color: {Colors.WARNING};'>Synced ratings for {ratings} track{'s' if ratings != 1 else ''}</span>")

        if not lines:
            lines.append("No changes were made.")

        if errors:
            lines.append("")
            lines.append(f"<span style='color: {Colors.DANGER};'><b>{len(errors)} error{'s' if len(errors) != 1 else ''}:</b></span>")
            for desc, msg in errors[:10]:  # Show max 10
                lines.append(f"<span style='color: {Colors.DANGER};'>  {desc}: {msg}</span>")
            if len(errors) > 10:
                lines.append(f"<span style='color: {Colors.DANGER};'>  ...and {len(errors) - 10} more</span>")

        # Safe-eject reminder
        if success and (added or removed or updated_file or updated_meta):
            lines.append("")
            lines.append(f"<span style='color: {Colors.TEXT_TERTIARY};'>Safely eject your iPod before disconnecting.</span>")

        self.result_details.setText("<br>".join(lines))
        self.result_details.setTextFormat(Qt.TextFormat.RichText)

        # Update summary
        total_actions = added + removed + updated_file + updated_meta + playcounts + ratings
        self.summary_label.setText(f"{total_actions} action{'s' if total_actions != 1 else ''} completed")

    def show_error(self, message: str):
        """Show error message."""
        QMessageBox.critical(self, "Sync Error", message)
        self.stack.setCurrentIndex(2)
        self.summary_label.setText("Error during scan")
        self._set_footer_for_state("empty")

    def _on_cancel_clicked(self):
        """Handle cancel/done button clicks based on current state."""
        current_idx = self.stack.currentIndex()
        if current_idx == 4:
            # Pre-sync backup prompt — go back to plan view
            self.stack.setCurrentIndex(1)
            self._set_footer_for_state("plan")
        elif current_idx == 0 and not self._cancelled:
            # During loading/executing — check if we're in a backup stage
            if self._current_exec_stage == "backup":
                # Skip the in-progress backup and proceed to sync
                self.cancel_btn.setEnabled(False)
                self.cancel_btn.setText("Skipping backup…")
                self.skip_backup_signal.emit()
            else:
                # Full cancel
                self._cancelled = True
                self.cancel_btn.setEnabled(False)
                self.cancel_btn.setText("Cancelling...")
                self.cancelled.emit()
        else:
            # Plan view, empty view, or results view — just go back
            self.cancelled.emit()

    def _select_all(self):
        """Select all items in all cards."""
        for card in self._category_cards:
            card.set_all_checked(True)
        self._do_update_selection_count()

    def _select_none(self):
        """Deselect all items in all cards."""
        for card in self._category_cards:
            card.set_all_checked(False)
        self._do_update_selection_count()

    def _expand_all(self):
        """Expand all category cards."""
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            card = item.widget() if item else None
            if isinstance(card, SyncCategoryCard) and not card._expanded:
                card._toggle_expanded()

    def _collapse_all(self):
        """Collapse all category cards."""
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            card = item.widget() if item else None
            if isinstance(card, SyncCategoryCard) and card._expanded:
                card._toggle_expanded()

    def _schedule_selection_update(self):
        """Alias used by card signals."""
        self._count_timer.start()

    def _update_selection_count(self):
        """Schedule a debounced update of the selection summary label."""
        self._count_timer.start()

    def _do_update_selection_count(self):
        """Actually update the selection summary label."""
        selected = 0
        total = 0
        bytes_to_add = 0
        bytes_to_remove = 0

        for card in self._category_cards:
            for row in card._track_rows:
                if not isinstance(row, SyncTrackRow):
                    continue
                total += 1
                if row.is_checked():
                    selected += 1
                    item = row.sync_item
                    if item.action == SyncAction.ADD_TO_IPOD:
                        if item.pc_track:
                            bytes_to_add += item.pc_track.size
                    elif item.action == SyncAction.REMOVE_FROM_IPOD:
                        if item.ipod_track:
                            bytes_to_remove += item.ipod_track.get("size", 0)
                    elif item.action == SyncAction.UPDATE_FILE:
                        if item.pc_track:
                            bytes_to_add += item.pc_track.size

        # Build git-diff style size string
        size_parts = []
        if bytes_to_add > 0:
            size_parts.append(f"+{_format_size(bytes_to_add)}")
        if bytes_to_remove > 0:
            size_parts.append(f"-{_format_size(bytes_to_remove)}")

        net_change = bytes_to_add - bytes_to_remove
        if bytes_to_add > 0 or bytes_to_remove > 0:
            net_sign = "+" if net_change >= 0 else "-"
            size_parts.append(f"(net {net_sign}{_format_size(abs(net_change))})")

        size_str = " ".join(size_parts) if size_parts else ""

        label_text = f"{selected} of {total} selected"
        if size_str:
            label_text += f" · {size_str}"

        self.selection_label.setText(label_text)

        # Live-update the storage bar with the selected items' net change
        if self._disk_total > 0:
            self._render_storage(net_change)

    def _get_selected_items(self) -> list[SyncItem]:
        """Get all checked sync items from category cards."""
        selected_items: list[SyncItem] = []
        for card in self._category_cards:
            selected_items.extend(card.get_checked_items())
        return selected_items

    def _apply_sync(self):
        """Show confirmation, then pre-sync backup prompt before syncing."""
        selected_items = self._get_selected_items()

        # Check if there are playlist changes even when no track items selected
        # Playlist card is now checkable — only include if the card's select-all is checked
        playlists_selected = (
            self._playlist_card is not None
            and self._playlist_card._select_all_cb.isChecked()
            and self._plan is not None
            and bool(self._plan.playlists_to_add or self._plan.playlists_to_edit or self._plan.playlists_to_remove)
        )

        if not selected_items and not playlists_selected:
            QMessageBox.information(self, "No Selection", "Please select items to sync.")
            return

        # Confirm
        add_count = sum(1 for s in selected_items if s.action == SyncAction.ADD_TO_IPOD)
        remove_count = sum(1 for s in selected_items if s.action == SyncAction.REMOVE_FROM_IPOD)
        meta_count = sum(1 for s in selected_items if s.action == SyncAction.UPDATE_METADATA)
        file_count = sum(1 for s in selected_items if s.action == SyncAction.UPDATE_FILE)
        art_count = sum(1 for s in selected_items if s.action == SyncAction.UPDATE_ARTWORK)
        playcount_count = sum(1 for s in selected_items if s.action == SyncAction.SYNC_PLAYCOUNT)
        rating_count = sum(1 for s in selected_items if s.action == SyncAction.SYNC_RATING)

        msg_parts = []
        if add_count:
            msg_parts.append(f"Add {add_count} tracks")
        if remove_count:
            msg_parts.append(f"Remove {remove_count} tracks")
        if file_count:
            msg_parts.append(f"Re-sync {file_count} changed files")
        if meta_count:
            msg_parts.append(f"Update metadata for {meta_count} tracks")
        if art_count:
            msg_parts.append(f"Update artwork for {art_count} tracks")
        if playcount_count:
            msg_parts.append(f"Sync {playcount_count} play counts")
        if rating_count:
            msg_parts.append(f"Sync {rating_count} ratings")

        # Playlist changes (only if playlist card is checked)
        if playlists_selected and self._plan:
            pl_add = len(self._plan.playlists_to_add)
            pl_edit = len(self._plan.playlists_to_edit)
            pl_remove = len(self._plan.playlists_to_remove)
            if pl_add:
                msg_parts.append(f"Add {pl_add} playlists")
            if pl_edit:
                msg_parts.append(f"Update {pl_edit} playlists")
            if pl_remove:
                msg_parts.append(f"Remove {pl_remove} playlists")

        msg = "This will:\n• " + "\n• ".join(msg_parts) + "\n\nContinue?"

        # Styled confirmation dialog (matches dark theme)
        confirm = QDialog(self)
        confirm.setWindowTitle("Confirm Sync")
        confirm.setMinimumWidth(scaled(420))
        confirm.setStyleSheet(f"""
            QDialog {{
                background: {Colors.BG_DARK};
                color: {Colors.TEXT_PRIMARY};
            }}
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                background: transparent;
            }}
        """)
        cl = QVBoxLayout(confirm)
        cl.setContentsMargins(scaled(20), scaled(16), scaled(20), scaled(16))
        cl.setSpacing(scaled(12))

        confirm_title = QLabel("Confirm Sync", confirm)
        confirm_title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        cl.addWidget(confirm_title)

        confirm_body = QLabel(msg, confirm)
        confirm_body.setWordWrap(True)
        confirm_body.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        confirm_body.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; background:transparent;")
        cl.addWidget(confirm_body)

        cl.addSpacing(scaled(8))
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel", confirm)
        cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE_ALT,
            border=f"1px solid {Colors.BORDER}",
            radius=Metrics.BORDER_RADIUS_SM,
            padding="8px 20px",
        ))
        cancel_btn.clicked.connect(confirm.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("Apply Sync", confirm)
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ACCENT};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_ON_ACCENT};
                padding: {scaled(8)}px {scaled(24)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.ACCENT_LIGHT};
            }}
        """)
        confirm_btn.clicked.connect(confirm.accept)
        btn_row.addWidget(confirm_btn)
        cl.addLayout(btn_row)

        if confirm.exec() != QDialog.DialogCode.Accepted:
            return

        # Decide backup strategy based on setting
        from ..settings import get_settings
        settings = get_settings()

        self._pending_sync_items = selected_items

        if settings.backup_before_sync:
            # Backup is automatic — sync starts immediately with backup.
            # The user can skip via the footer cancel button on the progress screen.
            self._is_auto_presync = True
            self._skip_presync_backup = False
            self.sync_requested.emit(selected_items)
        else:
            # Backup is off — ask if they'd like to back up first.
            self._show_presync_prompt()

    _format_size = staticmethod(_format_size)
    _format_duration = staticmethod(_format_duration)


class PCFolderDialog(QDialog):
    """Dialog to select PC music folder for syncing."""

    def __init__(self, parent=None, last_folder: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Select Music Folder")
        self.setMinimumWidth(scaled(440))
        self.selected_folder = ""
        self.last_folder = last_folder

        # Dark theme stylesheet
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.BG_DARK};
                color: {Colors.TEXT_PRIMARY};
            }}
            QLabel {{
                color: {Colors.TEXT_PRIMARY};
                background: transparent;
            }}
            QPushButton {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: {scaled(6)}px {scaled(14)}px;
            }}
            QPushButton:hover {{
                background: {Colors.SURFACE_ACTIVE};
            }}
        """)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scaled(12))
        layout.setContentsMargins(scaled(20), scaled(16), scaled(20), scaled(16))

        # Title
        title = QLabel("Select Music Folder", self)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        layout.addWidget(title)

        # Instructions
        label = QLabel(
            "Select the folder containing your music library.\n"
            "This folder will be compared with your iPod to find:\n"
            "• New tracks to add\n"
            "• Removed tracks to delete\n"
            "• Updated tracks to re-sync"
        )
        label.setWordWrap(True)
        label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        label.setStyleSheet(f"color:{Colors.TEXT_SECONDARY}; background:transparent;")
        layout.addWidget(label)

        # Folder selection
        folder_layout = QHBoxLayout()

        self.folder_edit = QLabel(self.last_folder or "No folder selected")
        self.folder_edit.setStyleSheet(f"""
            QLabel {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                padding: {scaled(8)}px;
                color: {Colors.TEXT_PRIMARY};
            }}
        """)
        self.folder_edit.setWordWrap(True)
        folder_layout.addWidget(self.folder_edit, 1)

        browse_btn = QPushButton("Browse...", self)
        browse_btn.clicked.connect(self._browse)
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ACCENT};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_ON_ACCENT};
                padding: {scaled(6)}px {scaled(16)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.ACCENT_LIGHT};
            }}
        """)
        folder_layout.addWidget(browse_btn)

        layout.addLayout(folder_layout)

        layout.addSpacing(scaled(8))

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("OK", self)
        ok_btn.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.ACCENT};
                border: none;
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_ON_ACCENT};
                padding: {scaled(6)}px {scaled(20)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {Colors.ACCENT_LIGHT};
            }}
        """)
        ok_btn.clicked.connect(self._accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Music Folder",
            self.last_folder,
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self.selected_folder = folder
            self.folder_edit.setText(folder)

    def _accept(self):
        if not self.selected_folder and self.last_folder:
            self.selected_folder = self.last_folder

        if not self.selected_folder:
            QMessageBox.warning(self, "No Folder", "Please select a music folder.")
            return

        if not os.path.isdir(self.selected_folder):
            QMessageBox.warning(self, "Invalid Folder", "The selected folder does not exist.")
            return

        self.accept()
