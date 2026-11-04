# HP iPod Mini identification

Research date: 2026-11-04. Scope: HP-branded silver iPod Mini models reported as
unrecognized by iOpenPod 2.0.17. This note distinguishes catalog evidence from
physical-device acceptance; no supplied hardware dump establishes what either
reported device returns to a Host probe.

## Model evidence

| HP model | HP product number | Advertised storage | Finish | Capability baseline |
| --- | --- | --- | --- | --- |
| `MP5001` | `PW753AA` | 4 GB | Silver | iPod Mini 2nd Gen, equivalent Apple variant `M9800` |
| `MP5002` | `PX762AA` | 6 GB | Silver | iPod Mini 2nd Gen, equivalent Apple variant `M9801` |

HP's own support catalog identifies
[MP5001 as a 4 GB Mini](https://support.hp.com/us-en/product/setup-user-guides/apple-ipod-from-hp-digital-music-player-series/model/472295)
and [MP5002 as a 6 GB Mini](https://support.hp.com/ca-en/drivers/apple-ipod-from-hp-digital-music-player-series/model/472294).
Their indexed titles remain available, but direct retrieval of those pages was
intermittently blocked; this investigation did not retrieve their downloadable
manuals or claim additional specifications from them.

The [EMPR HP parts catalog](https://store.emprgroup.com.au/hpc-9017175-6-hp-ipod-mini-silver-mp5001-4gb-music-player-pw753aa.aspx)
directly pairs `MP5001`, `PW753AA`, silver and 4 GB. Office Depot's own retained
[PW753AA#ABA product listing](https://www.officedepot.com/a/products/945736/Apple-iPod-Mini-40GB-From-HP/)
identifies HP as the manufacturer, specifies 4 GB and advertises 18-hour battery
life. The country suffix in that product number is not a different capacity.

Newegg's retained [HP MP5002 listing](https://www.newegg.com/apple-mp5002-mp3-player/p/N82E16855101506)
explicitly names the second generation, silver finish, 6 GB capacity and 18-hour
battery life. Its manufacturer specification link points to HP document
`c00430181`, which could not be retrieved during this investigation. A separate
[parts inventory entry](https://tamayatech.com/partsindex/partP122.htm)
directly pairs `PX762AA` with HP MP5002 and 6 GB. These are vendors' own retained
catalog records, not proof that an individual used unit has its original parts.

The generation assignment is also supported by comparing those specifications
with [Apple's own Mini specifications](https://support.apple.com/en-us/112317):
the first generation was 4 GB with an eight-hour battery specification, whereas
the second generation offered 4 and 6 GB with an eighteen-hour specification.
Apple names `M9800` and `M9801` as the corresponding silver second-generation
variants. Reusing their existing capability profiles is an inference from these
matching product specifications, not an HP firmware capture or an independent
test of every database capability.

Some current listings disagree: the
[AppleDB Mini selection page](https://appledb.dev/device-selection/iPod-mini.html)
places the HP model numbers on an entry labelled PP5020. That entry does not
override the contemporary product specifications above. No new CPU assumption
is needed for the registry change. Manual aggregation sites also misassociate
full-size photo-iPod documentation with MP5001; a title alone is insufficient to
import those capabilities.

## Product serials

The owner's reported serial has ten alphanumeric characters. The
[contemporary iLounge hands-on HP iPod review](https://www.ilounge.com/index.php/reviews/entry/apple-ipod-from-hp-ipodhp-ipod/comment-page-8)
independently describes ten-character HP serials and transcribes an HP casing.
That review concerns the full-size fourth-generation HP iPod, not the Mini.
It supports the existence of the HP serial format but does not establish a Mini
model decoder. Its prose and casing transcription disagree about whether the
first character is a letter or a number, so neither is a sound prefix-validation
rule.

No consulted primary source establishes that the final three or four characters
of an HP serial encode an Apple-style model variant. In particular, the one
reported ending `K4J` is not sufficient evidence to add a serial-suffix mapping.
HP product serials should be preserved as identity evidence without treating a
coincidental ending such as Apple's `S41` or `S42` as an exact model claim.

Serial acceptance and model identification are separate operations. Accepting a
ten-character serial does not, by itself, identify a Mini generation, capacity,
or finish. A known model or product number is still needed for an exact Device
Profile. USB evidence alone must retain its existing bounded candidates.

## Original iOpenPod comparison

The local `v1.68.1` source preserves `MP5001` in
`src/iopenpod/device/lookup.py:extract_model_number`. Its selection guard in
`src/iopenpod/device/info.py:has_exact_model_number` checks only for a nonempty
model string. The inspected model tables contain no `MP5001`, `PW753AA`, or
reported HP serial-ending entry. Success in that release does not demonstrate
that it resolved an HP-specific capability profile.

The pre-change 2.0 normalizer reduced both `MP5001` and `MP5002` to `MP500` and
rewrote `PW753AA` as `MW753`. Its Host-probe adapter also rejected ten-character
product serials. The registry must retain the distinct HP identifiers and their
documented aliases before Apple-specific normalization is applied.

## Acceptance limits

The implementation adds distinct `MP5001` and `MP5002` Device Profiles, normalizes
the two documented HP product numbers (including `#ABA` regional suffixes), and
retains the existing `x`-prefixed SysInfo round trip. HP profiles reuse the
corresponding second-generation Mini capabilities and silver portrait.

The Device Registry now owns product-serial validation shared by hardware-probe
translation and Device Summary. Ten-character serials are retained, but only
eleven- or twelve-character Apple-format serials enter model-suffix lookup or
certify model provenance during SysInfo reconciliation. No new serial suffix or
USB identifier was inferred from these reports.

Regression coverage lives in `tests/device_registry/test_hp_mini.py` and
`tests/iOpenPod/app/services/test_hp_mini_identification.py`. It covers both
metadata formats, HP aliases, capacity distinctions, conflicting model evidence,
serial validation and accidental Apple-suffix collisions, read-only discovery,
selection-time metadata repair, direct SCSI and udev serial observations, and
hardware model evidence without SysInfo. Missing model evidence remains
ambiguous. These are synthetic fixtures, not captured HP probe responses.

The supplied Linux log establishes that the installed version-2 identity rule
ran. The application's diagnostic cannot distinguish an absent serial from one
rejected by its validator. Neither a udev property dump nor the actual SysInfo or
SysInfoExtended bytes was supplied. Synthetic tests can prove known HP model
selection, serial preservation and conservative handling of incomplete evidence;
they cannot prove a particular physical iPod supplies enough model evidence.

The advertised 4 GB or 6 GB identifies the marketed variant. It is not a limit or
measurement of the current Volume, which may contain replacement flash storage.
Battery replacement and former Rockbox installation do not justify inventing a
different Device Profile. Physical acceptance remains a separate check using the
reported devices after the change.
