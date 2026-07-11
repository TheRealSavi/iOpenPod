# iOpenPod GUI Design System

This is the reusable design language for the PyQt iopenpod.gui. New UI should use
`src/iopenpod/gui/styles.py` primitives instead of local one-off styles.

## Principles

- Familiar desktop controls first: buttons look clickable, inputs look editable,
  destructive actions look distinct, disabled states look inactive.
- One primary action per surface. Use `accent_btn_css()` only for the action that
  advances the current task.
- Stable geometry: controls use 4px-grid spacing, 6px control radius, 8px panel
  radius, and fixed hit-target heights from `Design`.
- Quiet hierarchy: regular text stays regular weight, command labels use medium
  weight, primary or selected controls use semibold.
- State changes are visible and consistent: hover brightens surface, press darkens
  or compresses emphasis, selected chips get an accent ring.
- Local color literals are allowed only for media-derived artwork, charts, or
  device-specific accent math. App chrome uses `Colors`.

## Code Primitives

- `button_css(role, size)`: default entry point for text buttons.
- `accent_btn_css(size)`: primary action.
- `danger_btn_css(size)`: destructive action.
- `icon_btn_css(size)`: square symbol-only controls.
- `chip_btn_css(size)`: selectable pills, filters, IDs, compact segments.
- `input_css()`, `combo_css()`, `spin_css()`, `checkbox_css()`,
  `title_input_css()`: standard form controls.
- `table_css()`, `context_menu_css()`: standard table/menu surfaces.
- `panel_css(object_name)`: object-scoped `QFrame` panel/card style.
- `progress_bar_css()`: standard horizontal progress bars.
- `make_label()`, `make_section_header()`, `make_separator()`: typography helpers.

## Roles

- `primary`: one task-forward button, solid accent fill.
- `secondary`: normal bordered command.
- `quiet`: low-emphasis disclosure or inline command.
- `danger`: destructive command with red outline/fill states.

## Sizes

- `sm`: dense toolbar/chip/dialog secondary controls.
- `md`: default app controls.
- `lg`: confirmation dialogs and large task actions.

## Review Rule

Any new `setStyleSheet()` containing `QPushButton` should be questioned. Prefer
role helpers unless the control is a custom painted/media-derived component.
