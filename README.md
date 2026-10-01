# iOpenPod 2

**Your music. Your iPod.**

A free, open-source desktop app for browsing, playing, organizing, and syncing
filesystem-accessible iPods on **Windows, macOS, and Linux**, without iTunes.

[Website](https://therealsavi.github.io/iOpenPod/) ·
[Install help](https://therealsavi.github.io/iOpenPod/install-help/) ·
[Discord](https://discord.gg/9Yy499Tf5d) ·
[Support development](https://ko-fi.com/johngibbons)

![iOpenPod 2 album library with colorful cover art and a connected sample iPod](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/albums.webp)

*Real iOpenPod 2 UI captured on Windows. The screenshots use fictional media and
original sample artwork; no personal library or physical iPod is involved.*

## Get iOpenPod 2

**2.0 is in development.** Native packaging candidates exist; public iOpenPod 2 binary
releases, the 2.x PyPI package, and store publication are still pending. The
[website’s download section](https://therealsavi.github.io/iOpenPod/#install) will
link each channel as it becomes available.

| Platform | Planned direct download | Planned store distribution |
| --- | --- | --- |
| Windows | Native x64 ZIP | Microsoft Store |
| macOS | Native app archives for Apple Silicon and Intel | Mac App Store |
| Linux | Native x64 tar.gz archive | Flathub (Flatpak) and Snap Store |
| Python users | `iopenpod` 2.x on PyPI, requiring Python 3.12 | — |

Native downloads include the application runtime, so they do not need a separate
Python installation. The native Mac build targets macOS 12.3 or later; acceptance
on 12.3 remains pending. Store channels have independent signing, permissions, and
installed-package validation requirements. See [packaging](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/packaging.md).

### Python installation, once 2.x is published

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) to install the app
in an isolated tool environment:

```shell
uv tool install --python 3.12 "iopenpod>=2,<3"
iopenpod
```

The version constraint requires iOpenPod 2 and will fail until a matching release is
published. Upgrade with `uv tool upgrade iopenpod`. If the launcher is missing
from your PATH, run `uv tool update-shell` and reopen your terminal.

### Media tools

**FFmpeg and FFprobe are installed separately** for media inspection and conversion.
**Chromaprint’s fpcalc is optional** and enables acoustic matching.

The startup popup or **Settings → Media Tools → Set Up Media Tools** can install
missing tools after you choose **Install Missing Tools**. Native setup uses WinGet,
Homebrew, or a supported Linux package manager. You can skip setup to browse your
library. Confined store builds need their own verified tool access; follow the
instructions for that release. See [media-tool setup](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/media-tools.md).

## Explore your library

- **Albums, artists, genres, and tracks.** Browse artwork, search your collection,
  and edit metadata and ratings.
- **Playlists and Smart Playlists.** Arrange tracks, organize playlist folders,
  and create rule-based selections.
- **Playback and Synesthesia.** Listen to supported tracks with desktop media
  controls and explore music-reactive visuals.
- **Photos.** Browse Photo Albums, inspect device-sized images, and export retained
  originals and supported image representations.
- **Podcasts.** Find shows, manage subscriptions, and refresh feeds and artwork.
  Online discovery requires an internet connection.
- **Scrobbling.** Optionally submit iPod music plays to Last.fm and ListenBrainz.
- **Backup Snapshots.** Capture, browse, annotate, export, and restore local backups.
  Interrupted writes expose explicit recovery actions.
- **Appearance and conversion settings.** Choose light, dark, or system appearance
  and configure how incoming media is prepared.

Library edits save automatically by default. Enable **Draft all changes** to review
and save those edits together. Sync always has its own selection and review flow.

| Album details | Playlists |
| --- | --- |
| ![iOpenPod 2 album artwork and track details](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/album-details.webp) | ![iOpenPod 2 playlist browser](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/playlists.webp) |

## Choose what comes along

1. **Connect your iPod** and select it in the device picker. Your operating system
   must be able to mount and access it.
2. **Capture a Backup Snapshot** of the data you want to preserve.
3. **Choose Sync with Host**, add media folders, and select what to scan.
4. **Select your media**, then review additions, updates, and removals. Removal
   candidates start unchecked.
5. **Sync Selected** prepares compatible media and publishes verified changes.
   Use the app’s eject action when you are finished.

Device-aware preparation converts audio and video when needed and writes artwork
for your model. Optional acoustic matching helps recognize recordings across
format or metadata changes; previously committed source relationships can also
identify media without a new fingerprint.

![iOpenPod 2 Sync Review showing selected changes before a device write](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/sync-review.webp)

## Compatibility

iOpenPod 2 targets these filesystem-accessible iPod families. Features depend on the
model; real-device validation continues during development.

| Family | Target |
| --- | --- |
| iPod and iPod classic | Full-size generations 1–5.5 and the classic family |
| iPod mini | 1st and 2nd generation |
| iPod nano | 1st–7th generation |

**iPod shuffle, iPod touch, and iPhone are outside the 2.0 target.** The computer
must already be able to read and write the iPod’s filesystem. DRM-protected media
is not supported.

![iOpenPod 2 Photo Library with Photo Albums and an image inspector](https://raw.githubusercontent.com/TheRealSavi/iOpenPod/2.0/website/screenshots/iop2/photos.webp)

## Develop and contribute

From this **2.0 source checkout**, use the locked UV environment:

```shell
uv sync --locked
uv run iopenpod
```

UV selects Python 3.12 from `.python-version`. The module entry point is also
available through `uv run python -m iOpenPod`.

Run the repository checks:

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run rumdl check .
uv run mypy
uv run pytest
```

Useful contributions include hardware and platform testing, reproducible bug
reports, and focused pull requests. Include the iOpenPod 2 version, installation channel,
operating system, and iPod model with a report. Discuss major changes in an issue
or on [Discord](https://discord.gg/9Yy499Tf5d).

The application ships as one distribution with four internal boundaries:

| Package | Responsibility |
| --- | --- |
| `src/iOpenPod` | Application workflows, state, and GUI |
| `src/device_registry` | iPod identity and capabilities |
| `src/iPodDB` | Lossless iPod database formats |
| `src/storage` | Safe filesystem and removable-media operations |

Read [AGENTS.md](https://github.com/TheRealSavi/iOpenPod/blob/2.0/AGENTS.md), the [project context](https://github.com/TheRealSavi/iOpenPod/blob/2.0/CONTEXT.md), and the
[documentation map](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/README.md) before making substantial changes.
[Packaging](https://github.com/TheRealSavi/iOpenPod/blob/2.0/docs/packaging.md) covers native candidates and store release gates;
[website maintenance](https://github.com/TheRealSavi/iOpenPod/blob/2.0/website/README.md) covers screenshots and channel activation.

## License and credits

Licensed under **GPL-3.0-or-later**. All features are free; optional
[donations](https://ko-fi.com/johngibbons) support development without unlocking
features. See [LICENSE](https://github.com/TheRealSavi/iOpenPod/blob/2.0/LICENSE), [COPYING.md](https://github.com/TheRealSavi/iOpenPod/blob/2.0/COPYING.md), and
[ACKNOWLEDGEMENTS.md](https://github.com/TheRealSavi/iOpenPod/blob/2.0/ACKNOWLEDGEMENTS.md) for the license grant and third-party
credits, including HASHAB, libgpod, and gtkpod research. The application icon has
separate permission terms documented with its assets.

Independent software, not affiliated with or endorsed by Apple Inc. iPod and
iTunes are trademarks of Apple Inc.
