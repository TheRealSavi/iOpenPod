# ADR-0233: Share navigation behavior between shell styles

- Status: Accepted
- Date: 2026-11-03
- Extends: ADR-0020, ADR-0126, and ADR-0230
- Dropdown interaction policy and default navigation style superseded by [ADR-0234](0234-unify-desktop-navigation-dropdowns.md).

## Context

The requested Compact top bar offers more horizontal Library space while the
existing sidebar remains useful. Independent navigation or Playlist implementations
would risk diverging capability rules, selection, and drag validation. The sidebar
remains the behavioral baseline; the compact arrangement is a new presentation
choice and introduces no device workflow.

## Decision

Expose **Navigation style** in Library settings with **Sidebar** as the default
and **Compact top bar** as the alternative. Persist `library/navigation-style` on
the Host with values `sidebar` and `compact-top-bar`. Like Player position, this
shell preference applies immediately and does not travel with an iPod.

Both navigation surfaces emit the same application intents and reflect one
current page, selected Playlist, Active iPod, and Library Workspace. They share
route capability rules and action availability. Switching styles preserves the
current page and Playlist selection without reloading the Library.

The compact strip places the device image and Sync with Host on the left, centers
Audio, Video, Playlists, Photos, and Games, and places Maintenance and Settings on
the right. The device image opens Device Summary. Audio contains Albums, Artists,
Genres, Tracks, Genius, Podcasts, and Audiobooks; Video contains Movies, TV Shows,
Music Videos, and Videos. Maintenance contains Backups, Normalize Tags, and
Scrobble Now, retaining Review Changes when manual review is enabled. Hovering the
device image opens Eject and Choose Device actions without grabbing the pointer;
clicking the image still opens Device Summary. The menu stays open while moving
onto its actions and dismisses on leaving, Escape, or a context change. Keyboard
and context-menu access retain those same actions and availability rules. Media visibility follows
the Active iPod's existing capability policy. Audio, Video, Playlists, and
Maintenance also open on pointer hover, switch as the pointer crosses their
headings, and allow a short grace period before dismissing on departure. Clicking
these headings has no effect on selection or menu visibility, even when a popup
owns the mouse events. As clarified on 2026-11-04, these headings are containers:
they have no selected state and accept neither Tab nor click focus. Menu items
remain clickable and keyboard-operable once open. Opening Playlists must preserve
the current page and Playlist selection, including after a Library reload; initial
popup focus must not implicitly select the tree's first item. Ordinary hover handling
does not intercept Track drags or close nested Playlist menus.

The Playlists popup has a New control above the existing `PlaylistTree`. It reuses
the tree's editing, folder hierarchy, reordering, duplicate handling, and regular
Playlist drop behavior. Hovering a valid Track drag over Playlists opens the popup;
hovering over a Playlist Folder expands it. Folders and Smart Playlists retain
their existing rejection of Track membership drops. Workspace generation and edit
revision checks remain authoritative, including when the Active iPod changes
during a drag.

## Consequences

Library navigation gains two presentations without a second source of application
state or device mutation policy. Both styles must receive state updates even when
hidden, and shell tests must cover switching, selection, action availability, and
popup drag behavior. Sync Workspace and fullscreen presentation continue to control
navigation visibility independently of the saved style.
