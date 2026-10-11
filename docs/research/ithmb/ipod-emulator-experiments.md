# Local iPod emulator experiments

Experiment date: **2026-10-11**. This records the local installation and subsequent
experiments, separately from the earlier
[source-only assessment](ipod-emulator-assessment.md). The baseline, nonzero-offset,
and second-shard runs display the expected 200×200 artwork exactly. A selective
F1029 color control changes the large view to magenta while leaving the small
view unchanged. These are results for **one firmware image and emulated
configuration**, with the qualifications below. The Windows GUI also reaches its
main menu and Music submenu. No physical-device result is claimed, and no
iOpenPod format catalog or file-size cap changed.

## Environment and provenance

| Item | Recorded configuration |
| --- | --- |
| Emulator source | `siggifly/ipod-emulator`, upstream `dev` at [`d39e850ac07baa28abbdd8b00b77b834a757b5e1`][upstream] |
| Separate checkout | `C:\Users\JohnG\Coding\ipod-emulator`, branch `codex/ithmb-lab` |
| Lab artifacts | `C:\Users\JohnG\Coding\ipod-emulator-lab` |
| Rust | Stable 1.99.0, minimal MSVC installation through SHA-256-verified official `rustup-init` |
| Native build tools | Visual Studio 2022 Build Tools: `VC.Tools.x86.x64` and Windows 11 SDK 22621, installed through winget |
| Core build | Release `trace` and `ipod-boot` built with the locked dependency resolution |
| GUI build | Built and launched on Windows after the compatibility patch described below; six targeted tests passed |
| Firmware | `iPod_20.1.3.ipsw`, downloaded from Apple's official distribution |
| NOR | Synthetic: `make-nor --model A146 --seed 5`; no physical NOR dump used |
| Disk | 8 GiB image created with `make-disk`; headless run uses `initialized-5g.img` |

Artifact SHA-256 values recorded for this run:

```text
iPod_20.1.3.ipsw
351b19ec7f3eb6e4089a9598334a1f83aef097d88802826e51737f0420978142

synth-5g.bin
55974b9c91dcaafc69b9ea576160c625ff97a2b6ab2598fae27f8b70490edde3

fixtures/manifest.json
8169785d0582ea6d71df742d331a1366eca321f5f6e7c3b07377cf66cb7ba8dd

images/initialized-5g.img, closed after initialization
b15d7809e8a8292557d66d43c9336bbac76d477b160f9e9459fe82b33a74fe43

images/baseline.img, pristine injected image before its working copy was booted
9a6c96516d65e1b83faaa0b26996fc6f90b9f443c96a4004ba3b54faaf13948e

windows-compatibility.patch
9062cee65f71a10a268bdecc620616fbd7e93fe2c4bbf6aedf49ace86626d75e
```

The emulator checkout is separate from iOpenPod. The recorded Windows patch
changes `tools/ipod-gui/src/control.rs` and `tools/ipod-gui/src/main.rs`; it does not
change the emulation core. The first GUI launch waits while preparing its disk
copy. The local `Start iPod Lab.cmd` launcher pins the GUI clock to 5; the lab's
README records how to start it. GUI startup and headless artwork results are
distinct observations.
Disk images are writable during runs, so the hashes above identify their stated
closed/pristine states, not every later working copy.

## Boot paths and observations

The initial headless run uses **warm entry into RetailOS**, with a synthetic
identity and a supplied handoff block. Its recorded options are:

```text
--boot-osos --osos-from-disk --sysinfo --bcm --pmu --disk-writable
--clock=5 --battery=100 --rtc=2026-10-11T12:00:00
--disk=<initialized-5g.img> --drive
```

The synthetic NOR is supplied separately. This is not a run of Apple's original
NOR bootloader. The upstream synthetic path supplies boot effects in Rust; CLI
warm entry and the GUI's machine-construction path must be recorded as distinct
configurations. In particular, the headless clock value must not be silently
equated with the GUI's adaptive timing. [Synthetic NOR implementation][nor],
[boot-path history][matrix], [clock and bypass ledger][ledger].

| Run/checkpoint | Observed result | Interpretation |
| --- | --- | --- |
| Headless warm run, 10 simulated seconds; 50,000,000 instructions | White screen | Intermediate observation, not an artwork failure. |
| Same run, 70 simulated seconds; 349,656,040 instructions | Language picker with English highlighted | Firmware-produced interactive setup screen reached. |
| Select pressed, then 180 simulated seconds advanced; endpoint 250 simulated seconds and 539,452,430 instructions | Main menu: Music, Photos, Videos, Extras, Settings, Shuffle Songs | Setup advanced to the main menu. No artwork was tested at this checkpoint. |
| End of initialization | Snapshot saved; trace quit normally and image closed | Closed disk hash recorded above. |
| GUI boot | Reaches `Running`; selecting the language opens the main menu, then Return opens Music | Native GUI navigation confirmed; this is separate from the headless fixture run. |
| Baseline artwork fixture | Now Playing displays the synthetic track, then 100×100 and 200×200 corner-pattern images | Positive emulated-display observation with a fresh repeat; detailed sequence below. |
| Offset and second-shard variants | Large captures are byte-identical to baseline | Positive evidence for these exact fixtures; variant-specific fallback remains a limitation without read tracing. |
| Selective F1029 color control | Large view becomes solid magenta; small view unchanged | Establishes that the baseline large view depends on the F1029 payload in this configuration. |

These are sampled **endpoints**, not measurements of when each screen first
appeared. They do not establish a 70-second boot latency or a 180-second response
to Select. Timing notes from other upstream boot paths are not directly applicable
to this warm-entry run.

The three captures were inspected: the first is white, the second shows the
language picker, and the third shows the main menu. Artifacts are relative to the
lab directory above; the snapshot is 12,032,657 bytes.

| Artifact | SHA-256 |
| --- | --- |
| `captures/initial-10s.png` | `1913d232acad44749d799a995de0b6c8d3c74a28528f3052198a21bbb9b1b15d` |
| `captures/initial-70s.png` | `b980a7e392706474837c36d8470da7a5da86a1861efec7e5f653b23722ca9a98` |
| `captures/after-language-250s.png` | `edb5922da46be62ff4a4555452b8b3db5b5ce619a23e1416d2ab45cecd9915bf` |
| `images/initialized-main-menu.snap` | `67a26e7fc6166a966f9546292bf210567fb19d59a7afedc8d481b0e70e1d702f` |

## Baseline artwork run

The baseline image was copied to `images/baseline-trace.img` and booted with the
same CLI options above, changing the disk path. These checkpoints are again
sampled endpoints, not onset measurements:

| Action/checkpoint | Simulated-time endpoint | Capture in `captures/` |
| --- | --- | --- |
| Boot to language picker | 90 s | `baseline-boot.png` |
| Select, then advance 180 s | 270.1 s | `baseline-main.png` |
| Select Music, then advance 30 s | 300.1 s | `baseline-music.png` |
| Rotate +16, then advance 10 s; Songs highlighted | 310.2 s | `baseline-music-selection.png` |
| Select Songs, then advance 30 s; `Corner Test` listed | 340.2 s | `baseline-songs.png` |
| Select track, then advance 8 s; Now Playing | 348.2 s | `baseline-playing.png` |
| Continue the Select/Play sequence recorded in the script; large artwork view | 372.3 s | `baseline-select4.png` |

`baseline-playing.png` shows `Corner Test`, `Synthetic Artist`, and `iTHMB
Controls` beside the asymmetric red/green/blue/yellow image and its white stripe.
The displayed image is 100×100, consistent with the F1028 fixture. Its appearance
alone does not prove which source representation was read: the 200×200 F1029
fixture depicts the same pattern. The later selective color control separates
these display paths. File-read or parser tracing has not been performed. The
baseline establishes that this synthetic library is browsable and produces the
expected artwork pattern in this emulated Now Playing screen.

At 372.3 simulated seconds and 755,118,195 executed instructions, the larger view
displays the pattern at 200×200. An independent pixel comparison of the region
`x=60..259, y=32..231` against `expected-200.ppm` found **all 40,000 pixels equal**.
The exact expected-image hash is recorded below. This comparison alone validates
the captured pixels, not the identity of the source representation.

A second run starts from a fresh copy of the pristine baseline image and uses
`run-artwork-experiment.ps1`. Its final `baseline-repeat-large.png` is
byte-identical to `baseline-select4.png` and ends at the same instruction count.
The script and `logs/baseline-repeat-report.json` record the full command sequence,
clock and RTC, executable hash, input/output hashes, normal exit code 0, and saved
snapshot. The script uses no GUI input or snapshot restore. The executable hash
for this repeat is
`8d8e7e3848bcbb0f41a4084d4a236e69425bfe25731d7651e484775f17c5bc00`.

The two baseline source representations depict the same pattern. Consequently,
even this exact large-image match does not by itself exclude enlargement of
F1028 or another fallback. The selective color control below addresses that
ambiguity for the baseline path.

| Artifact | SHA-256 |
| --- | --- |
| `captures/baseline-songs.png` | `3520eb17d0e8a2aac8971d9ecd4acf9da687e9ffe0ceb9e714c0580dd80c45c8` |
| `captures/baseline-playing.png` | `9c291ed9515a4c35b5abf576fd4d1d723e4c5288fefdcbae5584fd1cb79482b1` |
| `captures/baseline-select4.png` and `captures/baseline-repeat-large.png` | `86d7d445c0685d0ec24f7536c708a1778c37ff650db5bceafa093cc69fa0d8ef` |
| Local fixture `expected-200.ppm` | `e177229b1be43ce9201f8a5afd62bf8454e5a3aff8b64fcd78d4692574452b2b` |
| `logs/baseline-repeat-report.json` | `21860a33cd004dab2cd019bd04a7fdc1833b9998be2daeb792a70e9fa38e3256` |
| `run-artwork-experiment.ps1`, baseline-repeat version | `ca7cebc606107a3f2d8b2ff1149bc9f50aa53abf2ea987cfc8cae737b2c226dc` |
| `run-artwork-experiment.ps1`, after adding the color-control variant | `892f6e17cf6ab968c207b46932a0bc95a0b003bb3d8833b6882d0cadf061f1cc` |

## Prepared fixtures

The local fixture manifest is
`.scratch/ithmb-emulator/fixtures/manifest.json`; its hash is recorded above.
These are **synthetic test inputs**, not captures from iTunes or a physical iPod.
The manifest describes database version `0x19`, MHIT header size `0x148`, artwork
root value `2`, and one generated track. The audio is a 30-second 440 Hz stereo
44.1 kHz, 128 kbps MP3 without embedded artwork. The artwork is independently packed
little-endian RGB565 with red, green, blue, and yellow corners, unequal boundaries,
and a white upper stripe to expose orientation and row errors.

| Variant | Controlled intervention | F1029 payload |
| --- | --- | --- |
| `baseline` | F1029 MHNI references offset 0 in `F1029_1.ithmb` | One 80,000-byte image |
| `offset-only` | F1029 MHNI offset changes from 0 to 80,000; the same image follows an 80,000-byte magenta control image | 160,000 bytes in `F1029_1.ithmb` |
| `second-shard-only` | F1029 MHNI filename changes from `_1` to `_2`; payload moves unchanged and `_1` is absent | Original 80,000 bytes in `F1029_2.ithmb` |
| `pixel-control` | Only F1029 pixel bytes change; database records and other inputs remain identical to baseline | 80,000 bytes: 40,000 little-endian `0xF81F` words, solid magenta |

The original three prepared trees share the same iTunesDB, F1028 image, audio, and SysInfo
bytes. **Injection excludes the fixture's SysInfo**, preserving the empty
firmware-created file instead. Injection/readback reports are under the lab's
`injection/` directory; the baseline report is
`baseline-20261011-082008-900/report.json` and records matching hashes for the five
injected files plus preserved firmware-created files.

The manifest records exactly three changed ArtworkDB bytes for the offset variant
(offsets 680–682) and one for the shard variant (offset 786). This controls the
fixture construction; it does not prove that the firmware reads the intended
record or accepts any variant. Key hashes from the manifest:

| Artifact | SHA-256 |
| --- | --- |
| Shared iTunesDB | `2ceaecf905f99a6a8598902df4297ed88ff353a48ca82af0c3b948de078164aa` |
| Baseline ArtworkDB | `dc0263d4f09c5d1486a0eaed25b82c8cf5b76b386db4d9debc83ae8ce765fc7a` |
| Offset-only ArtworkDB | `f83e22d9cdb9cc01f84b3b05409b67f7381d56e4dedcf28a6da02cd8b75dcdc2` |
| Second-shard-only ArtworkDB | `c30acd1d88fb6bd9b17852095072d52ec7b975fbee1073e52f5e24b6840cc169` |
| Original F1029 payload, in either shard | `c77f3f1d7e53ab1a0cc5df506317377c6240e73052f92ff069caf1ca0d7c3fe3` |
| Offset-only F1029 file | `e9a5dbc72b9fddba34f1264b63c68641492dc55387d22b8f066a452a9c431bcf` |
| Color-control F1029 file | `1aa73166f8a101df81e3d4be83cd97a5057d6186ae81015a65c3a98ec977c356` |

The color control was added separately after the original three-variant manifest.
Its injection report is `injection/pixel-control-20261011-083130-844/report.json`.
The analyzer verified that all six baseline/control source fixture files match
their manifests and that only F1029 differs. Injection again excludes the source
SysInfo. This is a content intervention, not an ArtworkDB metadata change.

The fixtures, generator, and run artifacts are local research materials, not
committed regression fixtures. Each result must identify the exact image
containing them, not just the source directory before injection.

## Controlled results

Each run uses a fresh working copy of its pristine injected image, the same
firmware/NOR and trace executable, fixed clock/RTC, and the recorded input
sequence. All completed normally with exit code 0. The offset run used its own
recorded command file; baseline repeat, shard, and color control used the script.
The final captures are at approximately 372.3 simulated seconds.

| Run | Executed instructions at final checkpoint | Large-view result |
| --- | --- | --- |
| Baseline repeat | 755,118,195 | All 40,000 pixels match the expected pattern; final PNG byte-identical to the initial baseline. |
| Offset-only | 755,284,678 | All 40,000 pixels match; final PNG byte-identical to baseline, not the magenta image at offset 0. |
| Second-shard-only | 755,118,195 | All 40,000 pixels match; final PNG byte-identical to baseline with the payload in `_2` and `_1` absent. |
| F1029 color control | 755,118,195 | All 40,000 pixels are exactly RGB `(255, 0, 255)`. The earlier small-view PNG remains byte-identical to baseline. |

For the color control, the small-view region `x=16..115, y=65..164` also matches
all **10,000 pixels** independently decoded from F1028. The selective change
therefore demonstrates that the observed large baseline view depends on F1029
content; it is not merely the unchanged small image enlarged. This conclusion is
from controlled outputs, not a trace of the firmware's file-read instructions.

Together these results **support** honoring a nonzero F1029 offset and an MHNI
filename ending in `_2` for the tested configuration. They do not prove that no
fallback occurs specifically in either altered metadata case: F1028 still depicts
the same pattern. A stronger follow-up would give F1028 a different pattern in
every variant, or trace the actual file/range reads. No maximum shard size, shard
count, global format-ID mapping, or other firmware behavior was tested.

Detailed provenance and comparisons are in the lab's `logs/` directory:

| Record | SHA-256 |
| --- | --- |
| `offset-only-result.json` | `5b19b089e3d16848f72206ff96f4b659d1581b7201892db80c9c4106468d7867` |
| `second-shard-only-repeat-report.json` | `d8526490bbdc0c9505986dc68bd3c2a784cec7a43845f2d66e11814e7c2359ad` |
| `pixel-control-run-report.json` | `57e7abe33616220a1ade5d04b7e346de9b9b3b3e47c0cdeb608964a36d469d82` |
| `artwork-repeat-comparison.json` | `c9bee031649ca224fdfb6a4aa575e5e9d915260a91ec35ec725f2d3360345670` |

`analyze-artwork-screens.py` performs the independent pixel comparisons. The
three expected-pattern final PNGs share SHA-256
`86d7d445c0685d0ec24f7536c708a1778c37ff650db5bceafa093cc69fa0d8ef`;
`captures/pixel-control-run-large.png` has SHA-256
`32937e846f3011dbb384b65193f11e78dc4e6fb013efb558eb692054c1f30849`.

Pristine image hashes supplement the baseline hash recorded above:

```text
offset-only.img
8267486181ffda9ff84fdb0f21caf025bcdca3943d9eae57f26e047f12cc1b72

second-shard-only.img
935f84ac3e078e5e31eafc4e01e1d4b973d9de17a9d96acf5fe9be097c5d996c

pixel-control.img
4fa04d71efe86edf82bc668221d33b593c2cc0618444f1c9dddfae984476ec5c
```

## Evidence limits and next questions

The baseline browsing/display control, fresh repeat, and F1029 content control
have passed. The next useful evidence is tracing file ranges and ARM-produced
pixels before the synthesized BCM display boundary, and validating a matching
fixture on a physical device with recorded firmware.

A screenshot can establish **what this emulated display showed**. It cannot alone
establish the firmware's byte-range interpretation, accurate VideoCore behavior,
or physical-device compatibility: the emulator's presenter copies RGB565 surfaces
itself. These Video 5G experiments also cannot settle F1061 behavior on Classic or
nano devices. Any successful result remains scoped to the exact firmware, fixture,
boot path, and emulator build used. [Display implementation][video],
[assessment and coverage](ipod-emulator-assessment.md),
[evidence standards](validation-and-open-questions.md).

[upstream]: https://github.com/siggifly/ipod-emulator/commit/d39e850ac07baa28abbdd8b00b77b834a757b5e1
[nor]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/nor.rs#L7-L52
[matrix]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/17-the-boot-matrix.md
[ledger]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/research/04-bypass-ledger.md#L27-L56
[video]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/hw/video.rs#L585-L672
