# ADR-0246: Edit Track EQ with canonical presets and preserve it during Sync

- Status: Accepted
- Date: 2026-11-06
- Extends: ADR-0026 and ADR-0076

## Context

Firmware research establishes 22 built-in Track EQ presets with IDs 100–121.
The inspected Mini 2, Video 5/5.5 and four Classics accept the same canonical
MHOD7 marker strings, despite different internal consumers. Plain names do not
provide equivalent configuration. The current text editor exposes protocol data,
while Host metadata merging can erase an iPod-only EQ assignment.
See [the firmware comparison](../research/ipod-eq-evolution-and-device-support.md).

## Decision

The Track metadata editor offers the 22 presets and **Use iPod setting**. The
latter explicitly clears the Track assignment; it does not force global EQ off.
Controls use numeric `EqualizerPreset` IDs internally, while the editor and Track
table display shared translated labels. German and Spanish join the English
source labels through the existing runtime translation mechanism.

The public `iPodDB.library` interface exposes preset IDs and canonical Track text
conversion, backed by a small pure implementation module.
Explicit named choices encode `#!#100#!#` through `#!#121#!#`; inheritance encodes
empty text through the existing writer. Recognition is deliberately restricted
to canonical markers and empty text. Permissive malformed firmware parsing,
language-dependent name lookup and playback prediction remain separate research.

`TrackMetadata.equalizer` retains raw text to preserve Unknown Data. Unknown
values display **Unknown preset (preserved)** without exposing IDs or markers.
Mixed and unknown values remain unchanged unless the user selects a replacement.
Reset restores the initial choice and cancels the edit. Existing Library Workspace
and iPodDB publication workflows remain authoritative; no new device I/O path is
introduced.

Track EQ is owned by explicit Library edits. Sync preserves it through Host
metadata merges and retained-media replacement. Host tag comparisons and optional
embedded media-tag work exclude EQ, since the Host tag source has no EQ authoring
contract. A user clears EQ explicitly in the editor. Persisted v1 Sync digests
retain their existing byte representation, including the raw EQ slot, so existing
baselines keep their meaning. Planner decisions require a differing Host-owned
projection before an EQ-only digest difference can request a metadata update.

## Consequences

The catalog and encoder are shared; global Preferences editing and effective
playback prediction are outside this change. Unknown/noncanonical values survive
unrelated edits without being silently converted to supported presets. An EQ-only
edit changes database metadata without scheduling media-file tagging.

Regression coverage includes every canonical ID, unknown and mixed values,
explicit inheritance, reset, packaged translations during an in-progress edit,
database publication, original v1 digest compatibility, and verified virtual-device
Sync for both metadata-only and audio-replacement paths. Physical device playback
and global Preferences reload behavior remain separate acceptance work.
