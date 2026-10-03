# iOpenPod: The Open-Source iPod Manager & iTunes Alternative for Windows, macOS, and Linux

**Your music. Your iPod.**

[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg?style=plastic)](LICENSE)
[![Platform: Win | Mac | Linux](https://img.shields.io/badge/Platform-Win%20%7C%20Mac%20%7C%20Linux-2ea44f.svg?style=plastic)](#download-and-install)
[![GitHub Release](https://img.shields.io/github/v/release/TheRealSavi/iOpenPod?style=plastic\&color=0a6fdb)](https://github.com/TheRealSavi/iOpenPod/releases/latest)
[![GitHub Stars](https://img.shields.io/github/stars/TheRealSavi/iOpenPod?style=plastic\&color=6e5494)](https://github.com/TheRealSavi/iOpenPod/stargazers)
[![PyPI Downloads](https://img.shields.io/pypi/dm/iopenpod?style=plastic\&color=0a6fdb\&cacheSeconds=86400)](https://pypi.org/project/iopenpod/)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=plastic)](https://discord.gg/9Yy499Tf5d)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/johngibbons)

iOpenPod is a free, open-source iPod manager and iTunes alternative for
**Windows, macOS, and Linux**. Browse your music, edit your library, and sync audio,
video, photos, and podcasts from your computer. Built-in conversion prepares media
for your iPod, and Sync Review lets you choose what gets added, updated, or removed.
Built with Python and Qt6.

[Website](https://therealsavi.github.io/iOpenPod/) ·
[Install help](https://therealsavi.github.io/iOpenPod/install-help/) ·
[Discord](https://discord.gg/9Yy499Tf5d) ·
[Support development](https://ko-fi.com/johngibbons)

![iOpenPod album library with album artwork and the selected album track list](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/album-library.webp)

## Download and install

Find native builds on the [releases page](https://github.com/TheRealSavi/iOpenPod/releases)
and channel availability on the [website](https://therealsavi.github.io/iOpenPod/#install).
For setup help, see the [installation guide](https://therealsavi.github.io/iOpenPod/install-help/).

| Platform     | Planned direct download                         | Store distribution                                                |
| ------------ | ----------------------------------------------- | ----------------------------------------------------------------- |
| Windows      | Native x64 ZIP                                  | [Microsoft Store](https://apps.microsoft.com/detail/9P2LXCHHWLG9) |
| macOS        | Native app archives for Apple Silicon and Intel | Mac App Store (planned)                                           |
| Linux        | Native x64 tar.gz archive                       | Flathub (Flatpak) and Snap Store (planned)                        |
| Python users | `iopenpod` 2.x on PyPI, requiring Python 3.12   | —                                                                 |

Native downloads include the application runtime, so they do not need a separate
Python installation. The native Mac build targets macOS 12.3 or later; acceptance
on 12.3 remains pending. Store channels have independent signing, permissions, and
installed-package validation requirements. See [packaging](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/packaging.md).

### Python installation

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) to install the app
in an isolated tool environment:

```shell
uv tool install --python 3.12 "iopenpod>=2,<3"
iopenpod
```

### Media tools

**FFmpeg and FFprobe** are installed separately for media conversion and inspection.
**Chromaprint's fpcalc** is optional and enables acoustic matching during Sync.

The startup popup or **Settings → Media Tools → Set Up Media Tools** can install
missing tools after you choose **Install Missing Tools**. Native setup uses WinGet,
Homebrew, or a supported Linux package manager.

## What you can do

* **Albums, artists, genres, and tracks.** Browse artwork, search your collection,
  and edit metadata and ratings.

* **Playlists and Smart Playlists.** Arrange tracks, organize playlist folders,
  and create rule-based selections.

* **Automatic media conversion.** Convert audio and video when needed and prepare
  artwork for your iPod model. Choose how incoming media is encoded in Settings.

* **Playback and Synesthesia.** Listen to supported tracks with desktop media
  controls and explore music-reactive visuals.

* **Photos.** Browse Photo Albums, inspect device-sized images, and export retained
  originals and supported image representations.

* **Podcasts.** Find shows, manage subscriptions, and refresh feeds and artwork.
  Online discovery requires an internet connection.

* **Scrobbling.** Optionally submit iPod music plays to Last.fm and ListenBrainz.

* **Backup Snapshots.** Capture, browse, annotate, export, and restore local backups.
  Interrupted writes expose explicit recovery actions.

* **Appearance and conversion settings.** Choose light, dark, or system appearance
  and configure how incoming media is prepared.

Library edits save automatically by default. Enable **Draft all changes** to review
and save those edits together. Sync always has its own selection and review flow.

| Track metadata | Track artwork |
| --- | --- |
| ![Edit Track dialog with title, artist, album, genre, composer, and track metadata](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/track-metadata.webp) | ![Edit Track artwork tab with cover art and controls to choose or clear artwork](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/track-artwork.webp) |

| Smart Playlists | Backup Snapshots |
| --- | --- |
| ![Smart Playlist editor with rules for music released before 2000](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/smart-playlist.webp) | ![Backups page with saved Backup Snapshots and restore actions for the selected iPod](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/backups.webp) |

![Audio transcoding settings for encoder, bitrate, lossless conversion, and spoken-word media](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/audio-transcoding-settings.webp)

## How to use

1. **Connect your iPod** and select it in the device picker. Your operating system
   must be able to mount and access it. Browse your library, play tracks, or edit
   metadata and playlists.
2. **Capture a Backup Snapshot** of the data you want to preserve.
3. **Choose Sync with Host**, add media folders, and select what to scan.
4. **Select your media**, then review additions, updates, and removals. Removal
   candidates start unchecked.
5. **Sync Selected** prepares compatible media and publishes verified changes.
   Use the app’s eject action when you are finished.

Optional acoustic matching helps recognize the same recording after format or
metadata changes. Sync can also recognize media from a previous successful Sync
without generating a new fingerprint.

| Media folders | Sync selection |
| --- | --- |
| ![Choose Media Folders dialog with per-folder media types and subfolder scanning](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/media-folders.webp) | ![Sync media selection with albums grouped as selected, mixed, and deselected](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/sync-media-selection.webp) |

![Sync Review with selected additions, unchecked removals, and items needing attention](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/sync-change-review.webp)

## iPod compatibility

iOpenPod targets these iPod families. Available features depend on the model.

| Family                | Target                                             |
| --------------------- | -------------------------------------------------- |
| iPod and iPod classic | Full-size generations 1–5.5 and the classic family |
| iPod mini             | 1st and 2nd generation                             |
| iPod nano             | 1st–7th generation                                 |

**iPod shuffle, iPod touch, and iPhone are not yet supported.** The computer
must already be able to read and write the iPod’s filesystem.

![Photo Library with the Manage Albums dialog and selected photo inspector](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/photo-albums.webp)

## Develop and contribute

Clone the repository, open its directory, and use the locked UV environment:

```shell
uv sync --locked
uv run iopenpod
```

Before submitting changes, run the repository checks:

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run rumdl check .
uv run mypy
uv run pytest
```

Hardware testing, platform testing, reproducible bug reports, and focused pull
requests all help. For bug reports, include your iPod model, operating system,
iOpenPod version, and steps to reproduce the problem.

Keep each pull request focused on one change. Discuss proposed work in an issue or
on [Discord](https://discord.gg/9Yy499Tf5d) before starting, especially for major
changes, so we can agree on the approach.

The application ships as one distribution with four internal boundaries:

| Package               | Responsibility                                 |
| --------------------- | ---------------------------------------------- |
| `src/iOpenPod`        | Application workflows, state, and GUI          |
| `src/device_registry` | iPod identity and capabilities                 |
| `src/iPodDB`          | iPod database formats                          |
| `src/storage`         | Safe filesystem and removable-media operations |

Read [AGENTS.md](https://github.com/TheRealSavi/iOpenPod/blob/2.0/AGENTS.md), the [project context](https://github.com/TheRealSavi/iOpenPod/blob/2.0/CONTEXT.md), and the
[documentation map](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/README.md) before making substantial changes.
[Packaging](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/packaging.md) covers native candidates and store release gates;
[website maintenance](https://github.com/TheRealSavi/iOpenPod/blob/2.0/website/README.md) covers screenshots and channel activation.

## Related projects

* [libgpod](https://github.com/gtkpod/libgpod) - C library for iPod database access (the reference implementation this project learned from)

* [gtkpod](https://github.com/gtkpod/gtkpod) - GTK+ iPod manager

* [Rockbox](https://www.rockbox.org/) - Open-source firmware replacement for iPods

## Coming from iTunes or another iPod manager?

iOpenPod works with the library on your iPod and media folders on your computer.
Start by browsing the existing library and capturing a Backup Snapshot, then choose
what to bring over in Sync Review.

* **No separate libgpod installation.** iOpenPod uses its own Python iPod database
  implementation, informed by libgpod and gtkpod research.

* **All features are free.** Donations support development without unlocking features.

* **Review before writing.** Sync shows planned changes, with removals unchecked by
  default. Backup Snapshots are user-controlled, and interrupted writes have
  explicit recovery actions.

***

## Star history

<!-- markdownlint-disable MD033 -->

<a href="https://www.star-history.com/?repos=therealsavi%2Fiopenpod&type=timeline&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=therealsavi/iopenpod&type=timeline&theme=dark&legend=top-left&sealed_token=aMCIa4pbVoIhlxj9qK6fW6xT1G5WPmVyftpcUHMTDCF-jNcb-ZD5ewReZkCnZxjUqpEYILAoYH1UP1nYDNyqT1PbhUaA09JI1Lrq1EZ2-mO9bYPn3EWaHyBxmimY3pGYha3MHx1aNeAXRuF0UoijWcDkCgvNBHYDbZNCLG6zG8wx6tDuSh8cmrTN0uas" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=therealsavi/iopenpod&type=timeline&legend=top-left&sealed_token=aMCIa4pbVoIhlxj9qK6fW6xT1G5WPmVyftpcUHMTDCF-jNcb-ZD5ewReZkCnZxjUqpEYILAoYH1UP1nYDNyqT1PbhUaA09JI1Lrq1EZ2-mO9bYPn3EWaHyBxmimY3pGYha3MHx1aNeAXRuF0UoijWcDkCgvNBHYDbZNCLG6zG8wx6tDuSh8cmrTN0uas" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=therealsavi/iopenpod&type=timeline&legend=top-left&sealed_token=aMCIa4pbVoIhlxj9qK6fW6xT1G5WPmVyftpcUHMTDCF-jNcb-ZD5ewReZkCnZxjUqpEYILAoYH1UP1nYDNyqT1PbhUaA09JI1Lrq1EZ2-mO9bYPn3EWaHyBxmimY3pGYha3MHx1aNeAXRuF0UoijWcDkCgvNBHYDbZNCLG6zG8wx6tDuSh8cmrTN0uas" />
 </picture>
</a>

<!-- markdownlint-enable MD033 -->

***

## Support

iOpenPod is free and open source. Donations are optional and help support development.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/johngibbons)

## License and credits

Licensed under **GPL-3.0-or-later**. All features are free; optional
[donations](https://ko-fi.com/johngibbons) support development without unlocking
features. See [LICENSE](https://github.com/TheRealSavi/iOpenPod/blob/2.0/LICENSE), [COPYING.md](https://github.com/TheRealSavi/iOpenPod/blob/2.0/COPYING.md), and
[ACKNOWLEDGEMENTS.md](https://github.com/TheRealSavi/iOpenPod/blob/2.0/ACKNOWLEDGEMENTS.md) for the license grant and third-party
credits, including HASHAB, libgpod, and gtkpod research. The application icon has
separate permission terms documented with its assets.

Independent software, not affiliated with or endorsed by Apple Inc. iPod and
iTunes are trademarks of Apple Inc.
