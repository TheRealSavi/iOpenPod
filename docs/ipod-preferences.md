# iPod preferences readers and writers

`iPodDB.preferences` models three distinct binary artifacts:

| Artifact | Reader / writer | Document |
| --- | --- | --- |
| `iPod_Control/Device/Preferences` | `parse_preferences` / `write_preferences` | `PreferencesDocument` |
| `iPod_Control/iTunes/iTunesPrefs` | `parse_itunes_preferences` / `write_itunes_preferences` | `ITunesPreferencesDocument` |
| `iPod_Control/Device/dst` | `parse_dst_table` / captured bytes only | `DSTTableDocument` |

All accept bytes and expose immutable observations. The two preferences writers
serialize edits over retained source; DST rules have no edit writer.
Storage owns file access and publication. There is no dependency
on Device Registry, automatic sync-policy change, or clock adjustment here.

## Firmware Preferences

The document retains `source_bytes`, `layout`, `settings`, `profile`, and optional
`extended_settings`. Exact known extents select the base structure:

| Layout | Bytes | Settings type | Fields |
| --- | --- | --- | --- |
| `FOURTH_GENERATION` | 2,892 | `FourthGenerationPreferences` | `timezone_code`, `language_code` |
| `VIDEO` | 2,924 | `VideoPreferences` | `timezone_code`, `language_code` |
| `CITY` | 2,952, 2,956, 2,960 | `CityPreferences` | `city_id`, `language_code` |
| `UNKNOWN` | Other nonempty extents, or explicitly selected | `None` | Opaque |

Language remains a native byte code: the sources do not establish a universal
model-specific locale catalog. The writer accepts byte values without claiming
that every firmware offers every language. English is documented as zero.

Model-specific fields require an explicit `PreferencesProfile` assertion from the
caller, based on its device/firmware evidence:

| Profile | Additional structure | Edit values | Extent constraint |
| --- | --- | --- | --- |
| `STANDARD` (default) | None | None | Any known base layout |
| `NANO_3` | `Nano3Preferences.daylight_saving_minutes` | 0 or 60 | 2,952 bytes |
| `VOLUME_LIMIT_1_1_1` | `VolumeLimitPreferences.volume_limit` | 0 through 64, device units | Known base layout containing the field |
| `CLASSIC_6_1_1_2` | `ClassicPreferences` and `ClassicClockPreferences` | Language; city/clock fields read-only | 2,952 bytes, version word `0x3c` |
| `CLASSIC_120GB_2_0_1` | `Classic201Preferences` and `ClassicClockPreferences` | Language and Alternate Audio (0/1); city/clock fields read-only | 2,956 bytes, version word `0x3d` |
| `CLASSIC_UPDATER_35_2_0_4` | `ClassicPreferences` and `ClassicClockPreferences` | Language; city/clock fields read-only | 2,956 bytes, version word `0x3e` |
| `CLASSIC_UPDATER_38_2_0_5` | `ClassicPreferences` and `ClassicClockPreferences` | Language; city/clock fields read-only | 2,960 bytes, version word `0x3f` |

The volume profile asserts the documented Video/nano firmware 1.1.1 behavior;
file size alone does not make that assertion. Zero is not assigned an invented
"disabled" meaning. Unknown layouts cannot enable these extensions. The nano 3
DST switch is exposed separately; it is not automatically added to a city's
historical UTC offset.

Each qualified latest Classic profile replaces the generic two-byte city view with a full u32 at
payload `0xb70`. A value such as `0x00010029` remains unknown rather than aliasing
city `0x29`. Its separate clock structure exposes `format_version`, raw
`retained_dst_state` at `0xb6c`, signed `clock_bias_days` at `0xb78`, and the raw
u32 `clock_bias_seconds` word at `0xb7c`. Saved DST has mixed 0/1 and 0/60 callers;
neither it nor the bias is added to IANA date conversion. City/clock edits are
rejected, while language changes preserve those bytes exactly.

Queued Host clock handling can refresh the saved correction, choose a matching
city, normalize Saved DST State to 0/1, and mark Preferences dirty. The separate
zone-change path can save raw DST minutes, normally 0/60. The file can lag live
processing and later persistence; its city need not reflect a manual choice.
When no city matches, firmware can select zero. Qualified Classic city zero
therefore includes an explanatory diagnostic and remains geographically
unresolved. See [the notification trace](research/classic-clock-notification-effects-2026-11-05.md).

`Classic201Preferences.alternate_audio` retains the raw u8 at payload `0xb85`:
zero is Off and one is On. Unknown values `2..255` round-trip unchanged, including
during language edits; explicit Alternate Audio edits accept only 0 or 1 and
preserve every unrelated byte. It is a global firmware preference, separate from
Host Media Stream Selection, an audio stream index, or a language identifier.
The setting's connection to the movie reader's requested audio language remains
unresolved. See the [Alternate Audio evidence](research/ipod-preferences.md#qualified-classic-alternate-audio).

The Application Layer qualifies the four latest Classic Calendar Targets using
the strongest available RetailOS and updater-family evidence, consistent with
the selected Device Profile. Families 35/38 require an explicit updater family;
the known Classic 6/6.5 models also allow model-plus-exact-release qualification
when updater identity is absent. Equal-authority conflicts do not qualify, and
transport revisions do not qualify. Unexpected framing on a qualified target
remains opaque rather than falling back to a two-byte city interpretation.
The Settings view shows captured clock observations on all four targets and
Alternate Audio on the qualified 2.0.1 profile. It offers no firmware preference
editing. See [ADR-0242](adr/0242-qualify-the-latest-classic-calendar-targets.md) and the
[firmware evidence](research/classic201-clock-semantics-2026-10-26.md).

`document.timezone` returns:

- `FixedOffsetTimezone(offset_seconds)`: seconds east of UTC for older encodings,
  including their encoded DST adjustment.
- `CityTimezone(city_id, timezone_name, detail="")`: city identity, known zone
  name and any interpretation diagnostic through the public Preferences contract.
  Unknown cities, including zero, retain `timezone_name=None`.
- `None`: an opaque layout or invalid older code.

Qualified Classic city `0x26` also returns no geographical zone on all four latest
releases: the inherited London mapping contradicts each firmware's base offset
and its intended city identity is unresolved. Unqualified profiles retain their
existing interpretation.
Four corroborated city mappings are corrected in the shared table; see
[the city identity evidence](research/classic201-additional-contracts-2026-10-26.md#city-identity-corrections).

The reader never consults the Host timezone or substitutes UTC for an unknown
reading. The Application Layer resolves city rules into a Device Time Context for
best-effort Library date conversion. Preferences are captured evidence, not a
Library save dependency (ADR-0240). See
[the time contract](ipod-time.md).

```python
from dataclasses import replace

from iPodDB.preferences import CityPreferences, parse_preferences, write_preferences

document = parse_preferences(preferences_bytes)  # Bytes already read through Storage.
assert write_preferences(document) == preferences_bytes
if isinstance(document.settings, CityPreferences):
    desired = replace(document, settings=replace(document.settings, city_id=0x69))
    candidate_bytes = write_preferences(desired)
```

`layout=PreferencesLayout.CITY` asserts an expected layout and rejects a mismatched
extent. `layout=PreferencesLayout.UNKNOWN` explicitly suppresses interpretation
for an unverified model, even if its extent matches. Layout names are format
families, not inferred Device Profiles.

## Saved Firmware DST Rules

`parse_dst_table(data, profile=...)` captures optional annual rules without
rejecting incomplete or unusual date metadata. The caller must qualify a profile:

| Profile | Prefix bytes | Complete rows | Nominal week selectors |
| --- | ---: | ---: | --- |
| `UNKNOWN` (default) | Opaque whole file | None decoded | None interpreted |
| `CLASSIC_120GB_2_0_1` | 0 | 205 × 16 bytes | 1, 2, 3, last=4 |
| `CLASSIC_UPDATER_35_2_0_4` | 2, meaning unknown | 205 × 16 bytes | 1, 2, 3, 4, last=5 |
| `CLASSIC_UPDATER_38_2_0_5` | 2, meaning unknown | 205 × 16 bytes | 1, 2, 3, 4, last=5 |

`DSTRule` retains the unsigned city ID, raw enabled byte, two weekdays, two
month/week pairs and three unused bytes. Every nonzero enabled byte means enabled;
Sunday is weekday zero. `start` and `end` expose `DSTTransition` observations.
Their `week_occurrence(profile)` returns a nominal `DSTWeek`, while
`supported(profile)` describes the recognized selector domain. Neither calculates
an instant or claims that firmware arithmetic equals the nominal calendar rule.

`DSTTableDocument.rules` preserves order. `rules_for_city(id)` returns every
matching row without narrowing the supplied ID. Duplicate rows cannot be reduced
to one effective rule: firmware enabled and active predicates scan differently.
City zero is not a terminator. `issues` records incomplete files, trailing data,
duplicate cities and unusual enabled transitions; these are not workflow errors.
`complete` means all 205 rows were captured, not that every rule is understood.

The document retains `source_bytes`, `prefix_bytes` and `unparsed_bytes`.
Short files expose only complete rows; partial rows are never padded or replaced
with compiled defaults. `serialize()` reproduces the original bytes. Unknown
profiles retain the entire file opaquely even when its length resembles a known
format. The source is never modified and there is no table edit writer.

The later loaders copy the prefix into two retained bytes and request a fixed
3,280 bytes of rows separately. No numeric interpretation or byte order is
established for the prefix. Bounded execution of the original 2.0.4/2.0.5 loader
and enabled lookup under Unicorn, with mocked file services, gives the same row
extent and lookup results for six distinct prefixes. A subsequent missing-file
load can retain the previous prefix while selecting compiled rows. Therefore the
prefix is neither a validated version/count nor evidence that saved rules are
currently active. See the [prefix follow-up](research/classic-dst-prefix-consumers-2026-11-05.md)
for the execution boundaries and untraced consumers.

Automatic application qualification covers families 33/35/38 at their respective
latest releases, independently of Preferences readability. Family 24 / 1.1.2
retains a present `dst` file opaquely: its inspected clock routes use retained/manual
DST and do not establish the later annual-file consumer.
Equal Nano tables do not establish their consumers' complete contract.
These annual selectors do not reconstruct historical timezone changes or prove
the currently active firmware buffer. They do not change Library date conversion.
See [ADR-0241](adr/0241-inspect-firmware-dst-rules-as-optional-evidence.md) and
[the pinned firmware evidence](research/firmware-dst-data-and-city-identity-2026-11-06.md).

## Binary iTunesPrefs

`ITunesPreferencesDocument.settings` is an `ITunesPreferences` structure covering
the documented settings from the iPodLinux format table:

| Fields | Representation |
| --- | --- |
| Setup completed, open iTunes on attach, disk use, checked tracks only | Native flags; `PreferenceToggle` for edits |
| Music and podcast sync modes | Native codes; `SyncMode.MANUAL` / `AUTOMATIC` |
| Music and podcast sync selections | Native codes; `SyncSelection.ALL` / `SELECTED` |
| Show artwork, sync photos, include original photos | Native flags; `PreferenceToggle` |
| Transcode to 128 kbps AAC, keep in source list, Sound Check | Native flags; `PreferenceToggle`; historically described for Shuffle |
| Library link and secondary library link | Two independent eight-byte identifiers |
| Shuffle music/file capacity values | Retained raw words; observation-only because units are unresolved |

The reader validates the `frpd` marker and requires the documented 236-byte
prefix. Longer files retain their full extent, including unknown header bytes and
tails. The supplied nano 5, nano 7, and connected-device files are all 1,232 bytes.
Unknown flag codes remain integers; they are never coerced to a misleading bool.
The enum types provide named values without discarding those unknown codes.

`profile=ITunesPreferencesProfile.SHUFFLE` additionally reads
`document.voice_over` as `ShuffleVoiceOverPreferences` when byte 249 exists.
Shorter historical files return `None`, distinct from disabled. The observed
VoiceOver interpretation is nonzero = enabled; new edits use 0/1. Standard-profile
files preserve that byte opaquely.

```python
from dataclasses import replace

from iPodDB.preferences import (
    PreferenceToggle,
    SyncMode,
    parse_itunes_preferences,
    write_itunes_preferences,
)

document = parse_itunes_preferences(itunes_prefs_bytes)
desired = replace(
    document,
    settings=replace(
        document.settings,
        music_sync_mode=SyncMode.MANUAL,
        open_itunes_on_attach=PreferenceToggle.DISABLED,
    ),
)
candidate_bytes = write_itunes_preferences(desired)
assert parse_itunes_preferences(candidate_bytes).settings == desired.settings
```

This example prepares bytes only. The codec does not change sync policy by itself.
It never creates a library identifier, copies one stored identifier over another,
or constructs default settings for a missing file. iTunesPrefs describes which
selection mode applies; this prefix does not establish the selected playlist or
track lists themselves.

## Preservation, validation, and limits

Offsets, binary encodings, and widths live in `BinaryStruct` definitions consumed
by the shared reader/writer. Unchanged documents reproduce every original byte.
Edits retain all other bytes, including unknown or invalid existing settings.
Validation applies independently to edited fields: an unknown timezone does not
prevent a language edit, and an unknown sync flag does not prevent another edit.
Mutable input buffers are copied.

Writers reject wrong types, out-of-range values, newly introduced unrecognized
flag/timezone codes, absent extension fields, and mismatched structures with
`iPodDBWriteError`. They preserve original extents and never initialize a new file.
Empty firmware Preferences, truncated iTunesPrefs prefixes, and bad iTunesPrefs
markers raise `iPodDBParseError`. Unknown firmware lengths remain opaque.

This covers the documented binary fields, not a complete reverse engineering of
every firmware setting. Unknown bytes remain represented by `source_bytes`.
The `iTunesPrefs.plist` companion, `iPodSettings.xml`, and alleged sync-history
records in the binary tail do not yet have substantiated typed contracts here.
The complete firmware schema and any dependent-file/checksum requirements remain
unresolved. Physical editing needs a separate Storage-backed workflow and verified
device acceptance. See the [format evidence](research/ipod-preferences.md).

## Validation

### Read-only Settings tab

Settings → iPod Preferences displays the Active iPod's Device settings and iTunes
settings, plus saved daylight saving rules when a `dst` file is present.
Selection reads these files through its existing read-only Filesystem
Session on the device worker, with a 1 MiB per-file limit and fingerprint checks.
The Application Layer publishes immutable display summaries; GUI widgets receive
no source bytes, filesystem handles, or writer operations. Values are selectable
plain text, including unknown codes and library identifiers.

The snapshot is captured when the iPod is loaded and replaced when it is reloaded
or another iPod becomes active. Clearing the Active iPod clears the display.
Missing, unreadable, and unsupported files have separate display states and do
not hide the other file's settings or fail an otherwise valid Library load.
Disconnects still abort selection. Model-specific interpretation uses the selected
Device Profile and available firmware evidence, never file length alone.

### Codec checks

`tests/iPodDB/test_preferences.py`, `test_itunes_preferences.py` and
`test_dst_preferences.py` use authored
fixtures with nonzero unknown bytes. They cover the native fields, enum edits,
timezone encodings, profiles, truncation, unknown values, library-link preservation,
and exact output outside the edited ranges.
Qualified Classic checks cover every retained Alternate Audio byte, explicit 0/1
edits, invalid new values, and continued city/clock protection. Application and GUI
checks cover profile qualification and selectable, read-only Alternate Audio text.
Latest-target fixtures cover all four extent/version pairs, full city IDs, raw
saved clock words, authority precedence, unresolved cities and exact byte
preservation. Virtual devices commit fold/gap playback history and save Libraries
on all four targets despite missing, unusual or later-changing clock evidence.

Read-only checks also exercise both codecs against the three supplied device
contexts. Captures are not committed or required by tests; candidate edits are
verified entirely in memory and the original files remain unchanged.

The DST reader was additionally compared with all 615 built-in rows extracted
from the three SHA-256-pinned Classic images in the format research. Every field,
unused byte and enabled count matched the independent extraction receipt: 108
enabled rows in 2.0.1 and 106 in each later image. That check uses synthetic file
framing around retained built-in rows; it is not a captured custom DST file or
physical acceptance test. Firmware binaries are not shipped or required by tests.
