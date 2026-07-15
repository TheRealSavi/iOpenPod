"""Typed application error hierarchy for runtime and orchestration layers."""

from __future__ import annotations


class AppError(Exception):
    """Base class for typed application errors."""


class AppConfigurationError(AppError):
    """Raised when app configuration is invalid or incomplete."""


class AppStateError(AppError):
    """Raised when runtime state is inconsistent or unavailable."""


class BackgroundJobError(AppError):
    """Raised when a background job fails before delivering a result."""
