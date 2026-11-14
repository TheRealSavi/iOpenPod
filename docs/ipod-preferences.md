# iPod preferences readers and writers

`iPodDB.preferences` models the following distinct native artifacts:

| Artifact | Reader / writer | Document |
| --- | --- | --- |
| `iPod_Control/Device/Preferences` | `parse_preferences` / `write_preferences` | `PreferencesDocument` |
| `iPod_Control/Device/iPodSettings.xml` | `parse_named_preferences` / `write_named_preferences` | `NamedPreferencesDocument` |
| `iPod_Control/Device/iPodSettings` (Nano 4) | `inspect_named_preferences` / no edits | `PreferenceInspection` |
| `iPod_Control/iTunes/iTunesPrefs` | `parse_itunes_preferences` / `write_itunes_preferences` | `ITunesPreferencesDocument` |
| `iPod_Control/Device/dst` | `parse_dst_table` / captured bytes only | `DSTTableDocument` |

All accept bytes and expose immutable observations. The preferences writers
serialize qualified edits over retained source; the additional Nano stores and
DST rules have no application edit writer.
Storage owns file access and publication. There is no dependency
on Device Registry, automatic sync-policy change, or clock adjustment here.

The application currently exposes inspection only. The implemented Apply/Revert
workflow described below is gated by `ENABLE_IPOD_PREFERENCES_WRITES`, which is
false in `iOpenPod/app/developer_flags.py`. Extras navigation is independently
gated by `ENABLE_EXTRAS_PAGES`, also false. Tests of these workflows explicitly
enable their flag; ordinary application tests retain the defaults. These
development switches do not qualify firmware or replace source validation.

The [whole-file firmware inventory](research/preferences-complete-inventory-2026-11-07.md)
records the deeper per-model investigation, including menu domains, defaults,
consumers and unresolved byte ranges. It distinguishes research knowledge from
the smaller, explicitly qualified editing contract documented here.

## Source ownership

Application consumers use the public `iPodDB.preferences` interface. Internally,
format definitions, retained documents, observation and editing have distinct
owners:

| Responsibility | Source |
| --- | --- |
| Binary layouts, exact framing and binary/named profile identifiers | `preferences/definitions.py` |
| Retained binary and named documents and timezone observations | `preferences/models.py` |
| Native authoring locations, domains, masks and coupled encodings | `preferences/native_definitions.py` |
| Binary parsing/serialization and explicit native edits | `preferences/codec.py`, `preferences/native.py` |
| Bounded named XML framing, byte spans and decimal interpretation | `preferences/_named_xml.py` |
| Named scalar edits over retained bytes | `preferences/named.py` |
| Read-only field catalogs and saved-field observations | `preferences/_binary_inspection_data.py`, `preferences/_named_catalog.py`, `preferences/binary_inspection.py`, `preferences/named_inspection.py`, `preferences/inspection_models.py` |
| Qualified saved city evidence, independent of display rows or editors | `preferences/clock_evidence.py` |

Named inspection, editing and clock evidence share XML framing, but each retains
its own field eligibility rules. A readable field does not become editable.
Self-closing elements have no replaceable text span. Inspection can interpret
decoded XML character references while editing retains their original spelling
until an explicit replacement. Unknown bytes and unrelated clock state survive
every supported edit.

Device Registry's `firmware.py` owns the shared model/release/updater matching
rules. Its `FirmwareTarget` describes identity evidence, not edit permission.
Preferences, Extras and Classic clock capture use that qualification with their
own explicit capabilities. The Application Layer composes qualified targets with
codec profiles and Storage; it does not duplicate binary sizes or version words.
`matches_preferences_profile` recognizes framing only, allowing callers to
withhold an unsafe legacy interpretation without inferring device identity.
Alarm codecs consume the same Preferences framing and alarm-word definition.

These are implementations of ADR-0097, ADR-0247 and ADR-0248, not broader firmware
support or new write authority. Research remains evidence in `docs/research/`;
its inventories are not runtime permission lists.

## Firmware Preferences

The document retains `source_bytes`, `layout`, `settings`, `profile`, and optional
`extended_settings`. Exact known extents select the base structure:

| Layout | Bytes | Settings type | Fields |
| --- | --- | --- | --- |
| `FOURTH_GENERATION` | 2,892 | `FourthGenerationPreferences` | `timezone_code`, `language_code` |
| `VIDEO` | 2,924 | `VideoPreferences` | `timezone_code`, `language_code` |
| `CITY` | 2,952, 2,956, 2,960 | `CityPreferences` | `city_id`, `language_code` |
| `UNKNOWN` | Other nonempty extents, or explicitly selected | `None` | Opaque |

Explicit firmware profiles can additionally select `FIRMWARE`, a qualified
frame whose clock layout is not inferred. `FirmwareLanguagePreferences` observes
the full u32 language word and does not expose a timezone. This is different
from an unknown frame: verified scalar fields can still be edited. Its language
word remains observation-only until a complete resource-dependent writer is
qualified.

The `VideoPreferences.timezone_code` name is retained for API compatibility.
Native execution on Video updater families 13/20/25, release 1.3, establishes
that file `0xB22` is an unsigned alarm word: its low 12 bits store minutes of day
and its high four bits survive alarm edits. It does **not** identify a timezone.
For exact 2,924-byte/version-word `0x39` framing, `document.has_video13_framing`
is true and `document.timezone` returns `None`, even without device identity.
The legacy field remains signed in the raw API; unchanged bytes and language
edits remain lossless, while new purported timezone edits are rejected.
Settings displays an unknown timezone and Library dates use the nonblocking
database-offset/UTC fallback. This format observation does not authorize alarm
editing or infer another firmware's clock fields. See the
[Mini/Video audit](research/mini-video-datetime-support-audit-2026-11-06.md).

The separate Extras workflow qualifies Mini 2 / 1.4.1 alarm-minute edits using
the connected Device Profile and firmware evidence. Its `iPodDB.alarms` codec
patches only the low 12 bits in exact framing; it never changes timezone, enable
state or sound. The raw codec also retains the Video 1.3 field representation,
but the application presents it as a **read-only Clock Alarm Projection**:
current Video firmware loads per-city alarms from `iPod_Control/Device/clock`
and copies the earliest alarm into Preferences. Editing this projected word does
not edit a persistent selected alarm. See the
[Video investigation](research/preferences-video-complete-2026-11-07.md).
Library Preferences capture remains read-only. See
[ADR-0247](adr/0247-manage-extras-through-qualified-lossless-file-edits.md).

The older generic layouts retain their historical language-byte API. Qualified
latest Mini, Video and Classic profiles now expose the native **u32** language
word at `0xAF8`; a nonzero upper byte must not alias English. English is zero.
The whole-file inventory now records sparse catalogs for Mini 1/2 and Nano 1/3/4;
Nano 4 adds UK English at code 1 and shifts later codes compared with Nano 3.
Language-change dependencies and resource adoption remain under investigation.
The Settings editor retains language as an observation, not a raw-code editor.
See the [latest firmware write model](#qualified-firmware-preference-editing).

Model-specific fields require an explicit `PreferencesProfile` assertion from the
caller, based on its device/firmware evidence:

| Profile | Additional structure | Edit values | Extent constraint |
| --- | --- | --- | --- |
| `STANDARD` (default) | None | None | Any known base layout |
| `NANO_3` | `Nano3Preferences.daylight_saving_minutes` | 0 or 60 | 2,952 bytes |
| `VOLUME_LIMIT_1_1_1` | `VolumeLimitPreferences.volume_limit` | 0 through 64, device units | Known base layout containing the field |
| `MINI_1_1_4_1` | `Mini1Preferences` | Qualified native fields below; clock/language observation-only in the editor | 2,876 bytes, version word `0x16` |
| `MINI_2_1_4_1` | `Mini2Preferences` | Qualified native fields below; clock/language observation-only in the editor | 2,876 bytes, version word `0x16` |
| `NANO_1_1_3_1` | `FirmwareLanguagePreferences` | Qualified native fields below; no clock inference | 2,916 bytes, version word `0x37` |
| `NANO_3_1_1_3` | `FirmwareLanguagePreferences` | Qualified native fields below; no clock inference | 2,952 bytes, version word `0x3c` |
| `NANO_4_1_0_4` | `FirmwareLanguagePreferences` | Qualified native fields below; no clock inference | 2,960 bytes, version word `0x3e` |
| `VIDEO_1_3` | `Video13Preferences` | Qualified native fields below; clock/language observation-only in the editor | 2,924 bytes, version word `0x39` |
| `CLASSIC_6_1_1_2` | `ClassicPreferences` and `ClassicClockPreferences` | Qualified native settings below; city/clock fields read-only | 2,952 bytes, version word `0x3c` |
| `CLASSIC_120GB_2_0_1` | `Classic201Preferences` and `ClassicClockPreferences` | Qualified native settings below, including Alternate Audio (0/1); city/clock fields read-only | 2,956 bytes, version word `0x3d` |
| `CLASSIC_UPDATER_35_2_0_4` | `ClassicPreferences` and `ClassicClockPreferences` | Qualified native settings below; city/clock fields read-only | 2,956 bytes, version word `0x3e` |
| `CLASSIC_UPDATER_38_2_0_5` | `ClassicPreferences` and `ClassicClockPreferences` | Qualified native settings below; city/clock fields read-only | 2,960 bytes, version word `0x3f` |

The volume profile asserts the documented Video/nano firmware 1.1.1 behavior;
file size alone does not make that assertion. Zero is not assigned an invented
"disabled" meaning. Unknown layouts cannot enable these extensions. The nano 3
DST switch is exposed separately; it is not automatically added to a city's
historical UTC offset.

The qualified Nano 3 / 1.1.3 profile does not inherit the historical `NANO_3`
extension or its `0x6BC` DST interpretation. The new Nano 1/3/4 profiles expose
verified saved scalar fields and a u32 language observation, while retaining
unqualified clock bytes without interpreting them. Nano 4/5/6/7 cannot acquire
a Classic city interpretation merely from equal file length. The separate
Nano 5/6/7 named-settings contract is described below.

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
offers independently qualified Alternate Audio edits on all four. Editing uses the separate
native-field contract below. See [ADR-0242](adr/0242-qualify-the-latest-classic-calendar-targets.md) and the
[firmware evidence](research/classic201-clock-semantics-2026-10-26.md).

`document.timezone` returns:

- `FixedOffsetTimezone(offset_seconds)`: seconds east of UTC for older encodings,
  including their encoded DST adjustment.
- `CityTimezone(city_id, timezone_name, detail="")`: city identity, known zone
  name and any interpretation diagnostic through the public Preferences contract.
  Unknown cities, including zero, retain `timezone_name=None`.
- `None`: an opaque layout, invalid older code, or the qualified Video alarm-word
  exclusion described above.

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
from iPodDB.preferences import (
    PreferenceKey,
    PreferencesProfile,
    parse_preferences,
    update_preferences,
    write_preferences,
)

# The Application Layer has independently qualified the connected firmware.
document = parse_preferences(
    preferences_bytes, profile=PreferencesProfile.CLASSIC_120GB_2_0_1
)
assert write_preferences(document) == preferences_bytes
desired = update_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
candidate_bytes = write_preferences(desired)  # Publication still belongs to Storage.
```

`layout=PreferencesLayout.CITY` asserts an expected layout and rejects a mismatched
extent. `layout=PreferencesLayout.UNKNOWN` explicitly suppresses interpretation
for an unverified model, even if its extent matches. Layout names are format
families, not inferred Device Profiles.

## Saved-field inspection

Inspection describes more saved state than the editor can safely change.
`inspect_binary_preferences(document)` returns a `PreferenceInspection` containing
immutable `PreferenceObservation` rows and nonblocking issues. Each row separates
its key, label, raw value, interpretation, category and evidence limits. Exact
profile, version and extent are required; a generic size-based layout does not
select another model's catalog. A reset-request file remains readable with a
warning that firmware can discard its saved values, while editing stays disabled.

The binary catalog includes named playback, display, language, contact, photo,
radio, menu, clock and internal fields where independently established for that
profile. It retains important model differences: Video's second volume word is
balance; Mini's corresponding word remains only partly understood. Early photo
durations are selectors, while Nano 3/4 and Classic use signed seconds. Nano 4's
transition IDs differ from Nano 3 and Classic. Numeric EQ IDs are separate from
older counted UTF-16 preset names, and a decoded name does not by itself prove a
compiled preset match. A stored menu bit describes a visibility request, not
current hardware or library availability.

Unknown enumerations, malformed strings, residual flag bits and incomplete clock
interpretations retain their raw values. Unmapped byte ranges appear in one
bounded **Unknown Data** summary; partly understood named fields carry their own
limits. No unidentified bytes are called padding. These observations describe
the captured source, before pending edits, and never grant write authority.

`inspect_named_preferences(data, profile=...)` provides the corresponding
profile-specific view of named Nano settings. It recognizes registered types and
the separately established value labels, while preserving unknown keys, strings
and invalid values. Registration bounds, raw setter acceptance and offered UI
choices remain distinct. The inspection catalog is not a claim that every field's
consumer or every possible value is understood.

## Qualified firmware preference editing

`available_preferences(document)` describes the native fields supported by an
explicit latest-firmware profile and exact framing. `preference_value(document,
key)` returns the retained native value, and `update_preferences(document,
changes)` validates explicit choices before `write_preferences` overlays them.
The original `source_bytes` remain the comparison baseline. Unknown scalar
values and bytes survive unrelated edits. Malformed compound Shuffle state stays
unresolved; no default is silently selected. A nonzero reset-request word at
file `0x04` withholds editing instead of clearing a native reset request.
`document.reset_requested` exposes that observation as `True`/`False` for exact
qualified frames and `None` for generic, opaque or mismatched sources.

In the matrix, **binary core** means Shuffle, Repeat and Sound Check. **Photo
controls** means slideshow Repeat, Shuffle, Time Per Slide and Transitions.
Every row also has the read-only observations qualified for that exact target.

| Latest target | Primary store / exact binary frame | Editable fields beyond binary core, or named-store fields |
| --- | --- | --- |
| Mini 1 / 1.4.1, updaters 3/6 | `Preferences`, 2,876 bytes / `0x16` | Clicker, Backlight Timer, Audiobook Speed, Contact Sort and Display |
| Mini 2 / 1.4.1, updater 7 | `Preferences`, 2,876 bytes / `0x16` | Clicker, Backlight Timer, Audiobook Speed, Contact Sort and Display |
| Nano 1 / 1.3.1, updaters 14/17 | `Preferences`, 2,916 bytes / `0x37` | Clicker, Backlight Timer, Audiobook Speed, Contact Sort and Display, Nike Spoken Feedback and Remote Commands |
| Nano 3 / 1.1.3, updater 26 | `Preferences`, 2,952 bytes / `0x3C` | EQ, Brightness, Clicker, Backlight Timer, Contact Sort, Photo controls, TV Out, TV Signal, TV Screen, Fit to Screen, Alternate Audio |
| Nano 4 / 1.0.4, updater 31 | `Preferences`, 2,960 bytes / `0x3E`; extensionless `iPodSettings` read-only | EQ, Brightness, Clicker, Backlight Timer, Contact Sort, Photo controls, TV Out, TV Signal, TV Screen, Fit to Screen, Alternate Audio |
| Nano 5 / 1.0.2, updater 34 | `iPodSettings.xml` | Brightness, Sound Check, EQ |
| Nano 6 / 1.2, updater 36 | `iPodSettings.xml` | Brightness, Sound Check, EQ |
| Nano 7 / 1.0.4, updater 37 | `iPodSettings.xml` | Brightness, Sound Check, EQ |
| Nano 7 refresh / 1.1.2, updater 39 | `iPodSettings.xml` | Brightness, Sound Check, EQ |
| Video 5 / 1.3, updaters 13/20 | `Preferences`, 2,924 bytes / `0x39` | Clicker, Backlight Timer, Audiobook Speed, Contact Sort and Display, slideshow Repeat and Shuffle, Widescreen, Voice Memo Quality |
| Video 5.5 / 1.3, updater 25 | `Preferences`, 2,924 bytes / `0x39` | Clicker, Backlight Timer, Audiobook Speed, Contact Sort and Display, slideshow Repeat and Shuffle, Widescreen, Voice Memo Quality |
| Classic 6 / 1.1.2, updater 24 | `Preferences`, 2,952 bytes / `0x3C` | EQ, Brightness, Clicker, Backlight Timer, Alternate Audio, Photo controls |
| Classic 6.5 / 2.0.1, updater 33 | `Preferences`, 2,956 bytes / `0x3D` | EQ, Brightness, Clicker, Backlight Timer, Alternate Audio, Photo controls |
| Classic 7 / 2.0.4, updater 35 | `Preferences`, 2,956 bytes / `0x3E` | EQ, Brightness, Clicker, Backlight Timer, Alternate Audio, Photo controls |
| Classic 7.5 / 2.0.5, updater 38 | `Preferences`, 2,960 bytes / `0x3F` | EQ, Brightness, Clicker, Backlight Timer, Alternate Audio, Photo controls |

Shuffle updates its enable and Albums bytes together. Repeat's **saved** values
are 0 Off, 1 All and 2 One, distinct from some runtime/UI enum orders. Clicker
preserves the upper 30 bits of its word: Classic exposes its verified native
Off/On menu domain, while Mini/Video retain their separate routing choices.
Those route codes are **not interchangeable**: Mini 1/2 and Nano 1 use 1 Speaker / 2 Headphones,
whereas all three studied Video images use 2 Speaker / 1 Headphones. Their native
English resource-labelled callbacks independently establish the reversal.
Numeric EQ uses preset IDs 0 and 100 through 121; zero means global EQ Off,
not the Track metadata choice “Use iPod setting”. Brightness uses the verified
0 through 100 slider domain. Backlight selectors are model-specific; the latent
15-second label on newer binary targets is readable but is not an offered edit.
Audiobook Speed uses signed values -1 Slower, 0 Normal and 1 Faster. Photo
Transitions update their mode/effect pair together, with the target's own Random
sentinel; malformed retained pairs are not silently normalized. Inverted values
such as Fit to Screen and Nike Remote Commands keep their native polarity.

Language, clocks, volume/lock state, menu masks, cache flags, slideshow music
identities, Captions and Subtitles remain read-only in this editor. Their known
values and effects can be inspected without treating partial research or wider
native setter acceptance as permission to write. Captions and Subtitles, for
example, have coupled live-notification behavior beyond two independent bytes.

Settings > iPod Preferences uses explicit Apply/Revert. It checks the connected
model, exact firmware, current identity metadata and captured source fingerprint,
then publishes through a recoverable Storage Transaction. Opening the tab never
writes; missing files are not created, and iTunesPrefs remains read-only here.
Unknown datetime metadata does not block an unrelated verified setting or a
Library workflow.

**Saved bytes and live settings are different states.** Native Mini/Video probes
show that a later dirty save from an existing Preferences owner can overwrite a
Host file edit. Explicit native loading adopts the edited bytes; USB eject and
reload ordering has not yet been fully established or physically accepted. The
UI reports file publication and asks the user to check settings on the iPod after
ejecting, without claiming immediate application or a guaranteed restart recipe.
See [ADR-0248](adr/0248-edit-qualified-firmware-preferences.md), the
[Classic evidence](research/preferences-classic-writes-2026-11-07.md) and
[Mini/Video evidence](research/preferences-mini-video-writes-2026-11-07.md).

Mini 1 and Nano 1 are independently qualified by
[250 native cases across their four updater inputs](research/preferences-mini1-nano1-2026-11-07.md).
Mini 1's read-only u32 selector at `0xB10` independently matches Mini 2's paired
standard/DST choices: selectors 1 through 50 represent effective fixed offsets
from -12 to +13 hours. They do not establish a geographic zone or historical
rules. Out-of-range words remain unknown. Nano 1's date and Alarm offsets are
not inferred from either Mini or Video; they remain untouched by scalar edits.

Nano 3 and Nano 4 independently bind their Clicker routes to 0 Off, 1 Speaker,
2 Headphones and 3 Both, preserving the upper 30 bits. Their later photo and
video work establishes the additional controls in the matrix, including Nano 4's
distinct transition catalog. Classic's expanded controls are independently
qualified on all four images. See the [Nano 3/4 consumer evidence](research/preferences-nano34-effects-2026-11-07.md),
[Classic structure evidence](research/preferences-classic-structures-2026-11-07.md),
and [Video consumer evidence](research/preferences-video-deep-followup-2026-11-07.md).

## Named settings

The newer Nano 4 investigation also finds named settings in the distinct path
`iPod_Control/Device/iPodSettings`, without the `.xml` suffix. Energy Saver,
Crossfade, Font Size, Shake, Voice Feedback and Preview Panel are among the
recovered registrations. `NamedPreferencesProfile.NANO_4_1_0_4` exposes these as
read-only observations alongside the binary editor. They are not inherited from
a Nano 5/6/7 profile or assigned guessed binary Preferences offsets. See the
[Nano 3/4 consumer supplement](research/preferences-nano34-consumers-2026-11-07.md).

Nano 5 is a click-wheel device whose studied UI uses the same kind of named
settings store used by the touch-screen Nano 6/7. Each exact target has its own
`NamedPreferencesProfile`: `NANO_5_1_0_2`, `NANO_6_1_2`, `NANO_7_1_0_4` and
`NANO_UPDATER_39_1_1_2`. Their independent native constructors, setters and
serializers qualify root `iPodSettings`, attribute `version="1.0"`, and these
three scalar paths:

| Section / element | Native type | Editable values |
| --- | --- | --- |
| `General/Brightness` | Integer | 0 through 100 |
| `Playback/SoundCheck` | Boolean | Numeric 0 or 1 |
| `Playback/EQ` | Integer | 0 Off; preset IDs 100 through 121 |

`parse_named_preferences` retains immutable source bytes and issues.
`available_named_preferences` describes safe scalar spans,
`named_preference_value` observes the raw numeric value or `None`, and
`update_named_preferences` validates explicit intent before
`write_named_preferences` replaces the selected scalar text. These functions
do not create an absent file or node. Unknown enum strings, clock fields,
comments and unrelated formatting remain exact. Unsupported XML, DTD/entity
declarations or encoding remain read-only without raising a datetime error.
Duplicate or complex known settings withhold that setting while other
unambiguous fields remain usable.

The native boolean parser does not skip leading whitespace, unlike the integer
loader. An edited Sound Check value therefore replaces its complete scalar text
with canonical `0` or `1`; a no-op preserves original spelling. Integer edits
preserve surrounding whitespace. Ambiguous or nonnumeric retained values are
not silently defaulted. The Application Layer offers only values it can project
without guessing.

Read-only named inspection additionally exposes the independently registered
playback, display, accessibility, language, radio, photo, fitness and clock state
for each firmware, with raw values and partial meanings. Unknown keys remain
visible. A valid city index refers to that firmware's own catalog, not an IANA
index; it does not establish the device's current location or historical offset.
Unusual firmware city bindings remain documented rather than silently corrected.

Nano 6's separate `iPodTimerSettings.xml` is not captured or inspected. Timer
fields within `iPodSettings.xml` remain uninterpreted Unknown Data and survive
unrelated edits byte-for-byte. Dedicated timer observations, duration/action
editors and codecs have been removed by user direction; see
[ADR-0267](adr/0267-remove-nano-countdown-timer-support.md).

The XML source fingerprint governs both changed and no-op publication. The
neighboring legacy binary Preferences blob is optional evidence and is
not a precondition for editing XML. Its familiar extent/version does not qualify
Classic offsets, a reset flag, or live-setting authority. Library date conversion
uses its ordinary nonblocking estimate instead of borrowing Classic city fields.
For these exact Nano 5/6/7 profiles, `inspect_named_binary_preferences` recognizes
the independently observed 2,960-byte / `0x3E` frame, shows its version and partial
saved-volume word, and retains the rest as unresolved data. The volume word has
no qualified percentage interpretation and does not represent the named Volume
Limit. A missing or unqualified binary blob does not hide usable XML settings.
See the [Nano 5 evidence](research/preferences-nano345-2026-11-07.md) and
[Nano 6/7 evidence](research/preferences-nano67-2026-11-07.md).

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
The `iTunesPrefs.plist` companion and alleged sync-history records in the binary
tail do not yet have substantiated typed contracts here. Named settings beyond
the explicitly qualified paths above remain observations or research findings,
not additional application editing contracts.
The full firmware schema, remaining dependent-state interactions and live adoption
remain unresolved. The qualified editor supplies the separate Storage-backed
publication workflow; verified saved bytes do not establish physical firmware
acceptance. See the [format evidence](research/ipod-preferences.md).

## Validation

### Settings inspection and editing

Settings → iPod Preferences displays the Active iPod's Device settings and iTunes
settings, plus saved daylight saving rules when a `dst` file is present. The
expanded view groups observations by category and searches labels, interpreted
values, raw values, details and keys. Filtering changes visibility only; it does
not alter drafts or edit qualification. Read-only values use selectable text;
stored raw values are available in tooltips. Qualified controls retain the same
observation context and require explicit Apply/Revert.
Selection reads these files through its existing read-only Filesystem
Session on the device worker, with a 1 MiB per-file limit and fingerprint checks.
The Application Layer publishes immutable display summaries; GUI widgets receive
no source bytes, filesystem handles, or writer operations. Values are selectable
plain text, including unknown codes and library identifiers.

The initial snapshot is captured when the iPod is loaded. The editor separately
refreshes its source and optional stores; switching or clearing the Active iPod
clears the previous device's values and drafts.
Missing, unreadable, and unsupported files have separate display states and do
not hide the other file's settings or fail an otherwise valid Library load.
Disconnects still abort selection. Model-specific interpretation uses the selected
Device Profile and available firmware evidence, never file length alone.

### Codec checks

`tests/iPodDB/test_preferences.py`, `test_itunes_preferences.py` and
`test_dst_preferences.py` use authored
fixtures with nonzero unknown bytes. They cover the native fields, enum edits,
timezone encodings, profiles, truncation, unknown values, library-link preservation,
and exact output outside the edited ranges. `test_binary_preference_inspection.py`
and the named inspection checks cover exact-profile qualification, differing
model catalogs, signed values, malformed retained data and nonblocking clock
observations. Native/named editor tests separately verify the write allowlists,
compound encodings and full-source preservation.
Qualified Classic checks cover every retained Alternate Audio byte, explicit 0/1
edits, invalid new values, and continued city/clock protection. Application and GUI
checks cover profile qualification, observation/editor merging and source-bound
publication. GUI checks cover grouped searchable rows and retained edit drafts.
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
