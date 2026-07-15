"""Adapters that translate app settings into sync-engine option objects."""

from __future__ import annotations

from typing import Any

from iopenpod.sync.transcoder import TranscodeOptions


def build_transcode_options(settings: Any) -> TranscodeOptions:
    """Build explicit transcode options from the current effective settings."""

    return TranscodeOptions.from_settings(settings)
