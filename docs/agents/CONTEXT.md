# iOpenPod

iOpenPod is a desktop application for managing and synchronising classic iPods.
Its GUI has a shared visual language that must remain predictable across built-in
and community-authored themes.

## Language

**Theme Renderer**:
The module that turns an authored theme's opaque palette and appearance
preferences into named application paints. It owns color derivation,
compositing, and contrast policy.
_Avoid_: palette helper, color utility

**Resolved theme**:
The immutable output of the Theme Renderer: a named catalog of paints for one
active theme and its accessibility preferences. GUI adapters read it but never
derive or mutate its paints.
_Avoid_: current palette, mutable theme colors

**Authored palette**:
The opaque named colors written in a theme JSON file. It describes intended
visual foundations, never CSS alpha or renderer-specific implementation values.
_Avoid_: CSS palette, raw style tokens

**Paint**:
A resolved application color with a documented recipe, source roles, and either
an opaque result or an intentional transparent layer.
_Avoid_: color string, RGBA token

**Component paint**:
An opaque Paint for a specific interface use such as a selected row, focused
border, or subtle status fill. Its recipe names both the source and backdrop.
_Avoid_: generic state color, translucent component color

**Effect layer**:
A transparent Paint intentionally drawn over unknown content, limited to
scrims, shadows, artwork tints, and gradients.
_Avoid_: reusable alpha token, component state
