# Community Classic firmware mods

Research date: 2026-11-17. Scope: a quick survey of public, first-party projects
for ideas for our Apple 2.0.5 firmware. This is source and release-note research,
not independent hardware validation. No device changes were made.

## Closest comparison: RepriseOS

RepriseOS modifies Apple's firmware and supports Classic 6G, 6.5G and 7G using
Apple 2.0.5. It retains Apple's interface and playback system. Its boot scheme
selects custom firmware, Apple firmware or separately installed Rockbox.
[Project README](https://github.com/lgreitis/osos-lab)

Released features provide particularly useful precedents:

| Mod | What the project implemented | Release evidence |
| --- | --- | --- |
| Dark Mode | An on-device toggle, replacement artwork and fixes for Search, Calendar, lyrics, clocks and previously opened screens. Theme artwork loads from disk. | [0.3.0](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.0), [0.3.1](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.1) |
| Custom EQ | Five adjustable bands, filter type/frequency/gain/Q, precut and a graphical editor. Hold displays the combined response. | [0.3.1](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.1) |
| Play Next / Play Last | Queue whole albums and artists, extending the song actions. | [0.2.9](https://github.com/lgreitis/osos-lab/releases/tag/v0.2.9) |
| Album Artists | Dedicated browsing; newer sorting respects native library order and Sort As metadata. | [0.3.1](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.1) |
| Clicker routing | Off, Speaker, Headphones or Both, including matching Settings previews. | [0.3.0](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.0) |
| DIY accessories | Allows an accessory to complete iAP authentication without Apple's authentication coprocessor. The accessory still needs the protocol handshake. | [0.3.0](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.0) |
| EU volume limit / Song Info | Removes the European volume limit and adds Song Info from song and Now Playing context menus. | [0.3.1 README](https://github.com/lgreitis/osos-lab/blob/v0.3.1/README.md) |

The current README also describes expanded EU volume-limit control, crossfeed,
clipping-aware EQ, broader File Info, Night Shift and playback logging. Song Info
and EU volume-limit removal already appear in the released 0.3.1 README; the
broader features must not be conflated with those earlier implementations. The
website still marks several additions as coming soon, so this survey separates
development documentation from inspected published releases. Up Next's queue
viewer is also marked coming soon. Presence on `main` alone is not a release.
[README](https://github.com/lgreitis/osos-lab),
[website status](https://repriseos.com/)

Useful implementation ideas include warming the display through gamma tables,
and logging actual listening time while excluding pauses and seek jumps.
The game SDK, Doom and NES work are explicitly deferred/incomplete; the game SDK
does not support sound. They are research references, not finished native-game
support to adopt.
[README](https://github.com/lgreitis/osos-lab),
[playback log](https://github.com/lgreitis/osos-lab/blob/main/docs/playback-log.md)

## Older Apple firmware projects: useful ideas, different targets

**iPodFirm** modifies Apple 1.3 on Video 5/5.5. Its documented patches include
album-list artwork, playlist collages and folders, Album Artists, Play Next/Last,
dark-mode switching, storage wake changes for flash mods and shuffle fixes. The
author reports a shuffle overflow above 32,767 songs. That is evidence of a Video
bug, not proof that Classic 2.0.5 has the same defect. Its README separates real
device tests from emulator-only features and explicitly limits supported models.
[iPodFirm features and test status](https://github.com/TheFauxDreamer/iPod5.5Firm)

**iPodWizard** remains useful prior art for graphics, fonts and native layout
editing. Its recent releases add Video 5/5.5 selector-bar colors, clicker tone and
duration, monochrome screen inversion, and editable monochrome Brick parameters.
These are not evidence of equivalent patches for Classic 6G onward. The inspected
theme collection explicitly targets Video 5/5.5 and excludes Classic 6G/7G.
[iPodWizard 1.3.5](https://github.com/TheMetalWizard/iPodWizard/releases/tag/v1.3.5),
[1.3.6](https://github.com/TheMetalWizard/iPodWizard/releases/tag/v1.3.6),
[theme target list](https://github.com/iliketurbos/ipodwizardthemeproject)

## Replacement firmware: feature inspiration

**Rockbox** supplies a much larger independent playback stack. Its own manual
sources document ReplayGain, crossfade, crossfeed, customizable EQ, repeat A-B,
rewind-before-resume and playback logging. These are useful behavior references;
implementing them in Apple's playback path is separate work.
[Playback settings](https://github.com/Rockbox/rockbox/blob/master/manual/configure_rockbox/playback_options.tex),
[sound settings](https://github.com/Rockbox/rockbox/blob/master/manual/configure_rockbox/sound_settings.tex)

**RPod**, a Rockbox fork tested by its author on Classic 7G, adds album and
bookmark cards, a small player beneath menus, simplified navigation and an
end-of-track sleep option. It also hides remaster annotations in displayed song
titles without changing the underlying tags. The author limits the validation
claim to their own devices and does not claim a tested fresh installation.
[RPod](https://github.com/remigius-labs/rpod)

**emCORE/freeMyiPod** is useful boot/runtime infrastructure rather than a
collection of patches to Apple's music interface. Its source includes a Classic
boot menu and installer, Disk Mode and small homebrew programs.
[freeMyiPod application source](https://github.com/freemyipod/freemyipod/tree/master/apps)

## What users are requesting

The follow-up review inspected RepriseOS open and closed issue lists, selected
maintainer replies and pending audiobook pull requests, its feature wishlist,
and community discussions linked below. These are concrete examples of demand,
not a popularity ranking or a representative survey. Issue descriptions are
reports and requests; they do not independently prove the stated stock behavior.

| Requested mod | Concrete need | Observed status on research date |
| --- | --- | --- |
| Editable queue and playlists | View upcoming tracks, remove/reorder queued items, rename On-The-Go playlists and add/remove tracks after saving. | Open [queue request #5](https://github.com/lgreitis/osos-lab/issues/5) and [playlist request #26](https://github.com/lgreitis/osos-lab/issues/26). Released Play Next/Last is only part of this request. |
| Better album organization | Chronological discographies, separate sort rules for each view, Album Artist ordering and visible disc numbers. | Open [#43](https://github.com/lgreitis/osos-lab/issues/43), [#66](https://github.com/lgreitis/osos-lab/issues/66), [#9](https://github.com/lgreitis/osos-lab/issues/9), [#12](https://github.com/lgreitis/osos-lab/issues/12), [#72](https://github.com/lgreitis/osos-lab/issues/72). Native Sort As fixes do not fulfill all these requests. |
| Idle-screen and appearance choices | Keep Now Playing visible, show a 24-hour idle clock, change the clock layout/background, choose accent colors or disable split menus. | Open [#65](https://github.com/lgreitis/osos-lab/issues/65), [#68](https://github.com/lgreitis/osos-lab/issues/68), [#10](https://github.com/lgreitis/osos-lab/issues/10), [#3](https://github.com/lgreitis/osos-lab/issues/3). |
| Artwork fit | Show a whole rectangular cover instead of cropping it to fill the square. | Open [#19](https://github.com/lgreitis/osos-lab/issues/19); the firmware and Host artwork-generation responsibilities still need investigation. |
| Long audiobooks and faster seeking | Avoid playback ending near 13.5 hours and avoid timeouts when jumping to late chapters. | Open [#18](https://github.com/lgreitis/osos-lab/issues/18), with unmerged [64-bit time fix #62](https://github.com/lgreitis/osos-lab/pull/62) and [chunk-based seek #63](https://github.com/lgreitis/osos-lab/pull/63). Contributors report physical tests; these are not published-release evidence. |
| Larger libraries and flash storage | Avoid RAM-related library limits and use capacity beyond the older Classic storage limit. | Open [library request #4](https://github.com/lgreitis/osos-lab/issues/4) and [capacity discussion #30](https://github.com/lgreitis/osos-lab/issues/30). Comments contain mixed setups and unsupported explanations; they do not qualify our capacity support. |
| Listening statistics | Total plays, listening duration, skips and top artists/albums/tracks on the device. | Open [#51](https://github.com/lgreitis/osos-lab/issues/51); author reports a Classic 7G prototype with screenshots. A prototype is not an upstream release. |
| Audio controls | Redefine Apple's EQ presets; add crossfeed for strongly separated stereo recordings. | Open [preset request #67](https://github.com/lgreitis/osos-lab/issues/67). [Crossfeed #58](https://github.com/lgreitis/osos-lab/issues/58) remains open although current development documentation already describes an implementation. |
| Default boot choice | Choose Apple firmware, RepriseOS or Rockbox without holding buttons at every boot. | Open [#27](https://github.com/lgreitis/osos-lab/issues/27); relevant to a multiple-OS design, not automatically to our current installer. |

Several requests have already become released features: album/artist queueing
([#6](https://github.com/lgreitis/osos-lab/issues/6)), clicker routing
([#22](https://github.com/lgreitis/osos-lab/issues/22)) and graphic EQ
([#14](https://github.com/lgreitis/osos-lab/issues/14)). The releases cited above
provide implementation evidence in addition to their closed status.

Closed does not mean implemented. The large-battery gauge request
[was closed after a maintainer raised accuracy concerns](https://github.com/lgreitis/osos-lab/issues/52#issuecomment-6755022338)
about varying aftermarket cells. HFS+ support
[was closed because it remains on the wishlist without a timeline](https://github.com/lgreitis/osos-lab/issues/38#issuecomment-6419359579).
The wishlist also includes FLAC, resource/font overrides, debug facilities and
easier Phase song synchronization. Its five-band EQ entry is stale relative to
0.3.1, demonstrating why wishlist entries need release/source checks.
[Project wishlist](https://github.com/lgreitis/osos-lab/blob/main/PATCH-WISHLIST.md)

Community discussions add requests for
[selectable mods to conserve RAM](https://www.reddit.com/r/ipod/comments/1x21bdy/comment/peyrxte/),
[timestamps for every listening event](https://www.reddit.com/r/ipod/comments/1xfvrio/comment/19rolvzo3cgcl/),
[left/right balance](https://www.reddit.com/r/ipod/comments/1xfvrio/comment/19rop7spvgxj8/)
and [mono output](https://www.reddit.com/r/ipod/comments/1xfvrio/comment/19roxa88xbhz7/).
A broader discussion asks for FLAC, folder-based loading, ReplayGain, scrobbling
and queue control while preserving Apple's interface. These are user goals,
not evidence that their suggested implementation routes work.
[Original-OS experience discussion](https://www.reddit.com/r/IpodClassic/comments/1xukhba/og_ipod_software_experience/)

Our inference: timestamped listening events fit iOpenPod's existing scrobbling
work particularly well, while optional mods with explicit memory costs match
both community interest and this project's intended mod selection. Chronological
album browsing, idle-clock controls and audiobook fixes provide concrete goals
that are narrower than a complete UI or audio-engine replacement.

## Implications for our first mods

These are recommendations from the survey, not adopted architectural decisions:

- Start with a native Settings toggle and a visible mod such as Dark Mode or
  clicker routing. This exercises settings, persistence and native UI integration.
- Follow with Album Artists or Play Next/Last: both have direct Apple-Classic
  precedents and improve everyday listening.
- Treat custom EQ and accurate playback logging as deeper audio/state work.
- Keep Parachute as its own runtime investigation; the surveyed Classic homebrew
  work does not establish a complete game SDK.

The projects show that substantial additions can coexist with Apple's interface.
They do not establish drop-in patch compatibility with our bootloader, firmware
layout or mod registry. Implementation should inspect each feature's hooks,
memory ownership and persistent state against our exact 2.0.5 image.
