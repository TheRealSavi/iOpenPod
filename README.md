# iOpenPod: The Open-Source iPod Manager & iTunes Alternative for Windows, macOS, and Linux

**Your music. Your iPod.**

[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg?style=plastic)](LICENSE)
[![Platform: Win | Mac | Linux](https://img.shields.io/badge/Platform-Win%20%7C%20Mac%20%7C%20Linux-2ea44f.svg?style=plastic)](#download-and-install)
[![GitHub: Download latest](https://img.shields.io/badge/GitHub-Download%20latest-0a6fdb?style=plastic)](https://github.com/TheRealSavi/iOpenPod/releases/latest)
[![GitHub Stars](https://img.shields.io/github/stars/TheRealSavi/iOpenPod?style=plastic\&color=6e5494)](https://github.com/TheRealSavi/iOpenPod/stargazers)
[![PyPI Downloads](https://img.shields.io/pypi/dm/iopenpod?style=plastic\&color=0a6fdb\&cacheSeconds=86400)](https://pypi.org/project/iopenpod/)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=plastic)](https://discord.gg/9Yy499Tf5d)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/johngibbons)

iOpenPod is a free, open-source iPod manager and iTunes alternative for
**Windows, macOS, and Linux**. Browse your music, edit your library, and sync audio,
video, photos, and podcasts from your computer. Built-in conversion prepares media
for your iPod, and Sync Review lets you choose what gets added, updated, or removed.
Built with Python and Qt6.

[Website](https://iopenpod.com) ·
[Install help](https://iopenpod.com/install-help/) ·
[Discord](https://discord.gg/9Yy499Tf5d) ·
[Support development](https://ko-fi.com/johngibbons)

![iOpenPod album library with album artwork and the selected album track list](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/album-library.webp)

## Download and install

<!-- markdownlint-disable MD033 -->

<a href="https://get.microsoft.com/installer/download/9p2lxchhwlg9?referrer=appbadge" target="_self" >
    <img src="https://get.microsoft.com/images/en-us%20dark.svg" width="200"/>
</a>
<!-- markdownlint-enable MD033 -->

Native downloads are available for all three platforms (Windows, MacOS, Linux) on the
[latest release page](https://github.com/TheRealSavi/iOpenPod/releases/latest).

Choose the asset for your platform from below.

you do not need Python to install these.
See the [installation guide](https://iopenpod.com/install-help/) for setup and troubleshooting.

| Platform              | Latest release assets                                                           | Installation                                                           |
| --------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Windows x64           | [Windows x86\_64 ZIP](https://github.com/TheRealSavi/iOpenPod/releases/latest)  | Extract `iOpenPod.exe` and run it.                                     |
| macOS · Apple Silicon | [macOS arm64 DMG](https://github.com/TheRealSavi/iOpenPod/releases/latest)      | Open the image and drag `iOpenPod.app` to Applications.                |
| macOS · Intel         | [macOS x86\_64 DMG](https://github.com/TheRealSavi/iOpenPod/releases/latest)    | Open the image and drag `iOpenPod.app` to Applications.                |
| Linux x64             | [Linux x86\_64 tar.gz](https://github.com/TheRealSavi/iOpenPod/releases/latest) | Extract the complete folder and run its top-level `iOpenPod` launcher. |

On Windows, keep the file name as `iOpenPod.exe` and place it in a folder you can write to
on a fixed NTFS drive for in-app updates. Windows users can also install through
[Microsoft Store](https://apps.microsoft.com/detail/9P2LXCHHWLG9).

On macOS, launch from Applications after copying the app and ejecting the DMG.
The build targets macOS 12.3 or later. Current downloads are ad-hoc signed and not notarized; so you will have to allow the app to run in System Settings>Privacy and Secutiy. See the
[Mac setup guide](https://iopenpod.com/install-help/#native-macos)
which covers the first-launch prompts. Choose a DMG to install; the ZIPs labeled
`sparkle-update` are reserved for the built-in updater and arent inteded for users.

On Linux, extract into a folder you can write to, preserve executable permissions,
and keep the whole `iOpenPod` folder together. Always start its top-level launcher,
including after an update. The binary is built on Ubuntu 24.04 and requires glibc
2.39 or later plus desktop libraries.

Mac App Store, Flathub, and Snap Store remain planned. Check the
[website](https://iopenpod.com/#install) for channel availability.

### Updating a GitHub installation

iOpenPod checks for updates at launch. You can also use **Settings → About →
Check for updates**. About shows your current version and Install Channel.

* **Windows and Linux:** choose **Update now** to download the update, then
  **Restart to install** when ready. Save any Library Draft and finish running
  workflows first. Close other iOpenPod instances before restarting.

* **macOS:** choose **Update now** after saving your work, then follow the built-in
  updater's installation and relaunch prompts.

Installation requires your choice. If an older build only offers **Open download
page**, or cannot update itself, install the latest download from above manually.
Older Linux directory bundles should be replaced by extracting the new archive
into a fresh folder.
Microsoft Store installations update through the Store.

### Install from PyPI with uv

First [install uv](https://docs.astral.sh/uv/getting-started/installation/),
then run:

```shell
uv tool install iopenpod
```

Launch the app with `iopenpod`. For updates, choose **Update now**, then
**Restart to install** in the app. Or manually run

```shell
uv tool upgrade iopenpod
```

### Media tools

**FFmpeg and FFprobe** are installed separately for media conversion and inspection.
**Chromaprint's fpcalc** is also installed seperately and enables acoustic matching during Sync.

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

| Track metadata                                                                                                                                                                                | Track artwork                                                                                                                                                                             |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ![Edit Track dialog with title, artist, album, genre, composer, and track metadata](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/track-metadata.webp) | ![Edit Track artwork tab with cover art and controls to choose or clear artwork](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/track-artwork.webp) |

| Smart Playlists                                                                                                                                                              | Backup Snapshots                                                                                                                                                                         |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ![Smart Playlist editor with rules for music released before 2000](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/smart-playlist.webp) | ![Backups page with saved Backup Snapshots and restore actions for the selected iPod](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/backups.webp) |

![Audio transcoding settings for encoder, bitrate, lossless conversion, and spoken-word media](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/audio-transcoding-settings.webp)

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

| Media folders                                                                                                                                                                              | Sync selection                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ![Choose Media Folders dialog with per-folder media types and subfolder scanning](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/media-folders.webp) | ![Sync media selection with albums grouped as selected, mixed, and deselected](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/sync-media-selection.webp) |

![Sync Review with selected additions, unchecked removals, and items needing attention](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/sync-change-review.webp)

## iPod compatibility

iOpenPod targets these iPod families. Available features depend on the model.

| Family                | Target                                             |
| --------------------- | -------------------------------------------------- |
| iPod and iPod classic | Full-size generations 1–5.5 and the classic family |
| iPod mini             | 1st and 2nd generation                             |
| iPod nano             | 1st–7th generation                                 |

**iPod shuffle, iPod touch, and iPhone are not yet supported.** The computer
must already be able to read and write the iPod’s filesystem.

![Photo Library with the Manage Albums dialog and selected photo inspector](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/main/website/screenshots/iop2/photo-albums.webp)

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

Read [AGENTS.md](https://github.com/TheRealSavi/iOpenPod/blob/main/AGENTS.md), the [project context](https://github.com/TheRealSavi/iOpenPod/blob/main/CONTEXT.md), and the
[documentation map](https://github.com/TheRealSavi/iOpenPod/blob/main/docs/README.md) before making substantial changes.
[Packaging](https://github.com/TheRealSavi/iOpenPod/blob/main/docs/packaging.md) covers native builds and store release gates;
[website maintenance](https://github.com/TheRealSavi/iOpenPod/blob/main/website/README.md) covers screenshots and channel activation.

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
features. See [LICENSE](https://github.com/TheRealSavi/iOpenPod/blob/main/LICENSE), [COPYING.md](https://github.com/TheRealSavi/iOpenPod/blob/main/COPYING.md), and
[ACKNOWLEDGEMENTS.md](https://github.com/TheRealSavi/iOpenPod/blob/main/ACKNOWLEDGEMENTS.md) for the license grant and third-party
credits, including HASHAB, libgpod, and gtkpod research. The application icon has
separate permission terms documented with its assets.

Independent software, not affiliated with or endorsed by Apple Inc. iPod and
iTunes are trademarks of Apple Inc.
