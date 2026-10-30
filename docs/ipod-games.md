# IC-Info and Games

## Installed games

The Games page displays a responsive grid read from the Active iPod's
`iPod_Control/Games_RO` directory through Storage. It loads in the background when
the Games page opens, and clears captured data when selection changes or the
device disconnects. Each game folder contributes one card: the manifest's
`Platforms` array describes executable variants, not separate games.

The pure `iPodDB.games` contract reads `Name`, `Version`, and `GUID` from
`Manifest.plist`. Version strings are preserved, including three-part versions.
Folder identifiers may be alphanumeric. `iTunesArtwork` supplies the extensionless
JPEG cover; the observed 320×240 covers retain their landscape aspect ratio.
No game executable or purchase metadata is read to build the grid.

Manifestless auxiliary folders are skipped. Malformed metadata remains visible
under its folder identifier with an unavailable version, and missing/invalid
covers use the gamepad glyph. One bad game does not discard the remaining catalog.
Reads, image dimensions, installation counts, and accumulated cover bytes have
explicit bounds. The installed catalog is display state, not proof that a game
is authorized to launch.

Read-only acceptance on the connected device returned 49 games and 49 covers
with no metadata errors. Synthetic tests cover malformed input, executable
variants, asynchronous loading, missing covers, and stale results after disconnect.

## Authorization preparation

Pressing **Gimme Games** prepares the complete game collection on the Host, then
runs the existing IC-Info preparation/merge and opens an **Available games**
dialog from the bundled `game-catalog.json`. Its artwork,
titles, versions, card painting, and equalized layout use the same grid as installed
games. Ownership preparation runs silently: progress, success, counts, and
already-authorized messages are not shown. Only failures preventing preparation
are surfaced in the page and dialog.

Entries marked `All` are shown for all supported models. Entries marked
`VideoOnly` appear exclusively for the iPod Video 5th/5.5th-generation family;
Classics and Nanos do not receive them. The current resource contains 56 entries
for Video and 49 for other supported models. A search field in the dialog header
filters titles using a case-insensitive literal match. Installed games are always
excluded, including when searching or clearing the search. Matching uses the
manifest GUID, with the folder identifier as a fallback for damaged metadata;
an installed older version also hides that game from the offering.

The dialog uses the same installed-game snapshot as the Games grid; opening or
reopening it does not rescan the device. Until that initial scan completes,
no offerings are displayed. When the dialog grid has no results, it displays
**No available games** centered in the content area. The Games page adds no
loading or empty-state text; operation failures are surfaced. Filtering retains
the decoded artwork and window. The dialog closes on an Active iPod change or
disconnect. Clicking a game card, or pressing Space on its focused card, checks
it using the same selection control as Host Sync album cards. Checked games stay
selected across searches. **Add** installs every checked game; it stays disabled
until authorization preparation and the installed-game scan have succeeded.
The footer's bottom-left **Select all** button checks every currently displayed
available game. It respects the search query and installed-game exclusion, retains
checks outside the current search, and is disabled while installation runs or no
games are displayed.

Closing and reopening the catalog for the same Active iPod reuses its window,
grid, and decoded artwork, avoiding native-window reconstruction on reopening.
Each click still runs preparation with the normal device write reservation.
Changing the Active iPod discards the retained dialog and starts fresh for the
new connection.

The Library sidebar's Games page provides one **Gimme Games** action. It prepares
the bundled Classic 6.5 IC-Info.sidb for the Active iPod and merges its account/key
records with an existing authorization store. The dialog's separate **Add** action
copies selected game executables and resources without modifying iTunesDB.

The sidebar entry appears only for an Active iPod with native click-wheel games
support: Video 5/5.5, Classic 6/6.5/7, and Nano 3/4/5. The action still requires
the qualified firmware release and writable connection described below.

## Game files

The [four-game library investigation](research/unique-game-library-contracts.md)
traces Song Summoner listening rewards, iQuiz custom packs, musika scores and
The Sims DJ purchases through game code and firmware. It records preservation
requirements and proposed support work separately from implemented behavior.

Phase has an additional music-playlist and per-song analysis workflow, separate
from installing its executable. The [firmware and game investigation](research/phase-playlist-contract.md)
records its persistent-ID selection, writable analysis files, and native-tested
Phase Library index. The [nano 5 verification](research/phase-nano5-firmware-contract.md)
traces its SQLite-backed SDK identities and native recognition of distinguished
kind 25. See [Phase audio analysis](phase-audio-analysis.md) for the implemented
companion generation when saving the Phase Playlist.

The app bundles `game-catalog.json` with artwork and the small
`game-downloads.json` release/content index. Game ZIPs, the old `SHA256SUMS`, and
executable payloads are absent from the assets and excluded from release builds.

On the first Gimme Games click, the Application Layer downloads the complete
[version16 preservation release](https://github.com/Olsro/ipodclickwheelgamespreservationproject/releases/tag/version16)
asset `iPod.Games.Files.7z` (1,800,542,124 bytes). The shared status bar shows
byte progress during download and extraction. The source SHA-256 and all 56
extracted game content fingerprints are verified before the browser opens.
Both compatibility groups are extracted, regardless of the current device;
the catalog still applies model filtering when offering games.

The default Windows Host location is
`%LOCALAPPDATA%/iOpenPod/cache/games/version16/files`. Other platforms use their
application cache directory. It retains the original `All iPods` and
`iPod Videos (5G and 5.5G only)` trees. A sibling `ready.json` records the pinned
source and content-index digests. With a matching receipt and game manifests,
later clicks reuse that folder immediately, even without the downloaded 7z.
A complete folder can rebuild a missing receipt after content verification.
An interrupted download retains `.7z.part` and resumes using HTTP Range.
Interrupted extraction never publishes a ready folder. Preparation uses a
cross-process Host file lease and private extraction workspace. The archive is
limited to 30,000 entries and 4 GiB; traversal, aliases, links, special files,
encryption, and duplicate paths are rejected. See [ADR-0211](adr/0211-download-the-game-collection-on-demand.md).

Add resolves compatible catalog identities directly to these Host game folders.
It neither downloads nor extracts again. The installer hashes the selected files,
checks them against the pinned content fingerprint, and validates the manifest
GUID/version before planning device writes. A game may contain at most 20,000
entries and 512 MiB. Links and duplicate or unsafe paths are rejected. Persistent
Host files remain available after installation for other iPods.

The Application Layer publishes all checked games in one create-only, recoverable
Storage Transaction under `iPod_Control/Games_RO`. Storage creates missing parent
directories; explicit game directories also preserve intentionally empty
folders. Installation also ensures `iPod_Control/GameStats_WO` and
`iPod_Control/GameData_RW` exist, preserving their existing contents. A conflicting
file blocks installation rather than being replaced. Existing game identities and occupied destination folders are rejected,
including renamed installations and case variants. Empty directory trees left
after recovery are reusable. Existing games are never replaced by this operation.
Empty directories can remain after interruption; file publication follows normal
transaction recovery. Game-root capitalization is normalized to the catalog
identifier while nested filenames and all file bytes are retained.
Discovery manifests publish after all executable and resource files.

Installation runs off the GUI thread under the existing exclusive device
reservation. Identity metadata and the authorization store are rechecked before
publication. A disconnect or cancellation stops further operations; retained
transactions require normal recovery before another write. Verified completion
refreshes the shared installed-game catalog so installed titles appear in Games
and disappear from Available games. Closing the dialog hides it while an admitted
installation continues; changing the Active iPod cancels the old operation.
Physical installation through this new UI still requires device acceptance;
small Host-folder and 7z fixtures cover batch publication, validation, source changes and UI
selection without depending on firmware images or full game executables.

Host preparation publishes download/extraction byte progress through the shared
status bar. Installation reports preparation, device copying, verification, and
finalization; copying reports the transaction's file count.
Unknown totals use an activity indicator. Queued updates share the removal
workflow's throttling and are cleared on completion, failure, disconnect or shutdown.
Authorization preparation remains silent.

## Uninstalling games

Right-click an installed game and choose **Uninstall** to remove its executable
folder under `iPod_Control/Games_RO`, plus the corresponding folders under
`iPod_Control/GameData_RW` and `iPod_Control/GameStats_WO`. Saved progress and
statistics in those game folders are included. Shared parent directories, sibling
games, iTunesDB, and IC-Info.sidb are preserved. Removal does not require first
pressing Gimme Games or preparing authorizations.

Uninstall first opens a warning naming the game and explaining that its saved
progress and statistics will also be deleted. **Cancel** is the default and Escape
action. Only choosing **Uninstall** begins removal, after checking that the same
Active iPod and catalog item remain current.

The shared status bar shows preparation, file removal, verification, folder cleanup
and finalization. Known stage totals use real file or folder counts; unknown totals
use an activity indicator. Worker reports are queued to the GUI thread and normally
limited to ten updates per second, with stage changes and final counts retained.
The controller clears its status on completion, failure, disconnect or shutdown;
stale queued reports cannot recreate it. Authorization preparation remains silent.

The executable folder uses the actual installed directory name. Runtime data and
statistics use the manifest GUID, falling back to the folder name for unreadable
metadata. Matching is case-insensitive; ambiguous shared identities and unsafe
paths fail before mutation. Missing runtime folders are allowed.

The Application Layer captures every file fingerprint and directory membership
before constructing one recoverable Storage removal transaction. Discovery
manifests are removed first. Changes to the captured files, membership or device
metadata block publication. After verified file removal, Storage removes only
the captured empty directories, deepest first. Unexpected files block that cleanup
and retain transaction recovery material. Completed removal refreshes the shared
catalog, returning the title to Available games. If Phase's companion index was
removed, the coordinator updates its cached absence precondition for later Library
operations. Uninstalling does not edit Playlists.

## Ownership and persistence

`iPodDB.ic_info` consumes bytes and returns a `TransferResult` containing prepared
bytes and added, replaced, and unchanged key counts. Counts describe authorization
records, not games. Its modules separate record structure, envelope protection,
account sessions, device binding, and merging. Runtime code must not load firmware,
invoke Ghidra, or require Unicorn.

The Application Layer owns the source resource in `iOpenPod/assets/games/`,
including the original source GUID and SHA-256 manifest. It verifies this manifest
before preparation. The supplied store has 12 accounts and 199 key records;
198 are supported type-0/1 values and one is a retained type-2 value. These are
properties of this resource, not hardcoded parser requirements.

The coordinator uses the selected connection's identity evidence, not its mount
path or marketing generation, to choose a destination. The supported researched
updater families are 13/20/25 (Video 1.3), 24 (Classic 1.1.2), 33 (Classic 2.0.1),
35 (Classic 2.0.4), 38 (Classic 2.0.5), 26 (Nano 3 1.1.3), 31 (Nano 4 1.0.4), and
34 (Nano 5 1.0.2). Ambiguous or different release evidence is not promoted to a
verified profile.

The workflow reserves the Active iPod, runs outside the GUI thread, and captures
the current file through Storage. Publication carries its expected fingerprint
and metadata dependencies. Storage owns staging, recovery originals, the Operation
Journal, verification, durable commit, and cleanup. A disconnect or identity change
stops the operation; interrupted publication uses existing device recovery.
No-op merges do not replace the file.

## Record and merge contract

The decrypted store begins with twelve zero bytes and one `sean` root. Each
record has a 20-byte big-endian header: total length, four-byte tag, identifier,
immediate-child count, and a retained reserved word. Containers must consume
their complete declared extent. The parser limits bytes and nesting; unknown
tags, payloads, sibling order, and reserved words round-trip exactly.

One `grup/head/guid` must match the supplied device GUID. Accounts are identified
by their `user` record identifier, and keys by the `key\x20` identifier within that
account. Duplicate selectors are rejected as ambiguous input.

Known singleton GUID, account version/session, and key value/type/signature fields
use identifier 1, matching native field lookup. Merely having the correct tag
with another identifier does not make a field usable by the firmware. Raw record
round trips still preserve arbitrary identifiers.

Bundled keys replace conflicts at the same selector. Destination-only accounts
and keys stay, including unknown key kinds that require no transformation.
Distinct selectors with identical values are not collapsed. Shared accounts keep
their destination metadata and RSA-protected AES session. Incoming values are
prepared for that actual session, then merged; their original RSA ciphertext is
not used as a session-equality test. Different account versions currently fail
closed rather than applying an unverified conversion. Signed incoming key records
are outside the supplied empty-signature profile.

Parent sizes and child counts are rebuilt when records are added. Repeated merges
return the existing bytes when all incoming records are already present. A corrupt
or unsupported existing envelope is an error, even when the bundled source works.

Type 2's final device-key semantics remain unresolved. Its native final-key path
rejects the captured record in both a genuine Nano 5 store and the transferred
store. Preserving its session-protected inner bytes does not claim that it has
become a usable final key.

## Phase Playlists

When Phase is installed, the Playlist editor offers **Use as the Phase Playlist**
for ordinary and Smart Playlists. The sidebar retains it in the normal hierarchy
with a gamepad sidebar icon and a prominent Phase wordmark over its hero artwork.
Selecting another Playlist replaces the
previous designation; applying the dialog changes the draft, and the normal
Library review/save publishes it to the iPod.

Saving prepares the Phase Library index and content-checked analysis files using
final persistent IDs, alongside the database changes in one Storage Transaction.
Eligible music lasts 30 through 1800 whole seconds. Duplicate occurrences share
an analysis file, and other tracks remain in the Playlist without generated
charts. Librosa detects musical attacks and locally tracked pulses from the
audio; matching source/version/chart fingerprints allow repeat saves to reuse
charts. Existing untracked charts are upgraded on the first analyzed save. See
[Phase audio analysis](phase-audio-analysis.md). Clearing or deleting the selected Playlist
empties the index without deleting old charts.

Loading follows the game's selection: match the Phase Library's playlist
persistent ID, then fall back to the exact name `Phase`. MHYP value 25 is written
as a producer convention but never used to identify the selected Playlist.
The current writer preserves unfamiliar index data by refusing to overwrite
extended layouts; the selection header can still be read from those indexes. See
[ADR-0209](adr/0209-publish-phase-companions-with-the-library.md) for the marker
convention, boundaries and native-parser verification limits.

## Verification

Game-capable devices require cached RetailOS provenance in addition to core
identity fields before discovery may skip a live hardware probe. Legacy
`visibleBuildID` entries copied from SCSI revisions lack the `retailos_release`
marker and trigger a probe. Selection reconciles the actual `VisibleBuildID`
from the live vendor payload into both SysInfo files and their authority record,
while retaining the transport revision separately. The Classic 6.5 regression
covers legacy `1.62` caches, correction to `2.0.1`, and reuse after reconnecting.

Repository tests use small synthetic records and compact known-answer vectors.
They cover bounds, exact round trips, duplicate selectors, preservation, conflict
replacement, idempotence, authentication failures, session differences, and the
virtual Storage workflow. Full firmware images and Ghidra projects stay in the
separate research lab. Native differential results are recorded there and are not
runtime dependencies or routine full-suite inputs.

The standalone converter passed native checks for all ten listed families:
1,533 final-key comparisons, plus session and wrong-GUID/tamper controls. Video
families verify 49 type-1 keys each; the other seven families verify all 198
supported type-0/1 keys each. Repeating each merge returned identical bytes.

Additional native Classic 6.5 and Nano 5 merge cases deliberately changed an
account's AES session, removed an account and key, introduced a conflicting key,
and added an unrelated key. Both restored 26 incoming records, replaced one
conflict, preserved the unrelated key and destination session, and verified all
199 supported final keys. The type-2 inner bytes remained unchanged when its
session layer was reconciled. Each enlarged store remained byte-identical on the
next merge.

The retained lab scripts are `standalone_app_transfer_audit.py` and
`standalone_app_merge_audit.py`, with receipts in
`artifacts/standalone-app-audit/`. Helper reconstruction notes and scripts live
in that lab's `notes/games/standalone-*.md` and `scripts/standalone_*.py`.
The product includes a 256 KiB first-generator-word table and approximately
57 KiB of cipher/RSA constants; the remaining helpers are reconstructed arithmetic.
The byte mixer was checked against all 65,536 native input pairs and reduced to
ordinary GF(256) multiplication with polynomial 0x11B.

No new physical iPod write or game-launch acceptance test was performed. These
offline native checks establish the file/key compatibility of the inspected
builds, not physical acceptance of the new GUI publication workflow.
