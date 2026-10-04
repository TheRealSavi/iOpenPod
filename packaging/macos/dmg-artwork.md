# DMG artwork

The installer uses the user's cobalt chrome reference, with the application and
Applications icons supplied by Finder. `dmg-backdrop.png` is original artwork
generated with the built-in image generation tool on 2026-10-04. The reference's
icons, window chrome, arrow, and text were not included in that generated layer.

`dmg-background.svg` adds the wordmark, glass arrow, and instruction panel. The
glass uses a blurred, enlarged copy of the wallpaper behind each shape, translucent
fills, edge highlights, and soft shadows. These effects are static artwork;
Finder does not provide a live Liquid Glass material for its background image.

Run `uv run python -m scripts.render_macos_dmg_background` to update
`dmg-background.png` using the project's existing Qt dependencies and system fonts.
Review the rendered text before committing. The PNG is checked in so release
builds do not depend on the build host's fonts or regenerate artwork.

The coordinate system is 800 × 500 points. The raster is 1600 × 1000 pixels at
144 DPI. Keep those physical dimensions aligned with `dmg-layout.applescript`:
160-point icons centered at `(200, 232)` and `(600, 232)`, with the arrow between
them. See the [packaging guide](../../docs/packaging.md) for checks and native
validation limits.

## Backdrop generation prompt

Use case: stylized-concept. Asset: background artwork ONLY for an iOpenPod macOS drag-to-install DMG, landscape 8:5 aspect ratio. Premium 3D studio render of twisting flowing liquid-chrome cobalt-blue ribbons on almost-black midnight navy. One sculptural blue chrome ribbon enters from lower left, loops up along the far left side, turns near upper left, then curves down across the bottom, ending toward the right. A second elegant broad sweep enters from middle right and flows toward lower center. Lustrous deep electric blue metal, thin icy silver-blue specular edge reflections, realistic flowing smooth reflective sculptural surfaces with a few beautiful closely spaced ridges. Strong composition, polished Apple wallpaper feel. Important composition: generous mostly dark negative space in the middle horizontal band, especially around x=25%, y=47% and x=75%, y=47% for actual Finder icons that will be added separately. Quiet top left for a small wordmark. Keep upper half center dark and uncluttered. Bottom at y=80% has a ribbon flowing behind the location of a future glass instruction bar so refraction will show. Cropped immersive edge-to-edge wallpaper, no frame, no window chrome, no traffic light buttons, no text, no logos, no symbols, no icons, no folders, no arrows, no panels. This is the abstract wallpaper layer only.
