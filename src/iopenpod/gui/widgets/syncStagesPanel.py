"""Sync stages panel — left-hand-side checklist of sync pipeline steps.

Each time we sync an iPod, we go through a set of phases to update the iPod (and back-sync ratings).

This panel is used to show a list of which stage we are up to in the sync process.

The goal of this is so that we can have a UI that looks like


+-------------------------------------------+
| 1. Stage 1                                |
| 2. Stage 2           [Stage Title Area]   |
| 3. Stage 3               [Progress]       |
| ...                                       |
+-------------------------------------------+
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iopenpod.sync_progress_stages import PIPELINE_STAGE_ROWS

from ..styles import FONT_FAMILY, Colors, Metrics

# ── Pure data model ─────────────────────────────────────────────────────


class StageStatus(StrEnum):
    """Per-stage display state in the checklist."""

    PENDING = "pending"  # haven't reached this stage yet
    CURRENT = "current"  # actively running right now
    DONE = "done"  # completed successfully
    SKIPPED = "skipped"  # the executor moved past without firing this stage
    FAILED = "failed"  # the sync ended in failure while this stage was active


@dataclass(frozen=True)
class SyncStage:
    """One row in the checklist.

    *aliases* are the stage IDs the executor may emit while this checklist
    row should be shown as CURRENT.  For example, the executor distinguishes
    ``scrobble_listenbrainz`` and ``scrobble_lastfm`` but the user just sees
    a single "Scrobble plays" row that stays active across both.
    """

    stage_id: str
    label: str
    aliases: frozenset[str] = field(default_factory=frozenset)

    def matches(self, stage: str) -> bool:
        return stage == self.stage_id or stage in self.aliases


# Canonical full-sync pipeline, in the order the executor runs the phases.
# Stages without an entry here are silently ignored by the state machine.
# e.g. ``transcode``, which is a sub-stage of ``add``
DEFAULT_PIPELINE: tuple[SyncStage, ...] = (
    *(
        SyncStage(row.stage_id, row.label, row.aliases)
        for row in PIPELINE_STAGE_ROWS
    ),
)


def _index_for_stage(pipeline: Sequence[SyncStage], stage: str) -> int | None:
    """Return the pipeline index whose row this raw stage belongs to."""
    for idx, step in enumerate(pipeline):
        if step.matches(stage):
            return idx
    return None


def init_states(pipeline: Sequence[SyncStage]) -> dict[str, StageStatus]:
    """Build a fresh PENDING state map keyed by ``stage_id``."""
    return {step.stage_id: StageStatus.PENDING for step in pipeline}


def apply_stage_event(
    pipeline: Sequence[SyncStage],
    states: Mapping[str, StageStatus],
    active: str | None,
    stage: str,
) -> tuple[dict[str, StageStatus], str | None]:
    """Transition the checklist in response to one executor stage event.

    Returns ``(new_states, new_active)``.  Inputs are not mutated.

    Rules:
      * If ``stage`` doesn't map to any pipeline row, no-op (caller will
        keep the current state — useful for sub-stages like ``transcode``).
      * If the matched row is already the active one, no-op.
      * Otherwise:
          - the previous active row (if any) becomes ``DONE``,
          - any still-``PENDING`` rows strictly between the previous and
            new positions become ``SKIPPED`` (the executor passed them by
            without firing them, so they had no work),
          - the new row becomes ``CURRENT``.
    """
    new_idx = _index_for_stage(pipeline, stage)
    if new_idx is None:
        return dict(states), active

    new_step_id = pipeline[new_idx].stage_id
    if active == new_step_id:
        return dict(states), active

    new_states = dict(states)
    prev_idx: int | None = None
    if active is not None:
        prev_idx = _index_for_stage(pipeline, active)
        if prev_idx is not None:
            new_states[pipeline[prev_idx].stage_id] = StageStatus.DONE

    # Steps strictly between the previous and new position get SKIPPED.
    # Forward jumps only — if the executor ever emitted an earlier stage
    # after a later one (it doesn't today) we'd just retread that row.
    if prev_idx is None or new_idx > prev_idx:
        start = (prev_idx + 1) if prev_idx is not None else 0
        for between_idx in range(start, new_idx):
            row_id = pipeline[between_idx].stage_id
            if new_states.get(row_id) == StageStatus.PENDING:
                new_states[row_id] = StageStatus.SKIPPED

    new_states[new_step_id] = StageStatus.CURRENT
    return new_states, new_step_id


def finalize_states_for_end_of_sync(
    pipeline: Sequence[SyncStage],
    states: Mapping[str, StageStatus],
    active: str | None,
    *,
    failed: bool = False,
) -> dict[str, StageStatus]:
    """End-of-sync cleanup.

    The currently-active row is marked ``DONE`` (or ``FAILED`` if the sync
    finished unsuccessfully while it was running), and any rows still in
    ``PENDING`` become ``SKIPPED``.
    """
    new_states = dict(states)
    if active is not None:
        new_states[active] = StageStatus.FAILED if failed else StageStatus.DONE
    for step in pipeline:
        if new_states.get(step.stage_id) == StageStatus.PENDING:
            new_states[step.stage_id] = StageStatus.SKIPPED
    return new_states


# ── Qt widget ───────────────────────────────────────────────────────────


# Per-status mapping from status to glyph render
_GLYPH_FOR_STATUS: dict[StageStatus, str] = {
    StageStatus.PENDING: "○",
    StageStatus.CURRENT: "●",
    StageStatus.DONE: "✓",
    StageStatus.SKIPPED: "–",
    StageStatus.FAILED: "✕",
}

_TOOLTIP_FOR_STATUS: dict[StageStatus, str] = {
    StageStatus.PENDING: "Waiting",
    StageStatus.CURRENT: "Running",
    StageStatus.DONE: "Done",
    StageStatus.SKIPPED: "No work needed",
    StageStatus.FAILED: "Failed",
}


class _StageRow(QFrame):
    """Single checklist row: glyph + label."""

    def __init__(self, step: SyncStage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stageRow")
        self._step = step
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(10)

        # Fixed-width glyph column so labels line up regardless of which
        # status icon is currently rendered.
        self._glyph = QLabel(_GLYPH_FOR_STATUS[StageStatus.PENDING], self)
        self._glyph.setFixedWidth(18)
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        layout.addWidget(self._glyph)

        self._label = QLabel(step.label, self)
        self._label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        self.set_status(StageStatus.PENDING)

    @property
    def stage_id(self) -> str:
        return self._step.stage_id

    def set_status(self, status: StageStatus) -> None:
        self._glyph.setText(_GLYPH_FOR_STATUS[status])
        glyph_color, text_color, bold = _row_colors(status)
        background, border_left = _row_frame_style(status)
        self.setToolTip(f"{self._step.label}: {_TOOLTIP_FOR_STATUS[status]}")
        self.setStyleSheet(
            "QFrame#stageRow {"
            f"background: {background};"
            "border: 1px solid transparent;"
            f"border-left: 3px solid {border_left};"
            "border-radius: 6px;"
            "}"
        )
        self._glyph.setStyleSheet(f"color: {glyph_color}; background: transparent;")
        self._label.setStyleSheet(f"color: {text_color}; background: transparent;")
        font = self._label.font()
        font.setBold(bold)
        font.setItalic(status == StageStatus.SKIPPED)
        self._label.setFont(font)


def _row_colors(status: StageStatus) -> tuple[str, str, bool]:
    """Return ``(glyph_color, label_color, bold_label)`` for a status."""
    if status == StageStatus.CURRENT:
        return Colors.ACCENT, Colors.TEXT_PRIMARY, True
    if status == StageStatus.DONE:
        return Colors.SUCCESS, Colors.TEXT_SECONDARY, False
    if status == StageStatus.FAILED:
        return Colors.DANGER, Colors.TEXT_PRIMARY, True
    if status == StageStatus.SKIPPED:
        return Colors.TEXT_DISABLED, Colors.TEXT_DISABLED, False
    # PENDING
    return Colors.TEXT_TERTIARY, Colors.TEXT_TERTIARY, False


def _row_frame_style(status: StageStatus) -> tuple[str, str]:
    """Return ``(background, left_border)`` for a row frame."""
    if status == StageStatus.CURRENT:
        return Colors.ACCENT_MUTED, Colors.ACCENT
    if status == StageStatus.FAILED:
        return Colors.DANGER_DIM, Colors.DANGER
    return "transparent", "transparent"


class SyncStagesPanel(QWidget):
    """Left-side checklist that ticks off sync stages as they complete.

    The widget owns the state machine state and rebuilds rows lazily when
    a different pipeline is supplied.  External callers should treat it
    as fire-and-forget:

      * call :meth:`reset_for_pipeline` (or pass the pipeline at construct
        time) before a sync run starts,
      * call :meth:`notify_stage` from the progress callback for every
        ``SyncProgress.stage`` value,
      * call :meth:`finalize` once when the run ends.
    """

    def __init__(
        self,
        pipeline: Sequence[SyncStage] = DEFAULT_PIPELINE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncStagesPanel")
        self.setStyleSheet(f"#syncStagesPanel {{ background: {Colors.SURFACE}; border-right: 1px solid {Colors.BORDER_SUBTLE};}}")

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(20, 24, 20, 24)
        self._outer.setSpacing(10)

        self._title = QLabel("Sync steps", self)
        self._title.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        self._outer.addWidget(self._title)

        self._rows_container = QWidget(self)
        self._rows_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._outer.addWidget(self._rows_container, 1)

        self._pipeline: tuple[SyncStage, ...] = ()
        self._states: dict[str, StageStatus] = {}
        self._active: str | None = None
        self._rows: dict[str, _StageRow] = {}

        self.reset_for_pipeline(pipeline)

    # ── Public API ──────────────────────────────────────────────────

    def reset_for_pipeline(self, pipeline: Sequence[SyncStage]) -> None:
        """Replace the row set and reset all rows to ``PENDING``."""
        self._pipeline = tuple(pipeline)
        self._states = init_states(self._pipeline)
        self._active = None

        # Rebuild rows from scratch — pipelines are short (~13 entries).
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for step in self._pipeline:
            row = _StageRow(step, self._rows_container)
            self._rows_layout.addWidget(row, 1)
            self._rows[step.stage_id] = row

    def notify_stage(self, stage: str) -> None:
        """Apply one stage event from the executor's progress callback."""
        self._states, self._active = apply_stage_event(
            self._pipeline,
            self._states,
            self._active,
            stage,
        )
        self._refresh_rows()

    def end_of_sync(self, *, failed: bool = False) -> None:
        """Mark the run as finished — active becomes DONE/FAILED, PENDING becomes SKIPPED."""
        self._states = finalize_states_for_end_of_sync(
            self._pipeline,
            self._states,
            self._active,
            failed=failed,
        )
        self._active = None
        self._refresh_rows()

    # ── Test introspection ──────────────────────────────────────────
    # Exposed just for tests

    def states_snapshot(self) -> dict[str, StageStatus]:
        return dict(self._states)

    def active_stage(self) -> str | None:
        return self._active

    # ── Internal ────────────────────────────────────────────────────

    def _refresh_rows(self) -> None:
        for stage_id, row in self._rows.items():
            row.set_status(self._states.get(stage_id, StageStatus.PENDING))


__all__ = [
    "DEFAULT_PIPELINE",
    "StageStatus",
    "SyncStage",
    "SyncStagesPanel",
    "apply_stage_event",
    "finalize_states_for_end_of_sync",
    "init_states",
]
