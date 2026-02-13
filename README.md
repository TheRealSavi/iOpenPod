# iOpenPod

**Open-source iPod Classic sync tool — manage your iPod without iTunes.**

iOpenPod reads and writes the iPod's native iTunesDB and ArtworkDB binary formats directly, giving you full control over your music library. Sync tracks, metadata, play counts, ratings, and album art between your PC and iPod — no iTunes required.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52.svg)](https://www.riverbankcomputing.com/software/pyqt/)

---

## Why iOpenPod?

- **No iTunes dependency** — Syncs directly with the iPod's database files
- **Format agnostic** — Automatically transcodes FLAC, OGG, and other formats to iPod-compatible ALAC/AAC
- **Acoustic fingerprinting** — Uses Chromaprint to reliably match tracks even after re-encodes or metadata changes
- **Two-way sync** — Play counts, ratings, and skip counts sync back to your PC library
- **Cross-platform** — Built with Python and PyQt6 (Windows, macOS, Linux)

## Features

### Music Sync
- **Smart library diffing** — Detects new, removed, and changed tracks using acoustic fingerprints
- **Automatic transcoding** — Converts FLAC, OGG, WMA, and other formats to ALAC or AAC on-the-fly
- **Transcode caching** — Optionally cache converted files for faster repeat syncs
- **Metadata-only updates** — Tag changes sync without re-copying audio files

### Play Count & Rating Sync
- **Bidirectional play count sync** — Reads the iPod's Play Counts file and merges with your PC library
- **Rating strategies** — Choose pessimistic (keep lower) or optimistic (keep higher) for conflicts
- **Skip count tracking** — Skip counts sync alongside play counts

### Library Management
- **Visual sync review** — See exactly what will change before syncing (add, remove, update)
- **Selective sync** — Check/uncheck individual tracks or entire categories
- **Duplicate detection** — Identifies duplicate tracks via acoustic fingerprinting
- **Integrity checks** — Detects orphan files, stale mappings, and missing tracks automatically

### Album Artwork
- **Artwork sync** — Extracts and writes RGB565 album art to iPod `.ithmb` files
- **Automatic resizing** — Generates all required artwork sizes (140×140, 56×56, etc.)

### Storage & Safety
- **Storage estimates** — Shows space required/freed before syncing
- **Checkpoint & rollback** — Automatic pre-sync backups with one-click restore
- **ETA tracking** — Real-time progress estimates during sync operations
- **Desktop notifications** — Get notified when long syncs complete

## Supported Devices

| Device | Read | Write | Notes |
|--------|------|-------|-------|
| iPod 1G–5G, Mini, Photo | ✅ | ✅ | No hash required |
| iPod Nano 3G–4G | ✅ | ✅ | HASH58 (FireWire ID from SysInfo) |
| iPod Classic (all gens) | ✅ | ✅ | HASH72 (requires one iTunes sync for HashInfo) |
| iPod Nano 5G | ✅ | ✅ | HASH72 |
| iPod Nano 6G–7G | ✅ | ❌ | HASHAB not reverse-engineered |

## Screenshots

<!-- Add screenshots here -->
<!-- ![Main Window](docs/screenshots/main.png) -->
<!-- ![Sync Review](docs/screenshots/sync-review.png) -->

*Screenshots coming soon — contributions welcome!*

## Installation

### Prerequisites
- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[Chromaprint / fpcalc](https://acoustid.org/chromaprint)** — for acoustic fingerprinting
- **[FFmpeg](https://ffmpeg.org/)** — for transcoding non-native formats

### Quick Start

```bash
# Clone the repository
git clone https://github.com/TheRealSavi/iOpenPod.git
cd iOpenPod

# Install dependencies with uv
uv sync

# Launch the app
uv run python main.py
```

### Alternative (pip)

```bash
pip install -e .
python main.py
```

## Usage

1. **Connect your iPod** — Plug in via USB and mount it (it should appear as a drive)
2. **Select device** — Click the device button in the sidebar to scan for connected iPods
3. **Browse your library** — View albums, tracks, and metadata in the album grid or list view
4. **Start a sync** — Click Sync, select your PC music folder, and review the proposed changes
5. **Apply changes** — Check/uncheck items as needed, then click Apply to sync

## How It Works

iOpenPod uses a **fingerprint-based sync engine** to reliably track identity between your PC files and iPod tracks:

1. **Scan** — Reads your PC music folder and the iPod's iTunesDB
2. **Fingerprint** — Computes acoustic fingerprints (Chromaprint) for each track
3. **Diff** — Compares fingerprints to find new, removed, changed, and matched tracks
4. **Review** — Shows a detailed sync plan with categories (add, remove, update metadata, etc.)
5. **Execute** — Copies/transcodes files, updates the iTunesDB, syncs artwork and play counts
6. **Write** — Rebuilds the entire iTunesDB with proper checksums for your device generation

## Project Structure

```
iOpenPod/
├── GUI/                    # PyQt6 user interface
│   ├── app.py              # Main window, device management
│   ├── notifications.py    # Desktop notification support
│   └── widgets/            # UI components (grid, list, sidebar, sync review)
├── iTunesDB_Parser/        # Binary parser for iTunesDB format
├── iTunesDB_Writer/        # Binary writer with hash/checksum support
├── ArtworkDB_Parser/       # Binary parser for ArtworkDB format
├── ArtworkDB_Writer/       # Album art extraction and writing
├── SyncEngine/             # Core sync logic
│   ├── fingerprint_diff_engine.py  # Acoustic fingerprint-based diffing
│   ├── sync_executor.py    # Executes sync plans
│   ├── transcoder.py       # FLAC→ALAC, OGG→AAC conversion
│   ├── checkpoint.py       # Backup & rollback system
│   └── eta.py              # ETA time estimation
└── main.py                 # Application entry point
```

## Contributing

Contributions are welcome! Areas where help is especially appreciated:

- **Testing on real hardware** — Especially iPod Nano models
- **macOS / Linux testing** — Primary development is on Windows
- **UI polish** — Dark theme refinements, accessibility
- **Documentation** — Usage guides, wiki pages

Please open an issue first to discuss major changes.

## Related Projects

- [libgpod](https://github.com/gtkpod/libgpod) — C library for iPod database access (reference implementation)
- [gtkpod](https://github.com/gtkpod/gtkpod) — GTK+ iPod manager
- [Rockbox](https://www.rockbox.org/) — Open-source firmware replacement for iPods

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Keywords

iPod sync tool, iPod Classic manager, iTunes alternative, iTunesDB reader writer,
iPod music sync without iTunes, open source iPod manager, iPod database tool,
manage iPod on Linux, manage iPod on Windows, iPod FLAC sync, acoustic fingerprint sync
