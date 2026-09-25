# ADR-0009: Use Qt logical pixels and native display metrics

- Status: Accepted
- Date: 2026-08-28

## Context

iOpenPod targets Windows, macOS, and Linux. Those Hosts use different system fonts,
native scale factors, and display densities. macOS Retina screens normally expose a
2× Device Pixel Ratio, while Windows and Linux may use fractional factors such as
1.25× or 1.5×. Hard-coded physical-pixel geometry, forced scale environment
variables, or fonts whose size is specified in pixels can render inconsistently and
can bypass accessibility and Host display preferences.

Qt 6 already maps widget geometry to device-independent logical pixels and creates
appropriately scaled backing stores. Its display policy must be configured before
`QApplication` exists.

## Decision

- Configure Qt's high-DPI scale-factor rounding policy as `PassThrough` before
  constructing `QApplication` so native fractional factors are preserved.
- Rely on Qt 6's automatic Windows, macOS, and Linux high-DPI integration. Do not set
  `QT_SCALE_FACTOR`, `QT_SCREEN_SCALE_FACTORS`, `QT_FONT_DPI`, or legacy high-DPI
  application attributes in production.
- Express layout, spacing, control sizes, and window geometry in Qt logical pixels.
- Express typography in positive point sizes. Derive the scale from the Host's
  General system font, apply a legibility floor, and resolve installed body and
  display families through `QFontDatabase`.
- Retain native window chrome and the default Host Qt style. Apply iOpenPod's visual
  language through semantic `QPalette` roles and restrained QSS rather than forcing
  one platform style.
- Use Qt geometry persistence, which restores windows into available screen space.
- Require SVG, `QIcon`, or explicitly Device-Pixel-Ratio-aware raster assets when
  graphical assets are added.
- Run the GUI tests on Windows, macOS, and Linux. Exercise 1×, 1.5×, and 2× scale
  factors in isolated test processes; scale environment variables are permitted only
  for these probes.

## Consequences

- A Retina window retains the same logical layout while Qt renders a 2× backing
  store, and fractional Windows/Linux scaling does not snap to an unrelated factor.
- Typography follows Host accessibility and platform metrics without dropping below
  the application's legibility floor.
- Widgets and pages remain platform-neutral; display policy stays in the GUI
  presentation boundary.
- Future custom painting must account for `devicePixelRatioF()`, and future raster
  asset work must provide high-density variants or use vector sources.
- Exact visual parity is not promised across native styles. The semantic hierarchy,
  spacing rhythm, contrast, and interaction states are the stable cross-platform
  contract.
