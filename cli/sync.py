"""Core sync orchestration for the iopenpod-sync CLI.

Drives the Qt-free SyncEngine to:
  1. Detect the connected iPod
  2. Load its iTunesDB (tracks + playlists)
  3. Run a plan+execute cycle for music (local folder → selected playlists)
  4. Download and sync configured podcast feeds
  5. Optionally pull ratings/playcounts back to PC file tags
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from cli.config import SyncConfig
from cli.device import find_ipod

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------

def _progress_cb(progress: Any) -> None:
    stage = str(getattr(progress, "stage", ""))
    current = getattr(progress, "current", 0) or 0
    total = getattr(progress, "total", 0) or 0
    message = getattr(progress, "message", "") or ""

    if total and current:
        bar = f" [{current}/{total}]"
    else:
        bar = ""

    if message:
        print(f"  [{stage}]{bar} {message}", flush=True)


# ---------------------------------------------------------------------------
# Music sync
# ---------------------------------------------------------------------------

def _build_pc_folders(config: SyncConfig) -> tuple[Any, ...]:
    """Build pc_folders entries from the config's music_path.

    When specific playlists are configured, we request both "music" and
    "playlists" media types so the engine discovers the M3U files.
    Without playlists, we scan for music only.
    """
    from infrastructure.media_folders import MediaFolderEntry

    music_path = str(Path(config.music_path).expanduser())
    media_types: tuple[str, ...]
    if config.playlists:
        media_types = ("music", "playlists")
    else:
        media_types = ("music",)

    return (MediaFolderEntry(directory=music_path, recurse=True, media_types=media_types),)


def _resolve_playlist_paths(config: SyncConfig) -> frozenset[str] | None:
    """Convert configured playlist names/paths to stable path keys.

    If the user listed playlist files (absolute or relative to music_path),
    we pass them as selected_playlist_paths so the engine syncs only those.
    Returns None to sync all discovered playlists.
    """
    if not config.playlists:
        return None

    from SyncEngine.sync_playlist_files import normalize_sync_playlist_path

    music_root = Path(config.music_path).expanduser()
    resolved: set[str] = set()
    for pl in config.playlists:
        p = Path(pl).expanduser()
        if not p.is_absolute():
            p = music_root / p
        resolved.add(normalize_sync_playlist_path(str(p)))

    return frozenset(resolved)


def run_music_sync(
    ipod_path: str,
    ipod_tracks: tuple[dict, ...],
    existing_playlists: tuple[dict, ...],
    device_info: Any,
    device_capabilities: Any,
    config: SyncConfig,
    dry_run: bool = False,
) -> bool:
    from SyncEngine.core.engine import SyncEngine
    from SyncEngine.core.models import (
        EngineOperation,
        EngineOptions,
        EngineRequest,
    )
    from SyncEngine.mapping import MappingManager

    pc_folders = _build_pc_folders(config)
    selected_playlist_paths = _resolve_playlist_paths(config)

    print("\n[Music] Planning sync...")
    plan_request = EngineRequest(
        operation=EngineOperation.PLAN,
        ipod_path=ipod_path,
        pc_folders=pc_folders,
        ipod_tracks=ipod_tracks,
        existing_playlists=existing_playlists,
        options=EngineOptions(
            rating_strategy=config.rating_strategy,
            selected_playlist_paths=selected_playlist_paths,
            write_back_to_pc=config.pull_ratings or config.pull_playcounts,
            dry_run=dry_run,
        ),
        progress_callback=_progress_cb,
        device_info=device_info,
        device_capabilities=device_capabilities,
    )

    engine = SyncEngine()
    plan_outcome = engine.run(plan_request)

    if not plan_outcome.success:
        for d in plan_outcome.diagnostics:
            if d.fatal:
                logger.error("Plan failed: %s", d.message)
        return False

    plan = plan_outcome.result
    if plan is None:
        logger.error("Planner returned no plan")
        return False

    # Summarise the plan
    adds = sum(1 for item in getattr(plan, "to_add", []))
    removes = sum(1 for item in getattr(plan, "to_remove", []))
    updates = sum(1 for item in getattr(plan, "to_update", []))
    print(f"[Music] Plan: +{adds} add  -{removes} remove  ~{updates} update")

    if dry_run:
        print("[Music] Dry run — skipping execution.")
        return True

    if adds == 0 and removes == 0 and updates == 0:
        print("[Music] Already in sync.")
        return True

    print("[Music] Executing sync...")
    mapping = MappingManager(ipod_path).load()
    exec_request = EngineRequest(
        operation=EngineOperation.EXECUTE,
        ipod_path=ipod_path,
        ipod_tracks=ipod_tracks,
        existing_playlists=existing_playlists,
        plan=plan,
        mapping=mapping,
        options=EngineOptions(
            rating_strategy=config.rating_strategy,
            write_back_to_pc=config.pull_ratings or config.pull_playcounts,
            dry_run=dry_run,
        ),
        progress_callback=_progress_cb,
        device_info=device_info,
        device_capabilities=device_capabilities,
    )

    exec_outcome = engine.run(exec_request)
    if not exec_outcome.success:
        for d in exec_outcome.diagnostics:
            if d.fatal:
                logger.error("Execute failed: %s", d.message)
        return False

    print("[Music] Sync complete.")
    return True


# ---------------------------------------------------------------------------
# Podcast sync
# ---------------------------------------------------------------------------

def run_podcast_sync(
    ipod_path: str,
    ipod_tracks: tuple[dict, ...],
    existing_playlists: tuple[dict, ...],
    device_info: Any,
    device_capabilities: Any,
    config: SyncConfig,
    dry_run: bool = False,
) -> bool:
    if not config.podcasts:
        return True

    from PodcastManager.subscription_store import SubscriptionStore
    from PodcastManager.feed_parser import fetch_feed
    from PodcastManager.models import PodcastFeed
    from PodcastManager.podcast_sync import build_podcast_managed_plan
    from SyncEngine.core.engine import SyncEngine
    from SyncEngine.core.models import (
        EngineOperation,
        EngineOptions,
        EngineRequest,
    )
    from SyncEngine.mapping import MappingManager

    # Subscription state lives on the iPod itself
    store = SubscriptionStore(ipod_path)
    store.load()

    # Ensure all configured feeds are in the store, respecting keep_episodes
    for pod_cfg in config.podcasts:
        existing = next((f for f in store._feeds if f.feed_url == pod_cfg.url), None)
        if existing is None:
            store._feeds.append(PodcastFeed(
                feed_url=pod_cfg.url,
                episode_slots=pod_cfg.keep_episodes,
            ))
        else:
            existing.episode_slots = pod_cfg.keep_episodes

    # Refresh each feed and match against iPod
    print(f"\n[Podcasts] Refreshing {len(store._feeds)} feed(s)...")
    refreshed: list[PodcastFeed] = []
    for feed in store._feeds:
        print(f"  {feed.feed_url}")
        try:
            updated = fetch_feed(feed.feed_url, existing=feed)
            refreshed.append(updated)
        except Exception as exc:
            logger.warning("Feed refresh failed for %s: %s", feed.feed_url, exc)
            refreshed.append(feed)

    store.update_feeds(refreshed)

    # Build the managed sync plan (handles newest/next mode, slot counts, etc.)
    plan = build_podcast_managed_plan(refreshed, list(ipod_tracks), store)

    adds = len(getattr(plan, "to_add", []))
    removes = len(getattr(plan, "to_remove", []))
    print(f"[Podcasts] Plan: +{adds} add  -{removes} remove")

    if dry_run:
        print("[Podcasts] Dry run — skipping execution.")
        return True

    if adds == 0 and removes == 0:
        print("[Podcasts] Already in sync.")
        return True

    print("[Podcasts] Executing sync...")
    engine = SyncEngine()
    mapping = MappingManager(ipod_path).load()
    exec_request = EngineRequest(
        operation=EngineOperation.EXECUTE,
        ipod_path=ipod_path,
        ipod_tracks=ipod_tracks,
        existing_playlists=existing_playlists,
        plan=plan,
        mapping=mapping,
        options=EngineOptions(supports_podcast=True),
        progress_callback=_progress_cb,
        device_info=device_info,
        device_capabilities=device_capabilities,
    )

    outcome = engine.run(exec_request)
    if not outcome.success:
        for d in outcome.diagnostics:
            if d.fatal:
                logger.error("Podcast sync failed: %s", d.message)
        return False

    # Persist updated feed state back to the iPod
    store.save()
    print(f"[Podcasts] Done. +{adds} added, -{removes} removed.")
    return True


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_sync(
    config: SyncConfig,
    mount_hint: str | None = None,
    dry_run: bool = False,
    skip_music: bool = False,
    skip_podcasts: bool = False,
) -> int:
    """Run a full sync cycle. Returns exit code (0 = success)."""
    from iTunesDB_Parser.ipod_library import load_ipod_library

    # 1. Find iPod
    print("Scanning for iPod...")
    result = find_ipod(mount_hint)
    if result is None:
        print("No iPod found.", file=sys.stderr)
        return 1

    device_info, db_path = result
    mount_path = str(Path(db_path).parent.parent.parent)
    display = getattr(device_info, "display_name", None) or mount_path
    caps = getattr(device_info, "capabilities", None)
    print(f"Found: {display}  [{mount_path}]")

    # 2. Load iTunesDB
    print("Loading iPod library...")
    library = load_ipod_library(db_path)
    if library is None:
        print("Failed to read iTunesDB.", file=sys.stderr)
        return 1

    ipod_tracks = tuple(library.get("mhlt", []))
    existing_playlists = tuple(
        library.get("mhlp", [])
        + library.get("mhlp_podcast", [])
        + library.get("mhlp_smart", [])
    )
    print(f"  {len(ipod_tracks)} tracks, {len(existing_playlists)} playlists on iPod")

    ok = True

    # 3. Music sync
    if not skip_music and config.music_path:
        ok = run_music_sync(
            ipod_path=mount_path,
            ipod_tracks=ipod_tracks,
            existing_playlists=existing_playlists,
            device_info=device_info,
            device_capabilities=caps,
            config=config,
            dry_run=dry_run,
        ) and ok

    # 4. Podcast sync
    if not skip_podcasts and config.podcasts:
        ok = run_podcast_sync(
            ipod_path=mount_path,
            ipod_tracks=ipod_tracks,
            existing_playlists=existing_playlists,
            device_info=device_info,
            device_capabilities=caps,
            config=config,
            dry_run=dry_run,
        ) and ok

    return 0 if ok else 1
