"""Choose an optional Host system-media session at application composition."""

import logging
import sys

from iOpenPod.app.playback.system_media.session import (
    NullSystemMediaSession,
    SystemMediaSession,
)

logger = logging.getLogger(__name__)


def create_system_media_session(
    *,
    platform_name: str | None = None,
    window_id: int | None = None,
) -> SystemMediaSession:
    """Create the current Host adapter, falling back when it is unavailable."""

    resolved_platform = platform_name or sys.platform
    if resolved_platform == "darwin":
        try:
            from iOpenPod.app.playback.system_media.macos import (
                MacOSSystemMediaSession,
            )

            return MacOSSystemMediaSession()
        except Exception:
            logger.warning(
                "macOS system-media integration is unavailable; playback will continue",
                exc_info=True,
            )
    elif resolved_platform == "win32":
        if window_id is None:
            logger.warning(
                "Windows system-media integration requires a top-level window handle"
            )
        else:
            try:
                from iOpenPod.app.playback.system_media.windows import (
                    WindowsSystemMediaSession,
                )

                return WindowsSystemMediaSession(window_id)
            except Exception:
                logger.warning(
                    "Windows system-media integration is unavailable; playback will continue",
                    exc_info=True,
                )
    elif resolved_platform.startswith("linux"):
        try:
            from iOpenPod.app.playback.system_media.linux import (
                LinuxSystemMediaSession,
            )

            return LinuxSystemMediaSession()
        except Exception:
            logger.warning(
                "Linux system-media integration is unavailable; playback will continue",
                exc_info=True,
            )
    return NullSystemMediaSession()


__all__ = ["create_system_media_session"]
