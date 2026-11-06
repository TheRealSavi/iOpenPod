# Datetime engineering guide

This is the code-navigation and interpretation guide for dates in iOpenPod.
[ADR-0243](adr/0243-use-whenever-for-calendar-interpretation.md) records the
Whenever migration. [The time contract](ipod-time.md) specifies native conversion;
the [Classic file map](research/classic-datetime-file-map-2026-11-06.md) and
[auxiliary inventory](research/auxiliary-datetime-file-inventory-2026-11-06.md)
identify bytes, tables, evidence and remaining unknowns. Those inventories are
not a claim that every firmware file or date consumer has been decoded.

## Separate the quantities before using a date

| Quantity | Representation | Interpretation |
| --- | --- | --- |
| Native iPod calendar word | Retained integer/bytes | A format-specific coordinate, often seconds from 1904; not automatically a UTC instant. |
| Semantic Library date | Signed integer Unix seconds | Best-effort instant. Zero is the existing unset sentinel; negative dates are valid. |
| UTC moment | Whenever `Instant` | For current Host time, authenticated validity and explicit-offset input. |
| Civil calendar coordinate | `PlainDateTime` or `Date` | Components that require a stated zone/offset policy before becoming an instant. |
| Historical zone rules | IANA key in Device Time Context | Host estimate of historical offsets for the selected city, not device history. |
| Captured effective offset | `TimeDelta`, whole seconds | Already includes the represented effective shift; do not add saved DST again. |
| Elapsed duration | Integers or `TimeDelta`; monotonic clock for measurement | Playback positions, timeouts and processing time are not civil dates. |
| Filesystem observation | Integer nanoseconds from Storage | Preserve for source identity and verification; do not round-trip through displayed dates. |

`Instant.timestamp()` floors to whole seconds. In particular, half a second before
the Unix epoch becomes `-1`, not `0`. The ordinary Mac-calendar
words covered here have whole-second precision; plist date objects can contain
fractions. Host ISO inputs with fractions intentionally follow this flooring rule.

Do not convert all integers into `Instant` eagerly. Unusual words, explicit clears,
an absent sidecar field and a nonzero word that projects to Unix zero carry
different evidence. An unchanged load/save must preserve the original bytes even
when display cannot represent the value or the selected timezone is uncertain.

## Code inventory and policies

Paths below are repository-relative. Individual format field definitions remain
the source of truth for offsets; do not repeat them in parsers or writers.

| Area | Code entry points | Policy and limits |
| --- | --- | --- |
| Native epochs and local conversion | `src/iPodDB/device_time.py` | Mac epoch offset 2,082,844,800; Core Data offset 978,307,200. Invalid values receive bounded interpretations; authoring resolves bounded native words. Neither operation changes retained originals merely because their interpretation is uncertain. |
| Capturing device interpretation | `src/iOpenPod/app/services/device_time.py`, `src/iOpenPod/app/services/classic_calendar.py`, `src/iOpenPod/app/services/ipod_preferences.py` | Qualify firmware identity and capture city/offset/provenance. No Host clock or Host timezone fallback for native dates. |
| Preferences and annual rules | `src/iPodDB/preferences/`, `src/iOpenPod/app/services/ipod_preferences.py` | Optional read-only observations, opaque unknown bytes, no write precondition. See exact entry points in the linked Preferences contract. |
| Library projection and editing | `src/iPodDB/library/_projection.py`, `src/iPodDB/library/_date_resolution.py`, `src/iPodDB/library/_track_writing.py`, `src/iPodDB/library/_photo_projection.py`, `src/iPodDB/library/_photo_writing.py` | Keep raw/semantic distinctions and bound new unrepresentable dates before validation. Missing layout fields retain previous values. |
| Playback sidecars | `src/iPodDB/sidecars/`, `src/iPodDB/library/_sidecar_projection.py` | Apply counter deltas independently of dates. Present binary zero clears; missing date fields do not clear. Preserve raw dates through merge and verification. |
| Smart Playlist dates | `src/iPodDB/library/smart_rules.py`, `src/iOpenPod/app/smart_playlist_preview.py`, `src/iOpenPod/GUI/dialogs/playlist_editor.py` | Absolute native bounds use local calendar conversion. Host relative preview retains rolling durations; firmware uses inclusive calendar-day bounds. |
| SQLite generation | `src/iPodDB/library/sqlite.py`, `src/iPodDB/SQLiteDB/` | Supported UTC Core Data columns derive from resolved semantic dates, with zero retained as missing. Do not apply another device-local shift. |
| MHOD type 55 plist date objects | `src/iPodDB/iTunesDB/parser/mhod_parsers/plist_mhod.py`, `src/iPodDB/iTunesDB/writer/mhod_encoder.py`, `src/iPodDB/iTunesDB/shared/chunk_defs/mhod_payloads/plist_mhod.py` | Typed date objects are UTC `Instant`; Python 3.12 plistlib uses naive UTC datetime at the adapter only. Authored values floor to microseconds before entering the model. Integer date keys in playback plists remain native integers. |
| Metadata input and display | `src/iOpenPod/app/core/dates.py`, `src/iOpenPod/app/metadata_fields.py`, `src/iOpenPod/app/models/track_columns.py`, `src/iOpenPod/GUI/widgets/photo_inspector.py` | User-entered unqualified date/time uses the Host zone; explicit offsets win. Unrepresentable displayed values fall back without blocking Library work. |
| Imported media tags | `src/iOpenPod/app/media/tags.py`, `src/iOpenPod/app/media/importing.py`, `src/iOpenPod/app/track_playback_policy.py` | Unqualified release-date tags use UTC. Supported year/month inputs expand to their first day. Missing/malformed dates do not discard media. |
| Podcasts | `src/iOpenPod/app/podcasts/feed_client.py`, `src/iOpenPod/app/podcasts/documents.py`, `src/iOpenPod/app/podcasts/media.py`, `src/iOpenPod/app/podcasts/catalog.py`, `src/iOpenPod/app/podcasts/sync.py`, `src/iOpenPod/app/podcasts/controller.py` | Feedparser's parsed tuple is UTC. Preserve signed Unix dates; malformed optional persisted dates become missing. Refresh and change times come from `Instant.now()`. |
| Scrobbling | `src/iOpenPod/app/scrobbling/queue.py`, `src/iOpenPod/app/scrobbling/timestamps.py`, `src/iOpenPod/app/scrobbling/service.py` | Preserve captured Unix-date evidence. Host midnight/service age limits are delivery policy; inability to deliver a date must not block Sync or lose counts. |
| Sync records and fingerprints | `src/iOpenPod/app/sync_execution.py`, `src/iOpenPod/app/library_sync_helper.py` | UTC ISO strings retain `+00:00` and six fractional digits. Deliberately authored FAT mtime uses two-second resolution; observed filesystem times remain Storage facts. |
| New Playlist and Genius dates | `src/iOpenPod/app/services/library_resources.py`, `src/iOpenPod/app/services/genius_mixes.py` | Capture a Host Unix instant and pass it through the normal semantic/native writer policy. |
| Backups and registry | `src/iOpenPod/app/backups/repository.py`, `src/iOpenPod/app/backups/models.py`, `src/device_registry/authority.py` | UTC persisted strings and snapshot identity format stay stable. Legacy backup label parsing is best effort; identity/verification requirements remain enforced. |
| Signed releases | `src/iOpenPod/app/updates/releases.py`, `scripts/update_feed.py` | Require UTC input and enforce issuance, expiry, skew and lifetime. No Library metadata fallback at this security boundary. |
| Screenshot fixtures | `scripts/capture_website_screenshots.py` | Deterministic Whenever-generated date strings for display fixtures; not device clock evidence. |
| OS media integration | `src/iOpenPod/app/playback/system_media/windows.py` | Whenever duration converts to stdlib timedelta solely for the WinRT ABI. These are elapsed positions, not dates. |

`SYSTEM_TZ` belongs in Host display/input and Host-day delivery policies only.
It must not leak into device conversion.

Whenever caches the Host zone. `src/iOpenPod/app/app.py` refreshes that cache at
startup and application activation. Unqualified editor input and background
Last.fm day allocation also refresh at their calendar boundaries, rather than
in every table cell. If refresh fails, valid unqualified editor input estimates
UTC and Last.fm defers delivery; a stale cached zone must not silently determine
a newly authored date. Display may retain its previous projection. Captured
Device Time Context keys and offsets remain independent of these Host refreshes.

Genius Mix expiry and Podcast retention are elapsed-duration policies: a day is
86,400 seconds and Podcast month choices are 30/60/90 days. These integer
comparisons do not promise calendar-anniversary or DST-aware local-day semantics.

## Native date policy

Given a fixed offset in seconds east of UTC:

```text
Unix = native_Mac - 2_082_844_800 - effective_offset
native_Mac = Unix + 2_082_844_800 + effective_offset
Core_Data = Unix - 978_307_200
```

Each format still owns its missing-value and preservation rules. The formulas
alone do not distinguish unset zero from an event exactly at an epoch.
For a u32 Mac word, the maximum civil coordinate is 2040-02-06 06:28:15;
the corresponding UTC instant depends on the selected interpretation. Values
outside the native range are bounded when authoring rather than wrapping. The
native format's range is independent of Whenever's wider calendar range.

For IANA keys, resolve the offset at the represented date. During a repeated local
hour, prefer the occurrence matching the captured database offset, otherwise the
earlier occurrence. During a missing local hour, use the pre-transition offset,
which moves the estimate forward through the gap. This applies to non-hour
transitions too. An invalid/missing key uses a valid captured fixed offset or an
explicit UTC estimate. Neither today's offset nor the Host's current location
can repair missing device history.

Date problems are nonblocking for Library load, edit, save and Sync. A diagnostic
can explain an estimate. Raw preservation, counter application and valid fields
continue independently. File integrity, device identity, transaction recovery,
explicit editor syntax validation and signed-update authentication retain their
own checks; they are not uncertain device calendar interpretation.

## What the latest Classic firmware establishes

Only these latest targets are in scope: Classic 6 / family 24 / 1.1.2, Classic
6.5 / family 33 / 2.0.1, Classic 7 / family 35 / 2.0.4 and Classic 7.5 / family
38 / 2.0.5. Older revisions must not inherit these qualifications implicitly.

- All four have an adjusted Firmware Calendar distinct from the Raw Hardware
  Clock. Saved day/seconds corrections are software bias, not a geographical
  timezone. New played/skipped words already include the adjusted calendar;
  adding saved bias or DST would apply the adjustment twice.
- Qualified Preferences retain raw DST at file `0xB6C`, full u32 city at `0xB70`,
  signed days at `0xB78`, and seconds at `0xB7C`. Framing/extent differs by target.
  A matching byte offset alone is insufficient qualification.
- Host `WRITE BUFFER` imports civil fields, an effective signed quarter-hour
  offset and a DST byte. It changes software correction. `READ BUFFER` exports
  the adjusted calendar; it cannot measure raw RTC basis.
- The queued Host-clock handler copies correction, reconciles city, normalizes
  saved DST to zero/one and marks Preferences dirty. Receipt, queued handling and
  persistence are separate events. The separate zone-change observer persists
  the raw live DST byte, normally zero or 60; do not universalize zero/one as the
  saved field's only encoding.
- Classic 6 city matching compares base offset. The later targets additionally
  compare the current-date DST predicate. City can therefore be an automatic
  match rather than the user's chosen location. No match can produce city zero;
  `0x26` also has unresolved geographical evidence. Both use explained fallback.
- The traced deferred MediaItem observer refreshes protected-media timing state.
  It does not directly rewrite ordinary Track dates. Smart evaluation samples
  and reuses day bounds during that evaluation; do not infer a global date rebase.
- The later three targets have qualified annual DST-file consumers. Their 205
  rows use recurrence selectors, not historical IANA rules. 2.0.1 has no prefix;
  2.0.4/2.0.5 have a two-byte prefix whose meaning remains unknown. Last-week
  selection and date arithmetic differ, so decoding requires the right profile.

These claims link to instruction-level evidence in the [time contract](ipod-time.md)
and [per-target support matrix](classic-calendar-support.md). The evidence includes
static traces, reconstructed arithmetic and bounded native ARM emulation with
mocked services. It does not establish execution on all four physical devices.

## Hints and open questions to preserve

| Target/area | Known hint | Still unresolved; do not infer |
| --- | --- | --- |
| All four raw RTCs | Calendar-shaped BCD register reads and year origin 2000; alarm write route is separately identified. Loader/updater/Disk paths were inspected beyond OSOS. | UTC/local basis at initialization, manufacturing/BootROM contribution and the effect of the unexplained register `0x58` write. The shared-RAM fallback date 2000-01-04 is not proof of an RTC seed. |
| All four notifications | Concrete Host queued handler and MediaItem observer dataflow are traced. | Every indirect recipient/callee, all ordering and physical persistence timing. No justified rebasing of existing ordinary dates. |
| Classic 6 / 1.1.2 | Saved-clock fields and base-offset city matching are qualified; inspected clock poll lacks the later automatic DST route. | A qualified consumer/layout for the optional DST file. Opaque preservation does not mean the firmware never uses it. |
| Classic 6.5 / 2.0.1 | Prefix-free annual rows, selector four means last; specific earlier weekday/February arithmetic behavior is traced. | Actual past city/manual-clock changes; geographical identity of the disputed city. Annual rows cannot reconstruct history. |
| Classic 7 / 2.0.4 | Two-byte prefix, selector four means fourth and five means last, later arithmetic corrections. | Meaning of the prefix, why it exists, and whether its semantics differ from 2.0.5. |
| Classic 7.5 / 2.0.5 | Same qualified row shape as 2.0.4, independently checked consumer and saved fields. | Prefix semantics and raw-clock initialization; matching structure is not evidence for all untraced behavior. |
| Photo/Artwork MHII dates | Fields `+0x28`/`+0x2C` retained; a Classic 2.0.1 importer copies one field. | Full epoch/use proof on every target and complete EXIF relationship. Current local-Mac projection is Host policy. Older Original iOpenPod unsigned-Unix output notes are historical producer evidence, not this contract. |
| Release/purchase dates | Existing UTC-Mac policy and paired capture/reference evidence. | The same all-four firmware proof level as ordinary added/modified/played/skipped fields. |
| Playlist/MHIP timestamp names | Retained fields and a 2.0.1 route that fills an empty Track added date. | Every creation/modification meaning and consumer on all four targets. Names alone do not establish semantics. |
| Smart relative periods | Firmware uses inclusive calendar-day comparison; Host currently uses rolling durations. | A deliberate future compatibility decision and migration, especially after backward clock changes. |
| Other files | Full SQLite Library set is a later nano capability; a Classic 2.0.1 Extras.itdb capture exists. | Calendar meaning of unnamed payload bytes, rental fields, iTunesPrefs tails, or similarly named `Device/PlayCounts`. |

New evidence should update the relevant format definition, fixture and research
report, then this guide if interpretation changes. Preserve contradictory or
partial observations with their target, artifact/hash, offsets and confidence;
do not upgrade a field name, source analogy or one capture into firmware proof.

## Host formats, precision and packaging

`parse_iso_instant` accepts ISO date-only, local date/time and explicit-offset
forms. It requires a policy for missing timezone information. Whenever 0.11 does
not accept every form accepted by Python's permissive `datetime.fromisoformat`
(for example ISO week-date input or arbitrary separators). Invalid editor input
uses normal validation; optional media parsing uses its existing missing-date
fallback. Native device input does not pass through this text parser.
Valid unqualified text with unavailable Host timezone rules estimates UTC;
explicit offsets remain authoritative. `HostDateZone.SYSTEM` is a typed adapter
for Whenever's `SYSTEM_TZ` sentinel, whose use as a type is not yet supported by
the repository's Mypy version.

Host JSON output keeps UTC `+00:00`, not a bracketed IANA annotation. Sync
records use six fractional digits. Backup, registry and signed-feed timestamps
retain the previous convention of omitting the fraction when it is zero and
otherwise using six digits. Snapshot IDs keep
`YYYYMMDDTHHMMSS.ffffffZ-sequence`. Plistlib exposes at most microseconds through
its Python 3.12 datetime API; the typed model floors newly authored `Instant`
values to that precision before serialization. Binary plist floating-point dates
have their own representation limits. Existing source bytes and binary plist
payloads stay retained when unchanged.

The runtime dependency is bounded to Whenever 0.11 and locked in `uv.lock`.
`tzdata` remains explicit; Windows also resolves the Host zone via `tzlocal`.
IANA rules come from the available timezone data, not the captured device. A
Device Time Context retains its key/offset/provenance against Preferences changes
but does not snapshot a tzdb version. Frozen builds require
`packaging/hooks/hook-whenever.py` because Whenever's public API uses lazy imports.
The hook includes submodules, metadata and tzdata resources and applies to both
the main app and the independent update helper.

Development stubs are separate from these runtime packaging hooks. Run
`uv run python -m scripts.prepare_typing` after environment setup to provide
Pylance and Mypy with the compatible Whenever 0.11.0 `SYSTEM_TZ` declaration.
The [typing notes](../typings/README.md#whenever-timezone-annotations) explain the
version gate, upstream mismatch and preservation of strict call-site checks.

Keep `time.monotonic`, `monotonic_ns`, `perf_counter` and `sleep` where measuring
elapsed work. Replacing them with UTC instants would introduce clock-change bugs.
Source `stat` timestamps stay integer nanoseconds; FAT two-second resolution is
a Storage concern, independent of Mac-epoch database words and DST disambiguation.

## Validation map

| Regression area | Starting tests |
| --- | --- |
| Native conversion and retained words | `tests/iPodDB/iTunesDB/test_device_time.py`, `tests/iPodDB/library/test_device_time_context.py` |
| Selection, sidecars and DST | `tests/iOpenPod/app/services/test_device_time_integration.py`, `tests/iOpenPod/app/services/test_playback_dst.py` |
| Plist precision and source preservation | `tests/iPodDB/iTunesDB/test_remaining_mhod_parsers.py` |
| Host editor, table and media input | `tests/iOpenPod/app/test_datetime_presentation.py`, `tests/iOpenPod/app/test_host_metadata_tags.py` |
| Podcast and Photo dates | `tests/iOpenPod/app/podcasts/test_feed_client.py`, `tests/iOpenPod/GUI/test_photo_page.py` |
| Host midnight and delivery | `tests/iOpenPod/app/test_scrobbling_timestamps.py` |
| Wire strings and strict update clocks | `tests/iOpenPod/app/backups/test_repository.py`, `tests/iOpenPod/app/test_release_metadata.py`, `tests/test_update_publication.py` |

- Device conversion: ordinary historical dates, folds, gaps, half-hour transitions,
  skipped days, invalid zones/offsets and native integer boundaries.
- Preservation: exact unchanged bytes, zero/absence collisions, backward dates,
  sidecar counters independent of dates, edited bounded values and plist precision.
- Host input/display: signed pre-1970 dates on Windows, explicit offsets,
  fractional seconds, missing dates and unsupported display ranges.
- Host persistence/security: UTC spelling, microsecond precision, snapshot naming,
  strict release timezone/issuance/expiry and unchanged rollback checks.
- Distribution: a frozen Whenever smoke program exercises IANA/Host zones,
  metadata and the extension path. Full CI remains responsible for other OS builds.

Run focused tests with `-W error::whenever.WheneverDeprecationWarning` and
`-W error::whenever.PotentialDstBugWarning`, then the repository's normal checks.
Historical capture comparisons are evidence with their original scope; do not
describe them as rerun on a new implementation without actually doing so.
