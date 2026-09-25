# Glyph Assets

Glyphs use a `24 × 24` view box and `currentColor`. The shared icon provider replaces
that color with a semantic Qt palette role and supplies common Device Pixel Ratio
variants through one `QIcon`. New glyphs should preserve those constraints rather
than embedding theme colors or adding page-local rendering code.
