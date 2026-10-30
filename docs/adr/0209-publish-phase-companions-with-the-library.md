# ADR-0209: Publish Phase companions with the Library

- Status: Accepted
- Date: 2026-10-30
- Chart generation policy superseded by [ADR-0210](0210-analyze-phase-playlist-audio-with-librosa.md).

A Phase Playlist remains an ordinary editable Playlist or Smart Playlist, with
one explicit selection per Library Workspace. Selecting another clears the prior
selection in the same draft edit. A gamepad sidebar icon distinguishes it
without changing its name. The editor offers selection when the installed game
catalog contains Phase; an existing selection can also be cleared after removal.

Loading selects the full playlist persistent ID from the game's Phase Library
index, falling back to the first eligible playlist named exactly `Phase` if no
ID matches. Missing or invalid index headers use the same name fallback. The
historical MHYP `+0x52` value 25 never determines selection. Saving still writes
25 as a producer convention for changed selected playlists. Nano 5 can select an ordinary
kind-0 SQLite container through that same ID. We keep that existing SQLite
classification rather than inferring an unverified mapping from MHYP to kind 25.
Changing the designation updates MHYP counterparts; unrelated raw values survive
ordinary edits. The same ID-first resolver applies after saving and across source
overlays. The captured index fingerprint is checked before preparation and save,
so external selection changes require reloading rather than silently changing
the playlist being edited. The selection header reader accepts extended index
content independently of the deliberately restricted index writer.

iPodDB owns the index and analysis byte formats. iOpenPod prepares companions
after database preparation assigns final identities, then includes them in the
same recoverable Storage Transaction as iTunesDB/iTunesCDB and SQLite. Source
index, chart and installation preconditions are rechecked before publication.
Cancellation and disconnected sessions stop preparation. There is no independent
device write from a dialog or codec, and no runtime firmware/emulator dependency.

At the user's request, missing charts contain synthetic events at one-second
intervals rather than actual audio analysis. Existing charts are retained. Only
music with whole-second duration 30 through 1800 receives an index record;
ordinary Playlist membership is unchanged, and repeated tracks share one chart.
Removing the selection or deleting the selected Playlist writes an empty index.
This prevents the game's title fallback from using stale index records. A playlist
still named exactly `Phase` remains selected by the game's name fallback even
with an empty index; rename it or select another playlist to change that. Old
charts remain on disk for reuse; this feature does not delete game data.

The first writer supports the verified minimal index layout. It rejects an
extended or malformed existing index instead of discarding Unknown Data. The
generated chart format passed the native build-3168002 parser at the minimum,
representative and maximum durations. Its native index reader also accepted
populated, selected-but-empty and cleared application-generated indexes. Virtual
Classic and Nano 5 saves verify final IDs, companion files and rejection of a
changed installation after review; Nano 5 checks both its SQLite container and
Dynamic container UI row. Physical gameplay and the Video-specific
game executable remain separate acceptance work; the placeholders are not
claimed to provide musically meaningful gameplay.
