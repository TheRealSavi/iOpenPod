---
layout: guide
title: Add your own songs to Phase on iPod | iOpenPod
description: Create a Phase Playlist with iOpenPod, add music from your iPod library, and generate gameplay analysis. Learn when the optional instrument analyzer is useful.
heading: Play your own music in Phase on your iPod
lead: iOpenPod can prepare a Phase Playlist from songs in your iPod library. Saving the playlist generates the audio analysis Phase needs to turn those songs into gameplay.
breadcrumb_title: Phase Playlist
body_class: iop2-page guide-page
permalink: /guides/phase-playlist-ipod/
og_image: /screenshots/iop2/phase-playlist.webp
og_image_alt: A Phase Playlist in iOpenPod with its game icon and music tracks
cta_heading: Make your Phase Playlist with iOpenPod
cta_description: Download the latest iOpenPod, install Phase on a compatible iPod, and prepare your own music. The app is free; optional donations support development.
related_guides:
  - /guides/install-ipod-click-wheel-games/
  - /guides/sync-ipod-without-itunes/
  - /guides/flac-to-ipod/
---

Start with the [latest iOpenPod]({{ '/#install' | relative_url }}) and
[install Phase through Games]({{ '/guides/install-ipod-click-wheel-games/' | relative_url }})
on a compatible iPod. Installing the game and preparing songs for it are separate steps.

## Before you create the playlist

- Phase must already be installed on the selected iPod.
- The songs you want to play must be in its music library. Use
  [Sync with Host]({{ '/guides/sync-ipod-without-itunes/' | relative_url }}) to add
  local music from your computer first.
- Set up FFmpeg through **Settings → Media Tools** so iOpenPod can decode the
  music for analysis. See the
  [media-tool setup steps]({{ '/install-help/#helper-tools' | relative_url }}).
- Keep the iPod connected while the playlist and analysis are saved.

## Create or select a Phase Playlist

1. **Select your iPod in iOpenPod.** Confirm that Phase appears in Games and that
   the songs you want are in the music library.
2. **Create or edit a playlist.** In the playlist editor, select
   **Use as the Phase Playlist**. The designated playlist has a Phase marker.
3. **Add your songs and choose their order.** You can edit it like an ordinary
   playlist. iOpenPod uses the actual audio, not just track titles, for analysis.
4. **Save the changes.** Library edits save automatically by default. If you use
   **Draft all changes**, apply the pending changes to prepare the playlist.
   Watch the status bar while iOpenPod analyzes new or changed songs and saves
   the game's companion data.
5. **Wait for completion, then eject.** Launch Phase on the iPod and check the
   playlist in the game.

{% include product-shot.html file="phase-playlist.webp" width=1741 height=1048 alt="A Phase Playlist in iOpenPod showing the Phase marker and the selected songs" caption="The designated Phase Playlist supplies the music used for gameplay analysis." %}

## Is the optional instrument analyzer required?

No. Acoustic analysis works without the optional model. It measures the music's
rhythm and attacks, with an emphasis on audible percussion.

For additional instrument analysis, choose **Settings → Media Tools → Set Up
Phase Analysis**. This downloads a separate analysis runtime and model and can
use several gigabytes. It can use GPU acceleration where supported and available;
CPU and acoustic fallbacks remain available. A GPU is not required to prepare
a Phase Playlist.

The optional model estimates instrument and vocal parts to provide more musical
evidence. It is not a promise of perfect note charts for every song. If optional
analysis fails, iOpenPod can use acoustic analysis. Unreadable or undecodable
audio still needs attention.

## Why does the first save take longer?

New songs require audio decoding and analysis. Duration depends on the songs,
device connection, computer, and selected analysis method. Start with a few songs
to check the workflow on your iPod before preparing a large playlist.

iOpenPod reuses matching analysis on later saves. Changing playlist order does
not necessarily require analyzing every song again. Older cached analysis can
need validation or regeneration after an application update.

## Phase does not show my songs

Check that Phase is installed, that the intended playlist is designated as the
Phase Playlist, and that the Library save finished successfully. An ordinary
playlist with the word "Phase" in its name does not by itself establish that
the required game data was prepared.

If preparation reports an audio-decoding error, check FFmpeg in Media Tools and
the affected song. If the device disconnected, reconnect it and follow any
recovery instructions before saving again. Then eject and check the game on the
iPod; desktop analysis checks do not establish playback on every physical device.
