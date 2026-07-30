"""Subsonic-compatible server sync source.

Provides music sync from Subsonic-compatible servers (Navidrome, Airsonic,
Gonic, original Subsonic) to iPod devices.  Mirrors the structure of
``iopenpod.podcasts``: a self-contained source module that builds a
``SyncPlan`` directly (bypassing the PC-library diff engine) and streams
track bytes during execution.
"""

from .client import SubsonicClient, SubsonicConnectionError
from .plan_builder import build_subsonic_sync_plan

__all__ = [
    "SubsonicClient",
    "SubsonicConnectionError",
    "build_subsonic_sync_plan",
]
