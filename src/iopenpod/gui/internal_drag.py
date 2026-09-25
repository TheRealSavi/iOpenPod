from __future__ import annotations

IOP_EXPORT_DRAG_MIME = "application/x-iopenpod-track-export"
IOP_PLAYLIST_DRAG_MIME = "application/x-iopenpod-playlist"


def is_iopenpod_export_drag(mime: object) -> bool:
    has_format = getattr(mime, "hasFormat", None)
    if not callable(has_format):
        return False
    try:
        return bool(has_format(IOP_EXPORT_DRAG_MIME))
    except Exception:
        return False


def is_iopenpod_playlist_drag(mime: object) -> bool:
    has_format = getattr(mime, "hasFormat", None)
    if not callable(has_format):
        return False
    try:
        return bool(has_format(IOP_PLAYLIST_DRAG_MIME))
    except Exception:
        return False
