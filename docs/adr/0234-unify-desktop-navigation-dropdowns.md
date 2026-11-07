# ADR-0234: Unify desktop navigation dropdowns

- Status: Accepted
- Date: 2026-11-04
- Supersedes: ADR-0233's dropdown interaction policy and default navigation style

## Context

Separate Device, action-menu, and Playlist popup implementations accumulated
different focus, hover, dismissal, and activation behavior. Making headings inert
did not provide a complete desktop navigation model. The requested replacement
allows keyboard access while keeping highlighting distinct from activation.

## Decision

Compact top bar is the default Navigation style. Existing saved preferences remain
authoritative, and Sidebar remains available in Library settings.

All five compact navigation dropdowns use `HoverDropdown` and one
`HoverDropdownGroup`. The group owns trigger events, popup exclusivity, placement,
pointer departure, keyboard switching, focus return, and nested-menu lifetime.
Content supplies `QAction` rows and optionally a native tree view. Playlist-specific
code supplies its content size and identity-checked drag behavior, not another
ordinary popup interaction implementation.

Tab focuses a heading without opening it. Hover opens it without choosing an item.
Click, Enter, Space, or Down opens it with the first enabled visible item active;
Up opens the last. Up/Down move the active item, Home/End move to the ends, and
Enter/Space activate. Disabled and hidden items are skipped. Left/Right switch
headings, except when opening a submenu or navigating a Playlist Folder. Escape
closes and returns focus to the heading. Tab/Shift+Tab close and continue through
the main window's focus order. Keyboard-open menus stay open while the pointer is
elsewhere; subsequent pointer movement resumes hover behavior. Pointer departure
has a short grace period. Outside clicks, application deactivation, shell movement,
and context changes dismiss the dropdowns and their nested menus.

The heading's hover, open, pressed, and keyboard-focus states are distinct. A row's
active highlight indicates where Enter will act. A checkmark indicates the current
page or committed Playlist selection. Neither hovering nor moving the active row
changes the current page. `PlaylistTree` opts into activation-only selection for
this surface; the Sidebar retains its existing selection behavior. Empty and locked
Playlist content retains the same availability rules as the existing workflow.

Device uses the same heading behavior. Device Summary is its first action, followed
by Eject and Choose Device. Summary and Eject retain their existing availability
rules. Photos, Games, Settings, and Sync remain direct controls.

## Consequences

Interaction fixes and theme states now have one implementation and one behavioral
test matrix across all five dropdowns. The Playlist tree retains native hierarchy,
context actions, scrolling, editing, and drag validation. Its highlighted row is
presentation state, separate from the application's committed selection. The shared
popup supports a nonactivating drag mode so opening it does not grab a Track drag.
