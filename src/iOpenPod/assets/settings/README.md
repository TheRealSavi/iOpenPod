# Settings screenshots

These screenshots capture actual iOpenPod Qt widgets at 2× pixel density.
The Language setting instead uses `../glyphs/language.svg` for every language,
rendered in the current theme's text color. Settings with no useful visual result
have no preview.

General setting screenshots have Porcelain originals in this directory and Slate
variants in `slate/`. The active palette selects the Light or Dark version.
Theme and Mode previews continue to show the specific selected themes.

Mode's Light and Dark previews use the currently selected theme screenshots. Auto
combines those same screenshots at runtime along a bottom-left to top-right
diagonal, with Light above/left and Dark below/right. It has no separate image file.

Library screenshots use the supplied GenericArt directory and the explicit
filename-to-Album mapping in `scripts/screenshot_catalog.py`, shared with the
website and onboarding captures. Album names, artwork, and Track lists stay
matched. Sample artists and Track names come from that existing catalog.

Regenerate on Windows:

```shell
uv run python -m scripts.capture_settings_screenshots --artwork-dir "C:\Users\JohnG\Desktop\GenericArt"
```

Use `--slate-only` to add or refresh Slate variants while preserving all existing
Porcelain and theme screenshots. The default command regenerates both versions.

The isolated composition uses in-memory settings and a fake playback backend.
It does not open physical devices, personal media, or the user's settings.
Original artwork is read without modification. `manifest.json` records source
filenames, Album titles, artwork hashes, output hashes, and pixel dimensions.

Captures cover the available Light and Dark themes, Colorful Mode, Track-list
title bar styles, Player position and idle visibility,
navigation styles, Library View Modes, and device artwork styles. The runtime
allowlist in `GUI/presentation/settings_illustrations.py` selects these captures
and the shared Language SVG. Remaining setting rows stay unillustrated.
The preview shows only the image. Static screenshots retain their captured
language and theme; accessibility text follows the translated setting row.
