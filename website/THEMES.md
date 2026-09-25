# Themes

iOpenPod themes are ordinary JSON files in the user settings directory's
`themes/` folder:

- macOS: `~/Library/Application Support/iOpenPod/themes/`
- Windows: `%APPDATA%/iOpenPod/themes/`
- Linux: `~/.config/iOpenPod/themes/`

The app copies the Catppuccin files there when it creates the folder for the
first time. It never restores an individual file, so deleting a theme removes
it from the next launch. The permanent `Dark` and `Light` themes are built into
the application and cannot be deleted.

The file name is the stored theme ID (for example, `ocean-night.json` becomes
`ocean-night`); `name` is the readable menu label. IDs may use letters,
numbers, periods, underscores, and hyphens.

```json
{
  "name": "Ocean Night",
  "type": "dark",
  "colors": {
    "accent": "#5cc8ff",
    "accent_light": "#a4e4ff",
    "background": "#10212f",
    "background_alt": "#152b3c",
    "surface": "#1e3d52",
    "surface_alt": "#30506a",
    "surface_raised": "#406987",
    "surface_hover": "#507b9b",
    "surface_active": "#3b6685",
    "menu_background": "#30506a",
    "dialog_background": "#152b3c",
    "tooltip_background": "#30506a",
    "text_primary": "#e8f5ff",
    "text_secondary": "#c5deed",
    "text_tertiary": "#a0bdce",
    "text_disabled": "#738d9d",
    "border": "#52718a",
    "border_subtle": "#30506a",
    "gridline": "#30506a",
    "danger": "#f07979",
    "success": "#72cf9b",
    "warning": "#f0c56e",
    "info": "#77c7f4",
    "star": "#f5d67a",
    "sync_cyan": "#72d9d9",
    "sync_purple": "#b8a1ed",
    "sync_magenta": "#ec9fc6",
    "sync_orange": "#eea56d",
    "sync_freed": "#6bd3c0",
    "playlist_smart": "#b8a1ed",
    "playlist_podcast": "#72cf9b",
    "playlist_master": "#6f97b1",
    "playlist_regular": "#5cc8ff"
  },
  "high_contrast": {
    "text_primary": "#ffffff",
    "border": "#ffffff"
  }
}
```

Every `colors` value is an opaque `#RGB` or `#RRGGBB` value. Alpha values and
`rgb()`/`rgba()` values are deliberately invalid: the application owns alpha
for derived effects, never the theme author.

Only this compact foundation palette is required:

`accent`, `background`, `background_alt`, `surface`, `surface_raised`,
`text_primary`, `text_secondary`, `text_tertiary`, `text_disabled`, `border`,
`danger`, `success`, `warning`, and `info`.

Every other documented color is an optional opaque override. The Theme
Renderer fills omitted roles through stable, named recipes: for example,
`accent_light` is derived from `accent`; stars default to `warning`; playlist
and sync categories default to relevant accent, status, or text colors. A
theme can provide a full palette when it has an intentional hierarchy—as the
bundled Catppuccin themes do—without making every community theme repeat app
specific colors.

`high_contrast` is optional. It accepts any subset of the same color names.
When increased contrast is enabled, iOpenPod applies automatic text and border
adjustments for names not supplied there; supplied values win.

## How colors are composed

Theme JSON is the authored palette: every value is a direct opaque visual
foundation. The Theme Renderer is the single application seam that turns those
foundations into the colors used by the interface.

- Direct paints—surfaces, text, borders, menus, dialogs, and tooltips—remain
  the exact opaque hex colors authored in the theme.
- Component paints—selection fills, button states, status tints, and focus
  borders—are opaque results. Their named renderer recipes declare both source
  color and backdrop, then pre-compose the final color.
- Effect layers—only modal scrims, shadows, artwork tints, crop masks and
  guides, thin scrollbar thumbs, and gradients—stay transparent. They are
  explicitly marked as layers because their content genuinely must show
  through. Fixed-source effect recipes live in the renderer. Image-derived
  effects use their supplied artwork color with application-owned alpha, never
  a theme-file value.

The renderer preserves a theme's `accent` and `accent_light` values. Only a
custom accent selected in iOpenPod settings is contrast-normalized; then every
accent-derived paint and the regular-playlist title bar follows that one result.

| Color family | Required | Used for |
| --- | --- | --- |
| `accent` | Yes | Primary actions and controls |
| `background`, `background_alt` | Yes | Window canvas and inset backdrop |
| `surface`, `surface_raised` | Yes | Primary panels and raised controls |
| `text_primary`, `text_secondary`, `text_tertiary`, `text_disabled` | Yes | Text hierarchy |
| `border` | Yes | Prominent outlines and input borders |
| `danger`, `success`, `warning`, `info` | Yes | Status and notification meaning |
| `accent_light`, `surface_alt`, `surface_hover`, `surface_active` | No | Accent and elevation refinements |
| `menu_background`, `dialog_background`, `tooltip_background` | No | Component-specific backgrounds |
| `border_subtle`, `gridline`, `star` | No | Hairlines, table rules, and ratings |
| `sync_cyan`, `sync_purple`, `sync_magenta`, `sync_orange`, `sync_freed` | No | Sync-stage and storage refinements |
| `playlist_smart`, `playlist_podcast`, `playlist_master`, `playlist_regular` | No | Playlist/category title-bar refinements |
