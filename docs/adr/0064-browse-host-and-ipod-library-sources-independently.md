# ADR-0064: Browse Host and iPod Library Sources independently

- Status: Superseded by ADR-0067
- Date: 2026-09-18
- Extends: ADR-0019 and ADR-0063

## Context

A completed Host Media Scan already produces the same immutable Library Snapshot
contract as an iPod Library, but the GUI previously reported counts and retained the
snapshot without presenting its records. Loading that snapshot into the Active iPod's
Library Workspace would reuse the widgets, but it would also discard or obscure the
device-bound Library Draft and could expose iPod-only edit, export, playback, or save
actions against Host identities.

Duplicating Host-specific page designs would make equivalent Tracks, collections,
Playlists, and Photos behave differently based only on their source.

## Decision

The GUI exposes iPod Library and Host Media Library as explicit Library Source
choices. A completed Host Media Scan becomes the current choice and is projected
through new instances of the existing Albums, Artists, Genres, Tracks, Playlists,
Photos, Podcasts, Audiobooks, Movies, TV Shows, Music Videos, and Videos page classes.
Switching sources replaces the widgets mounted at those stable routes without
changing the route set or reconstructing either source.

The Host presentation owns a separate read-only Library Workspace and Qt model set.
It never replaces the Active iPod's Library Workspace, draft revision, or retained
source documents. Device-only mutations, export, Queue, Player, and review actions
are not connected to the Host presentation. The latest completed Host Media Library
stays available in memory until another scan replaces it or the application closes.

Host Photos use the common lazy, byte-bounded Photo presentation pipeline. The Host
loader reads the source-specific Host path outside the GUI thread, downsamples before
caching RGB pixels, and rejects the read when file size or modification time no
longer matches the completed scan.

## Consequences

Users can inspect both sides of a future Sync with the same browsing vocabulary and
visual behavior while an unsaved iPod Library Draft remains intact. Host Playlists
and Photos use the same virtualized widgets, selection behavior, sorting, and search
as their iPod counterparts.

This decision does not implement comparison, Sync planning, Host playback, Host
metadata editing, or publication. Those workflows require their own source authority
and review policy rather than borrowing the Active iPod's capabilities.
