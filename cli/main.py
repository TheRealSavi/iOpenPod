"""iopenpod-sync — headless iPod sync CLI.

Usage:
    iopenpod-sync [options]

Options:
    --config PATH       Config file path (default: ~/.config/iopenpodcli/config.yaml)
    --device PATH       iPod mount path (auto-detect if omitted)
    --dry-run           Plan but don't write anything
    --no-music          Skip music sync
    --no-podcasts       Skip podcast sync
    --list-devices      List connected iPods and exit
    --init-config       Write an example config and exit
    -v, --verbose       Verbose logging
"""

from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _list_devices() -> None:
    from ipod_device.scanner import scan_for_ipods

    devices = scan_for_ipods()
    if not devices:
        print("No iPods found.")
        return
    for d in devices:
        model = getattr(d, "model_family", "") or ""
        gen = getattr(d, "generation", "") or ""
        cap = getattr(d, "capacity_gb", "") or ""
        mount = getattr(d, "mount_path", "")
        display = getattr(d, "display_name", "") or str(mount)
        print(f"  {display}  [{mount}]  {model} {gen} {cap}GB".rstrip())


def _init_config(path: str) -> None:
    from pathlib import Path

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    example = """\
# iopenpod-sync configuration
# See: https://github.com/TristonYoder/iOpenPod

# Root directory containing your music files
music_path: ~/Music

# M3U / M3U8 playlist files to sync (paths relative to music_path, or absolute).
# Leave empty to sync all music in music_path.
playlists:
  # - Favorites.m3u
  # - Workout.m3u8

# Podcast feeds
podcasts:
  # - url: https://feeds.example.com/podcast.rss
  #   keep_episodes: 5

# Sync ratings from iPod back to PC file tags (via mutagen)
pull_ratings: true

# Sync play counts from iPod back to PC file tags
pull_playcounts: true

# Rating conflict resolution: ipod_wins | pc_wins | higher_wins
rating_strategy: ipod_wins
"""
    target.write_text(example)
    print(f"Config written to {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="iopenpod-sync",
        description="Headless iPod sync — music playlists + podcasts + ratings",
    )
    parser.add_argument("--config", metavar="PATH", help="Config file path")
    parser.add_argument("--device", metavar="PATH", help="iPod mount path (auto-detect if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="Plan but don't write")
    parser.add_argument("--no-music", action="store_true", help="Skip music sync")
    parser.add_argument("--no-podcasts", action="store_true", help="Skip podcast sync")
    parser.add_argument("--list-devices", action="store_true", help="List connected iPods and exit")
    parser.add_argument("--init-config", metavar="PATH", nargs="?", const="~/.config/iopenpodcli/config.yaml",
                        help="Write example config and exit")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.list_devices:
        _list_devices()
        sys.exit(0)

    if args.init_config:
        _init_config(args.init_config)
        sys.exit(0)

    from cli.config import load_config
    from cli.sync import run_sync

    config = load_config(args.config)

    sys.exit(
        run_sync(
            config=config,
            mount_hint=args.device,
            dry_run=args.dry_run,
            skip_music=args.no_music,
            skip_podcasts=args.no_podcasts,
        )
    )


if __name__ == "__main__":
    main()
