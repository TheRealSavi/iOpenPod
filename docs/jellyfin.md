# Jellyfin Play Count Sync

iOpenPod can synchronize play counts in both directions between the Active iPod
and one Jellyfin account. Only music play counts are synchronized. Ratings,
favorites, last-played dates, and media files are not.

## Using it

1. Open Settings → Sync → Jellyfin.
2. Enter the server address (for example `http://192.168.1.20:8096`), your Jellyfin
   username, and password, then choose **Connect**.
3. With an iPod selected, choose **Sync play counts now**.

Jellyfin 10.9 or later is required. The password is sent once to obtain an access
token. Only the token is kept, in the native OS keyring. Global settings keep the
non-secret server address, username, and a device ID so that Jellyfin lists
iOpenPod as one device across sign-ins.

## How counts are merged

For each matched song, iOpenPod remembers the total both sides agreed on and the
count it last saw on each side. Plays made on either side since then are added:

```text
new total = agreed + new iPod plays + new Jellyfin plays
```

- **First pairing:** the larger of the two counts wins. This can miss plays made on
  both sides before the first sync, but never counts one play twice.
- **Interrupted sync:** the play counts and the memory are saved to the iPod in one
  recoverable Storage transaction, so they land or roll back together. The memory
  is written with final values before Jellyfin is updated; Jellyfin updates that
  fail are recorded with Jellyfin's previous count and retried next time. Any
  interruption can at worst miss a play, never count one twice.
- **Decreases** (for example, marking a song unplayed in Jellyfin) are not
  propagated. The merged total is restored to that side.
- Raising an iPod count above zero also marks the song as played. Counts sent to
  Jellyfin also set Jellyfin's played flag.
- The iPod's unscrobbled play counter is not changed, so plays that came from
  Jellyfin are not scrobbled as iPod plays.

## The memory lives on the iPod

The memory is stored on the iPod it describes, at
`iPod_Control/iOpenPod/Integrations/jellyfin-play-counts-v1.json`, so every computer that syncs
the iPod merges from the same baseline. Plays merged by one computer are never
added again by another, on Windows, macOS, or Linux. The document is keyed by
Jellyfin server and user, then by the iPod's persistent Track ID; it needs no
device key because of where it lives. Entries for songs no longer on the iPod are
dropped. It is compact JSON limited to 8 MiB, enough for roughly 90,000 songs.

Backup Snapshots include the document, so restoring a snapshot restores the
memory together with the play counts. An unreadable document stops the sync before
anything changes and is preserved; remove it to start over with a first pairing.

## Matching

Only music Tracks with a persistent iPod Track ID are considered. A song matches a
Jellyfin audio item when, after case and whitespace normalization:

- title and album are equal;
- an artist name agrees (Track artist or album artist against Jellyfin artists or
  album artist, including "A feat. B" against Jellyfin's split artists);
- track and disc numbers agree when both are known; and
- lengths differ by at most three seconds when both are known.

A pairing is remembered by Jellyfin item ID once established. Songs with no match,
or with several candidates, are reported and skipped. Two iPod songs that would
claim the same Jellyfin item are both reported as ambiguous.

## Device safety

The iPod is changed only through the existing Library preparation and verified
save, under the same exclusive device reservation as a Library save. The memory
document joins that save's Storage transaction through the coordinator's
`application_writes` argument, which accepts only documents under the reserved
`iPod_Control/iOpenPod/Integrations/` folder; when only the memory changes, it is written alone
with a generation-checked atomic replacement. Sync is refused while the Library has
unsaved edits. Jellyfin is updated only after the iPod save is confirmed.

## Code map

| Path | Role |
| --- | --- |
| `src/iOpenPod/app/jellyfin/client.py` | Jellyfin HTTP API (version check, sign-in, audio items, user data) |
| `src/iOpenPod/app/jellyfin/matching.py` | iPod Track to Jellyfin item matching |
| `src/iOpenPod/app/jellyfin/state.py` | Per-song baselines and the merge rule |
| `src/iOpenPod/app/jellyfin/device_state.py` | The memory document stored on the iPod |
| `src/iOpenPod/app/jellyfin/service.py` | The workflow without Qt |
| `src/iOpenPod/app/jellyfin/controller.py` | Qt worker, device reservation, composition root |
| `src/iOpenPod/app/jellyfin/token_store.py` | Access token in the OS keyring |
| `src/iOpenPod/GUI/widgets/jellyfin_settings.py` | Settings → Sync controls |

`MainWindow` composes the integration and passes its controls to `SettingsPage`
through the `sync_sections` argument. `DeviceCoordinator` provides the
`application_writes` argument and the application document methods it uses.
