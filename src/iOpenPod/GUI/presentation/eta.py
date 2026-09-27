"""Shared, deliberately approximate wording for stage ETA evidence."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication

from iOpenPod.app.core.eta import EtaState

if TYPE_CHECKING:
    from iOpenPod.app.core.eta import EtaEstimate


def eta_text(estimate: EtaEstimate) -> str:
    """Describe the current stage without claiming whole-operation completion."""

    match estimate.state:
        case EtaState.UNKNOWN_TOTAL:
            return ""
        case EtaState.WARMING_UP:
            return QCoreApplication.translate("Eta", "Estimating time for this stage…")
        case EtaState.STALLED:
            return QCoreApplication.translate("Eta", "Waiting for progress…")
        case EtaState.PAUSED:
            return QCoreApplication.translate("Eta", "Paused")
        case EtaState.COMPLETE:
            return QCoreApplication.translate("Eta", "Finishing this stage…")
        case EtaState.ESTIMATING:
            remaining = estimate.remaining_seconds
            lower, upper = estimate.lower_seconds, estimate.upper_seconds
            assert remaining is not None and lower is not None and upper is not None
            if upper / lower >= 1.75 and _duration(lower) != _duration(upper):
                return QCoreApplication.translate(
                    "Eta", "About {lower} to {upper} left in this stage"
                ).format(lower=_duration(lower), upper=_duration(upper))
            return QCoreApplication.translate(
                "Eta", "About {duration} left in this stage"
            ).format(duration=_duration(remaining))


def _duration(seconds: float) -> str:
    if seconds < 60:
        rounded = max(5, math.ceil(seconds / 5) * 5)
        if rounded < 60:
            return QCoreApplication.translate("Eta", "{seconds}s").format(
                seconds=rounded
            )
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return QCoreApplication.translate("Eta", "{minutes}m").format(minutes=minutes)
    hours, minutes = divmod(minutes, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return QCoreApplication.translate("Eta", "{days}d {hours}h").format(
            days=days, hours=hours
        )
    return QCoreApplication.translate("Eta", "{hours}h {minutes}m").format(
        hours=hours, minutes=minutes
    )
