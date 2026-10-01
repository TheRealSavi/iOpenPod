# iPod preferences readers and writers

`iPodDB.preferences` models two distinct binary artifacts:

| Artifact | Reader / writer | Document |
| --- | --- | --- |
| `iPod_Control/Device/Preferences` | `parse_preferences` / `write_preferences` | `PreferencesDocument` |
| `iPod_Control/iTunes/iTunesPrefs` | `parse_itunes_preferences` / `write_itunes_preferences` | `ITunesPreferencesDocument` |

Both accept bytes, expose immutable typed settings, and serialize edits over the
retained source. Storage owns file access and publication. There is no dependency
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

The volume profile asserts the documented Video/nano firmware 1.1.1 behavior;
file size alone does not make that assertion. Zero is not assigned an invented
"disabled" meaning. Unknown layouts cannot enable these extensions. The nano 3
DST switch is exposed separately; it is not automatically added to a city's
historical UTC offset.

`document.timezone` returns:

- `FixedOffsetTimezone(offset_seconds)`: seconds east of UTC for older encodings,
  including their encoded DST adjustment.
- `CityTimezone(city_id, timezone_name)`: city identity and known zone name.
  Unknown cities, including zero, retain `timezone_name=None`.
- `None`: an opaque layout or invalid older code.

The reader never consults the Host timezone or substitutes UTC for an unknown
reading. The Application Layer now resolves city rules into a Device Time Context for
Library date conversion and captures Preferences as a save dependency. See
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
settings. Selection reads both files through its existing read-only Filesystem
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

`tests/iPodDB/test_preferences.py` and `test_itunes_preferences.py` use authored
fixtures with nonzero unknown bytes. They cover the native fields, enum edits,
timezone encodings, profiles, truncation, unknown values, library-link preservation,
and exact output outside the edited ranges.

Read-only checks also exercise both codecs against the three supplied device
contexts. Captures are not committed or required by tests; candidate edits are
verified entirely in memory and the original files remain unchanged.
