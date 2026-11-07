# Latest Classic firmware targets and identity evidence

Research date: **2026-11-05, America/Detroit**. This report establishes the four
latest-firmware targets requested for date/time support. Clock and database
behavior require the separate per-image investigations; updater identity alone
does not prove those behaviors.

## The four maintained targets

Apple's current [update catalog][apple-catalog] offers four separate branches.
Each offer was compared with the original retained IPSW's `manifest.plist`;
`UpdaterFamilyID`, `BuildID` and `VisibleBuildID` all match. Family 35 still offers
2.0.4 while family 38 offers 2.0.5. Treating 2.0.5 as an update for every late
Classic would therefore merge distinct update targets without evidence.
[Captured catalog][catalog], [comparison receipt][targets], [verification script][script]

| User's target label | Firmware research target | Latest offered release | Catalog BuildID | Catalog VisibleBuildID |
| --- | --- | --- | ---: | ---: |
| Classic 6 | Updater family 24 | 1.1.2 | 152207360 | 17989632 |
| Classic 6.5 | Updater family 33 | 2.0.1 | 151093248 | 33652736 |
| Classic 7 | Updater family 35 | 2.0.4 | 151289856 | 33849344 |
| Classic 7.5 | Updater family 38 | 2.0.5 | 151355392 | 33914880 |

The generation labels in this table are the **task's naming convention**. The
updater-family/release pairs are directly verified Apple metadata. An Apple
manifest does not contain the terms 6, 6.5, 7 or 7.5, a retail SKU, capacity or
board identity. All four manifests identify the broader `FamilyID` as 11; that
value cannot distinguish these firmware targets. [Comparison receipt][targets]

The catalog was fetched directly from `https://itunes.apple.com/check/version`.
Apple redirected within `itunes.apple.com` to its version endpoint. The saved
response is **6,359,921 bytes**, SHA-256
`5a2938b0aa28808cb738b0871e01d6e084c5f56243d69b0c6c4fabec442586b8`.
Its HTTP Date is 2026-11-06 03:19:54 UTC, which is November 5 in the user's
timezone. The untouched response and acquisition headers are retained locally;
these establish what Apple offered at capture time, not an assertion that an
online catalog can never change. [Acquisition receipt][acquisition]

## Marketed devices and the 7/7.5 distinction

Apple's [model identification page][apple-models] distinguishes the September
2007 Classic with 80/160 GB, September 2008 Classic with 120 GB, and September
2009 thin Classic with 160 GB. All are marked A1238. It does not introduce a
separate Classic 7.5 category. The 2007 entry lists serial suffixes Y5N, YMU,
YMV and YMX; the page supplies no suffix rule separating updater 35 from 38.

The existing Device Registry has this retail identity grouping:

| Registry generation | Model numbers | Capacity | Calendar-target implication |
| --- | --- | --- | --- |
| 6th Gen | MB029, MB147 | 80 GB | Candidate for updater 24; qualify the observed firmware. |
| 6th Gen | MB145, MB150 | 160 GB | Candidate for updater 24; capacity alone cannot distinguish late 160 GB devices. |
| 6.5th Gen | MB562, MB565 | 120 GB | Candidate for updater 33; MB565 has retained hardware metadata corroboration. |
| 7th Gen | MC293, MC297 | 160 GB | Does not by itself choose updater 35 versus 38. |

This is the repository's existing catalog contract, not a new physical SKU
survey. Its 9ZS/9ZU serial aliases choose MC293/MC297, not an updater family.
Do not introduce an invented MC-series SKU or split the registry generation
solely to display the user's 7.5 label. A separate, qualified firmware target
can distinguish the date contracts while preserving the current Device Profile.
[Registry catalog][registry]

The pinned emulator catalog calls updater 35 Classic Rev B and updater 38
Classic Rev C, but its own header attributes model labels to an AppleWiki
transcription. Its measured download hashes corroborate packages; those labels
are not independent Apple proof of hardware mapping. This investigation therefore
does not use them to infer a manufacturing-date, serial-number or board-name
cutoff. [Pinned source and provenance statement][emulator]

## Available identity evidence and qualification

The public `DeviceEvidence` already carries typed updater-family and firmware
identifiers with provenance and authority. Both text SysInfo and plist/vendor
metadata parsing support `UpdaterFamilyID`. The games workflow independently
selects the strongest observations for each field; a calendar qualifier can use
the same authority rule without importing game policy or its blocking errors.
[Evidence model][evidence], [metadata parser][metadata], [authority selection][games]

One retained physical observation demonstrates why these distinctions matter.
The MB565 capture's cached SysInfo and SysInfoExtended report a misleading
`VisibleBuildID` of 1.62. Its separately retained live hardware payload reports
RetailOS 2.0.1, family 11 and updater family 33. The payload is 12,464 bytes,
SHA-256 `b88c70fd701ad47482518016d759980fa75a81fa123f76146fa16829575a1928`.
These fields were re-read through the public parser, without accessing a device
or exposing serials/GUIDs. Do not mistake SCSI/transport revision for RetailOS,
or let weaker stale metadata veto an unambiguous stronger observation.
[Session provenance][capture-note], [retained hardware payload][hardware]

Recommended qualification policy, distinct from the primary observations:

1. Prefer unambiguous strongest updater-family and exact RetailOS evidence,
   consistent with the selected Classic Device Profile. Recognize only the four
   latest pairs in the table for this research scope.
2. Keep `FamilyID=11`, A1238, current storage size and MC293/MC297 separate from
   updater-family identity. None supplies the missing 35/38 distinction alone.
3. If retaining a model-plus-release fallback when updater identity is absent,
   describe that as an application inference. Do not use it to override a
   conflicting explicit updater-family observation.
4. Unknown, older or conflicting evidence means unqualified optional clock
   observations and the existing best-effort Library date policy. It must not
   become a blocking Library issue or an implicit firmware-upgrade operation.

## Identity questions remaining for each target

| Target | Answered here | Remaining identity/qualification questions |
| --- | --- | --- |
| Classic 6 / 24 / 1.1.2 | Current Apple offer matches the retained package. | Obtain a trustworthy retained vendor-identity capture for both 80 GB and thick 160 GB hardware; establish their actual reported updater/release fields and whether any supported variant omits them. |
| Classic 6.5 / 33 / 2.0.1 | Current offer and retained MB565 hardware payload agree on the family/release. | Confirm MB562 and additional physical units report the same identifying fields; characterize missing/stale metadata without treating it as a date failure. |
| Classic 7 / 35 / 2.0.4 | It remains a separate current Apple update branch. | Obtain a physical updater-35 vendor capture tying the branch to its actual retail/board/serial observations; determine whether any stable hardware-only identifier separates it from 38. |
| Classic 7.5 / 38 / 2.0.5 | It remains a separate current Apple update branch. | Obtain the corresponding updater-38 capture; establish the precise hardware/manufacturing boundary and whether MC293/MC297 or serial suffixes are shared, without inferring it from release labels. |

No new physical capture was taken. A search of the existing supplied capture
locations found the family-33 evidence above, but did not establish equivalent
family-24/35/38 physical metadata. Synthetic and emulator SysInfo files must not
be promoted to physical observations. These identity gaps do not prevent explicit
byte-codec support for all four verified firmware images.

## Reproduction and scope

From the firmware lab, rerun the metadata comparison into a fresh receipt:

```powershell
uv run python scripts/check_latest_classic_targets.py --catalog artifacts/latest-classic-catalog-20261105-v1/version.plist --output artifacts/latest-classic-catalog-20261105-v1/targets-next.json
```

The script refuses to replace existing evidence. It reads four original ZIP
manifests, verifies their family/build identities against the catalog, and records
archive, manifest, catalog and script hashes. It executes no downloaded firmware.
Firmware consumers, DST arithmetic and date domains are covered by the separate
Classic 6 and later Classic reports. No application source changed in this
identity investigation.

[apple-catalog]: https://itunes.apple.com/check/version
[apple-models]: https://support.apple.com/en-us/103823
[catalog]: ../../../ipod-firmware-lab/artifacts/latest-classic-catalog-20261105-v1/version.plist
[acquisition]: ../../../ipod-firmware-lab/artifacts/latest-classic-catalog-20261105-v1/receipt.json
[targets]: ../../../ipod-firmware-lab/artifacts/latest-classic-catalog-20261105-v1/targets-v2.json
[script]: ../../../ipod-firmware-lab/scripts/check_latest_classic_targets.py
[registry]: ../../src/device_registry/data/catalog.py
[evidence]: ../../src/device_registry/models.py
[metadata]: ../../src/device_registry/metadata.py
[games]: ../../src/iOpenPod/app/services/games.py
[capture-note]: ../../../ipod-firmware-lab/notes/session-2026-10-26.md
[hardware]: ../../../ipod-firmware-lab/Classic33FW/captures/2026-10-26-disk-identity/hardware-payload-0.bin
[emulator]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/firmware.rs
