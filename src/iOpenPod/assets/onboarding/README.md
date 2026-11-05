# Onboarding screenshots

These PNGs are captures of the real iOpenPod Qt widgets using a fictional Library
and the application's bundled device portraits. Album artwork comes from the supplied GenericArt folder, using the same
explicit filename-to-Album mapping as the website and Store captures. No personal media, settings,
network services, or physical iPods are used.

Regenerate on Windows with:

```shell
uv run python -m scripts.capture_onboarding_screenshots --artwork-dir "C:\Users\JohnG\Desktop\GenericArt"
```

The source images remain external capture inputs and are never modified.
`manifest.json` records their filenames and SHA-256 hashes alongside the output
hashes. The folder must contain the 24 covers named in
`scripts/screenshot_catalog.py`. Album names follow the artwork filenames, with
invented artists and matching Track lists.

The script uses the offscreen Qt platform and explicitly loads the installed
Segoe UI fonts. It captures navigation, all three Library layouts, both device
image styles, Transcoding settings, the pressed Sync with Host button in both
navigation styles, Choose Media Folders, Select Media, and Sync Review. Runtime code
loads only these packaged PNGs; it does not import the script or test fixtures.
Screenshots remain in the light theme for a consistent example regardless of
the dialog's live theme. The adjacent copy explains each selected option.
The compact navigation capture uses a 960-pixel-wide window and its top 240 pixels:
the whole navigation bar, Albums heading, and upper artwork row remain visible.
The Sync entry captures focus on the pressed button and neighboring Library UI.
The folders and Sync stages use simulated selections; no scan or transfer runs.
Select Media shows three selected and three deselected Albums, including an
already-synced Album with the iPod symbol.
The Review capture uses the workspace's available-execution state to show the
real Sync Selected action. Tutorial pages explain these controls without editing
transcoding or Library-draft settings.

The script also writes light/dark dialog previews and small-window previews under
ignored `.scratch/onboarding-preview/` for visual review. After changing the
illustrated widgets, regenerate the images and inspect those previews.

Onboarding stages Host preferences until Finish. Each preference is saved through
the existing settings service before the completion flag is persisted. A save
failure keeps the dialog open for retry and leaves completion false; preferences
saved before the failure can already be persisted. Dismissal before Finish makes
no settings changes. Existing installations without the flag see the same tour,
with their current Host preferences selected.
