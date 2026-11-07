# Native Genius capabilities

Device Registry describes the native firmware features separately from whether
iOpenPod can prepare, publish, or preserve their data. This contract covers stock
firmware on the catalog's filesystem-accessible iPods. iPod touch, iPod shuffle,
Rockbox, and firmware cross-flashing are outside this policy.

## Device matrix

| Device | Native Genius Playlists | Native Genius Mixes |
| --- | --- | --- |
| Full-size iPod 1G–5.5G, both Minis | Unsupported | Unsupported |
| Classic 6G, original 2007 80/160 GB | Unsupported | Unsupported |
| Classic 6.5G, 2008 120 GB | Supported | Unsupported |
| Classic 7G, later thin 160 GB | Supported | Supported from RetailOS 2.0.3; unknown until version evidence resolves the requirement |
| nano 1G–3G | Unsupported | Unsupported |
| nano 4G | Supported | Unsupported |
| nano 5G–7G | Supported | Supported |

Native Genius Playlists are generated on the iPod from a selected Track. Native
Genius Mixes expose a firmware Mix container and use Genius relationships to build
playback. An ordinary Host-generated Playlist can still play on older devices;
that does not enable either native feature. The support states do not describe
Apple account access or the availability of Apple's Genius service.

## Registry API

`DeviceProfile.capabilities.genius` contains `playlists`, `mixes`, and an optional
numeric `mixes_minimum_firmware`. Both feature fields use `FeatureSupport`:

- `SUPPORTED`: the model and any required firmware evidence permit the feature.
- `UNSUPPORTED`: stock firmware on the model lacks it, or the observed release is
  below the required version.
- `UNKNOWN`: required release evidence is missing, malformed, or contradictory.

`DeviceRegistry.identify(evidence)` refines only an exact profile. For Classic 7G,
it compares the highest-authority RetailOS observations numerically against 2.0.3.
It normalizes two-component releases with a zero patch component. Disagreement
at the highest authority stays unknown, even if every disputed value is above
the threshold. A malformed current observation cannot fall back to a cached one.
The catalog object remains unchanged, and later identification uses fresh evidence.

For example, after exact identification:

```python
from device_registry import FeatureSupport

native_mix_supported = profile.capabilities.genius.mixes is FeatureSupport.SUPPORTED
```

Use explicit enum comparisons. Testing an enum's truthiness is not a capability
check. A plain model lookup describes the catalog baseline; Classic 7G Mix support
remains unknown until identification receives usable release evidence. Recovery
connections and ambiguous identities still do not provide an exact Device Profile.

`firmware_versions` now means the user-visible RetailOS release. Parsers use only
`VisibleBuildID`/`visibleBuildID`; `BuildID` and `BuildVersion` are internal builds.
`transport_revisions` retains `FireWireVersion`, `scsi_revision`, and generic SCSI
probe revisions with their original authority. These revisions never satisfy a
Genius firmware requirement. Reconciliation keeps the release and transport keys
separate. Historical incorrectly labeled cache values cannot be reliably repaired
without fresh evidence; current hardware versions outrank those cached values.

Reconciliation caches the observed release as `visibleBuildID` in SysInfo and
`VisibleBuildID` in SysInfoExtended, with its value and provenance in SysInfo
Authority. For a profile with a firmware requirement, discovery reuses this cache
only when both file hashes match, the release has recorded hardware provenance
marked `value_kind: retailos_release`, and both files contain the same release.
That marker is set by a current release observation, not by copying a legacy cache;
rewriting an old transport revision cannot certify it as firmware. Missing or
inconsistent firmware entries trigger a read-only hardware probe; selection saves
the result through the existing
verified metadata-reconciliation workflow. A complete cache is reused across
connections without another probe. It remains Device Metadata and cannot detect a
firmware replacement that leaves all three cache files unchanged. Other profiles
continue caching the release when available without requiring it for identity.

`SupportsGenius` or `SupportsGeniusMixes` keys are not required activation flags in
this contract. The tested nano 7G's hardware payload omitted both. Database
presence, SQLite support, and sparse capability metadata do not replace the model
and release policy.

## Evidence and limits

- Original iOpenPod was inspected at
  [v1.68.1's capability module][original]. It has no Genius capability fields.
  The existing model catalog remains the hardware baseline; these feature facts
  extend it using Apple documentation and the local investigation.
- Apple's [nano 4G announcement][nano4] describes native song-based Genius
  Playlist creation. The [nano 5G announcement][nano5] introduces Genius Mixes,
  and the [nano 6G announcement][nano6] also identifies Mix support.
- The [120 GB Classic guide][classic120] documents Genius Playlists. Apple's
  [2.0.3 release-notes archive][classic203], `en/Readme.rtf`, introduces Mixes for
  the Fall 2009 160 GB Classic. The earlier Classic's 2.0.1 hardware probe and
  firmware analysis corroborate the distinction in the [research notes][research].
- The [nano 7G guide][nano7] documents native Genius features. Our local nano 7G
  1.0.4 experiment confirmed that an authored Mix appears and begins playback.
  Our Classic 6.5G 2.0.1 experiment confirmed native Playlist generation, playback,
  and saving. These are the only locally verified physical cases here.
- Upstream [cross-generation research][crossgen] reports native Mix playback on
  nanos 5G/6G. Classic 7G and nano 4G authoring remain untested locally. Native
  support is broader than the current iOpenPod authoring validation.

See [ADR-0175](adr/0175-model-native-genius-capabilities-by-firmware.md) for the
registry contract. The application now uses these capabilities to generate basic
Genius data during Sync, as described in
[ADR-0178](adr/0178-generate-basic-genius-during-sync.md). The registry itself
neither generates relationships nor writes device files. Native collection
editing and saved Playlist import remain separate work.

[original]: https://github.com/TheRealSavi/iOpenPod/blob/de300074a25f6f327b54a7141720e5fbff9d5c5b/src/iopenpod/device/capabilities.py
[nano4]: https://www.apple.com/newsroom/2008/09/09Apple-Introduces-New-iPod-nano/
[nano5]: https://www.apple.com/newsroom/2009/09/09Apple-Introduces-New-iPod-nano-With-Built-in-Video-Camera/
[nano6]: https://www.apple.com/ca/newsroom/2010/09/01Apple-Reinvents-iPod-nano-With-Multi-Touch-Interface/
[classic120]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[classic203]: https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-7155.20090925.Ju879/iPodDocumentation_35.2.0.3.ipd
[nano7]: https://cdsassets.apple.com/live/6GJYWVAV/user/locale/en-gb/ma1624_ipod_nano_2015_user_guide.pdf
[research]: research/genius-generation-2026-10-24.md
[crossgen]: https://github.com/dotm5/Genius-Mix-Research/blob/57b7ae865a10177f725c90e946e1199c00411e53/docs/CROSSGEN.md
