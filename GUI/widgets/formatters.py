"""
Shared formatting utilities for the GUI.

Provides consistent human-readable formatting for sizes, durations, ratings, etc.
Import these instead of defining local static _format_* methods.
"""


def format_size(bytes_val: int) -> str:
    """Format bytes as human-readable string (B, KB, MB, GB)."""
    if not bytes_val or bytes_val <= 0:
        return ""
    val = float(bytes_val)
    if val < 1024:
        return f"{int(val)} B"
    elif val < 1024 * 1024:
        return f"{val / 1024:.1f} KB"
    elif val < 1024 * 1024 * 1024:
        return f"{val / (1024 * 1024):.1f} MB"
    return f"{val / (1024 * 1024 * 1024):.1f} GB"


def format_duration_mmss(ms: int) -> str:
    """Format milliseconds as M:SS or H:MM:SS for individual tracks."""
    if not ms or ms <= 0:
        return "—"
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_duration_human(ms: int) -> str:
    """Format milliseconds as 'X hours' or 'X min' for aggregate displays."""
    if not ms or ms <= 0:
        return "0 min"
    hours = ms / (1000 * 60 * 60)
    if hours >= 1:
        return f"{hours:.1f} hours"
    minutes = ms / (1000 * 60)
    return f"{minutes:.0f} min"


def format_rating(rating: int) -> str:
    """Format rating (0-100) as stars (★☆). Returns empty string for 0."""
    if not rating or rating <= 0:
        return ""
    stars = min(5, rating // 20)
    return "★" * stars + "☆" * (5 - stars)
