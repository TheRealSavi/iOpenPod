# Microsoft Store screenshots

Upload the eight PNG files in `screenshots/` as **Desktop** screenshots for the
English (United States) listing, in numeric filename order. Each is 1920 × 1080
pixels, under 50 MB, and captured directly from the real iOpenPod 2.0 Qt widgets.
The matching captions and SHA-256 hashes are in `screenshots/manifest.json`.
No logos, marketing overlays, or fabricated controls have been added.

| Order | File | Screen |
| --- | --- | --- |
| 1 | `01-album-library.png` | Album browsing with Colorful Mode |
| 2 | `02-album-details.png` | An album opened in Whole Page Table mode |
| 3 | `03-playlists.png` | Playlist contents and artwork banner |
| 4 | `04-photo-library.png` | Photo albums, image preview, and representation details |
| 5 | `05-sync-review.png` | Expanded, selected changes in Sync Review |
| 6 | `06-about-and-credits.png` | License, optional donations, and acknowledgements |
| 7 | `07-sync-selection.png` | Host media selection with supplied Album artwork |
| 8 | `08-transcoding-settings.png` | Audio and video conversion settings |

Microsoft's [MSIX screenshot guidance](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/meight/screenshots-and-images)
requires PNG files, a minimum desktop size of 1366 × 768, and at most 50 MB per
image. It permits up to ten Desktop screenshots and recommends at least four.
Captions must be no longer than 200 characters. These eight images and captions meet
those dimensional and format requirements; Store certification remains Microsoft's
decision.

## Reproduce the captures

From the repository root on Windows, with the locked development environment:

```powershell
uv run python -m scripts.capture_store_screenshots --artwork-dir "C:\Users\JohnG\Desktop\GenericArt"
```

The capture harness uses the existing isolated application-shell test composition,
in-memory settings, and `VirtualStoragePlatform`. It renders the actual application
widgets through Qt's offscreen platform at a scale factor of one. Windows Segoe UI,
Segoe UI Symbol, Segoe UI Emoji, and Arial fonts are loaded from the installed
Windows font directory for ordinary text rendering; the font files are not copied
or distributed. No desktop or browser automation is needed.

The harness selects the app's existing Dark appearance, Colorful Mode, Whole Page
Table library preference, and manual draft-review option. It does not modify
production GUI files, real application settings, or device media. Navigation uses
the real page signals and widget interactions. `QWidget.grab()` writes the complete
client area without resizing or retouching the resulting screenshots.

## Sample data and rights

- The displayed **Sample iPod** is a synthetic model projection of the catalog's
  supported MB029 iPod Classic profile. No physical iPod is discovered or used.
- The 24 Album names, invented performer names, 288 Track records, three Playlists,
  ratings, durations, storage statistics, and dates are fictional capture data
  authored in the harness. Album names follow the source artwork filenames;
  invented artists and Track titles fit each cover's theme. These names are not
  artwork credits, a user's Library, or a packaged music offer.
- Album artwork and Photo examples come from the user-supplied GenericArt folder.
  The 24 covers named in `scripts/screenshot_catalog.py` are required. The catalog
  binds each Album to its exact filename. The last 12 case-insensitively sorted
  PNG filenames supply Photos, matching the website and onboarding captures. Source filenames and SHA-256 hashes are recorded in the manifest.
  Original files remain external inputs and are never modified.
- The Sync Review shows typed example Add actions from the fictional
  `C:/Sample Music` path. No such media files need to exist, no media helper is run,
  and the capture never executes a Sync or claims a completed transfer.
- The fictional metadata and capture scripts are distributed under the project's
  GPL-3.0-or-later license. Supplied artwork is used at the project owner's request;
  its inclusion does not assign a new license to the source images. Windows fonts
  remain owned and licensed by their respective owners.
- The normal application device illustration appears as part of the captured UI;
  its provenance is documented with the application's device-image assets. The
  project license and third-party notices continue to apply to the underlying UI.

These screenshots show example library contents only. The app does not ship the
fictional Tracks as playable music. The first screenshot's caption and the app's
status bar identify the sample library, and the Photo screenshot caption identifies
its sample illustrations.

## Verification

All eight captures are visually inspected after generation for readable text,
intact controls, loaded artwork, accurate feature presentation, and absence of
private data. The manifest records the exact image bytes to upload. Regenerate
and inspect the images after changing relevant UI or attribution text; do not
substitute obsolete screenshots after a release rebuild.
