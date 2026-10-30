# Glyph Assets

Glyphs use a `24 × 24` view box and `currentColor`. The shared icon provider replaces
that color with a semantic Qt palette role and supplies common Device Pixel Ratio
variants through one `QIcon`. New glyphs should preserve those constraints rather
than embedding theme colors or adding page-local rendering code.

`games.svg` is the unmodified Tabler Icons outline `device-gamepad-2` from commit
`a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d`, matching the
[Genius Mix icon collection](genius-mixes/README.md). It uses the same
[MIT license](genius-mixes/LICENSE).
