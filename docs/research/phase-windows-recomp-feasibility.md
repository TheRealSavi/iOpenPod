# Phase Windows recompilation feasibility

Investigation date: 2026-10-31. Upstream examined at
[`8a7afced6b30ff9dd3ef71aeebf620f34ced5317`](https://github.com/DogParty/iPodClickWheelRecomps/tree/8a7afced6b30ff9dd3ef71aeebf620f34ced5317).
The local checkout is ignored under `.scratch/phase-windows/upstream`.

## Finding

The project supplies a credible foundation for a Windows Phase port, but Phase is
not a supported title. Its six titles are Mini Golf, Cubis2, HoldEm, Lost, Sims
Bowling, and Vortex. The project describes Windows support for those ports, with
Windows specifically described as lightly tested in Vortex's README. This is not
evidence that Phase runs on Windows 11. The follow-up below builds a native
Windows diagnostic executable, but no playable Phase port has been demonstrated.
[Upstream overview][overview],
[Vortex build instructions][vortex-readme].

The first local experiment established two concrete incompatibilities before a
host executable could be produced: the shared recompiler does not understand
instructions present in Phase, and its import reader overlooks Phase's Settings
thunk. More extensive work remains in the game's host interfaces, especially
music-library metadata, audio timing, and its separate SoundEffect framework.
These are observed source differences and failed translation probes, not an
estimate based only on the README.

For the immediate chart-quality problem, the useful acceptance target is the
number, timing, and lanes of **playable gems produced by Phase**, rather than the
number of records in Phase Gameplay Analysis. The existing integration validates
the PHZ parser, but expressly does not establish physical gameplay quality.
[ADR-0210](../adr/0210-analyze-phase-playlist-audio-with-librosa.md).

## What is reusable

| Component | Existing capability | Phase qualification still needed |
|---|---|---|
| ARM-to-C++ tools | eApp image reader, function discovery, control-flow analysis, generated function table and import bindings | Instruction coverage and discovery of Phase's indirect targets |
| Guest runtime | ARM registers/flags, bounded guest-memory access, heap, indirect dispatch | Phase image/BSS/stack ranges and startup contract |
| Graphics | Shared software implementation of iPod graphics/OpenGLES, render scaling | Phase's actual ordinal mapping and drawing state; screenshot comparison |
| Desktop | SDL3 window, keyboard/gamepad input, settings, Windows memory/platform support | Phase click-wheel and button semantics; avoid another title's memory addresses |
| Audio | PCM effects, queued music playback, Windows Media Foundation decoder | Phase SoundEffect ABI, song position, pause/seek, and synchronization |
| Files | Resource lookup, asynchronous completion queue, persistent saves | Separate game assets, Phase Library/chart paths, and user music |
| Validation | Headless target, scripted input, frame limits, framework-call logging, image/call oracles | Phase-specific recordings and expected behavior |

These facilities are visible in [the common layout][common],
[the build definition][cmake], [the frame pump][main],
[the file adapter][files], and [the music decoder interface][decoder].
The common CMake target does not by itself provide a complete new-game adapter:
much of the frame pump, framework ABI, and SDL host still lives under each title.
[Shared build sources][common-cmake].

The existing Vortex frame pump contains title-specific button flags at
`0x18063E5C`, a particular context reason policy, clock progression, and graphics
attribute policy. Copying it would provide scaffolding, not a verified Phase
startup implementation. [Frame pump][main].

## Input already available locally

The offline firmware lab already has a plaintext Phase build-3168002 eApp:

| Property | Observed value |
|---|---|
| File | `../ipod-firmware-lab/artifacts/phase-game/Phase_3168002.plain.bin` |
| Size | 947,252 bytes |
| SHA-256 | `35834fede51f170a0b0bda8e380e1c12af0f86ca1a7952e5abfbb24ab4082258` |
| Load base used by both tools | `0x18000000` |
| Nonzero header vectors | `0x1807EB10`, `0x1807EAB0`, `0x1807EB70` |

The size and vectors were read using upstream `EAppImage.load`; the hash is bound
by the existing [native decryption receipt][decryption] and
[native game-contract probe][contract-probe]. The upstream reader accepts this
file as an eApp without conversion. It does not supply the original game's
assets or remove their need at runtime. [Image reader][image],
[Vortex instructions][vortex-readme].

Useful existing local evidence includes the [Phase import inventory][imports],
the [game function survey][survey], and the [extracted asset index][assets].
These are private research inputs outside the iOpenPod source distribution.
The [existing metadata research](phase-application-contract.md#classic-game-facing-metadata-api-follow-up)
already maps a substantial part of Phase's library-facing ABI to inspected
Classic firmware. It can inform host shims without emulating all of RetailOS.

## Recompiler experiment

The baseline probe used the unmodified pinned upstream sources, no runtime
bindings, and only header/import seeds. From the iOpenPod root:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(
    ".scratch/phase-windows/upstream/common/tools"
).resolve()))
from recomp.functions import build_function_table
from recomp.generate import Bindings, Generator
from recomp.image import EAppImage

image = EAppImage.load(Path(
    "../ipod-firmware-lab/artifacts/phase-game/Phase_3168002.plain.bin"
))
functions = build_function_table(image, [], set(), image.end, set())
generator = Generator(
    image, functions, Bindings(), set(), "Phase feasibility", namespace="phase"
)
generator.discover_all()
```

The Python block was supplied to `uv run python -`. It failed after discovering
10 function bodies, with 527 table entries, at function `0x180A8D8C`:

```text
0x180a8d9c: e16fcf11 — cmn without S bit (msr-space encoding)
```

The word is in the ARM CLZ instruction space. A diagnostic rerun excluded the
failing function in memory only, then repeated that process to expose further
failures. Another such failure occurred at `0x180A95D4` (`e16f1f10`). The next
failures included BLX-register words `e12fff31`, `e12fff32`, `e12fff3c`, and
conditional `112fff31`, reported as unsupported MSR encodings. The current
unmodified decoder recognizes BX but has no CLZ or BLX operation. Excluding 12 failing
functions reached only 98 bodies; it did not complete discovery. Exclusions were
diagnostic only and are not a correctness-preserving port.
[Decoder][arm], [control-flow walker][cfg], [C++ emitter][cpp].

The initial required increment was tested instruction support covering decode,
control flow, condition handling, link-register semantics, and emitted behavior.
Then rerun discovery and compare relevant functions against native execution.
Successful discovery alone cannot prove that every function-pointer target was
found. Upstream's title driver supplements header seeds with recorded calls,
stored code pointers, PC-relative code addresses, and explicit extra entries.
[Vortex discovery driver][funcs].

There is a separate import-reader problem. Phase's Settings descriptor has:

| Field | Value |
|---|---|
| Descriptor file offset | `0xF94` |
| Declared count | 1 |
| Link pointer | `0x18000FD8` |
| Thunk address | `0x18000FCC` |
| Thunk instruction | `0xE51FF004` |

That is a negative-offset `LDR pc, [pc, #-4]`. Upstream's mask recognizes only the
positive-offset form, so `EAppImage.frameworks` omits Settings even though the lab
inventory identifies a call to it. Adjusting the import mask and validating both
forms is necessary before generated bindings can represent all Phase imports.
[Image reader][image], [local import inventory][imports].

## Native Windows implementation follow-up

The ignored checkout now has tested support for CLZ, BLX-register calls,
ARMv5TE dual transfers, saturating arithmetic, signed halfword multiplication,
and PC-relative absolute-pointer jump tables. It recognizes negative-offset
import thunks and guards the compiler-specific format attribute for MSVC.
The local patch is `.scratch/phase-windows/phase-armv5te.patch`.
Instruction behavior was checked against the
[Arm instruction reference](https://documentation-service.arm.com/static/6245c734b059dc5ff9a8bdab)
and unchanged ARM execution with Unicorn 2.1.4.

Using the lab's function inventory and additional indirectly called entries
observed during bounded execution, the tools translate over 3,500 functions.
MSVC 19.44 builds them into `phase-native-probe.exe`. This is a **headless research
executable**, not a windowed game. Its adapters stop on unknown framework calls;
allocation uses a bounded research arena, not a production allocator.
The host uses the [documented MSVC command environment](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line).

Validation is stronger than successful translation:

- Nine authored decoding/control-flow regressions pass.
- 1,792 authored instruction executions compare all registers, flags, and touched
  memory with Unicorn across 28 CLZ/DSP/dual-transfer encodings.
- 200 deterministic candidate-vector cases produce identical selected indices
  in native Windows C++ and the unchanged ARM selector.
- From identical post-constructor/checkpoint snapshots, native Windows function
  `0x18053580` matches every five-word selected record for bundled `fff` (332),
  version-3 *Poppies* (377), and version-4 *Poppies* (378).
- Extending that Windows run through `0x18053F14`, `0x18053CEC`, `0x18056720`,
  and `0x180563B8` matches every emitted tap record and timestamp, all callback
  kinds/times, and marker strings against an ARM recording sink: 250 taps for
  `fff`, 282 for Poppies before, and 284 after. Sweeps are separate annotations;
  these counts are not the total number of playable interactions.

The snapshot comparison adapts allocation/free and symbol interning consistently
on both hosts. The parser/constructor still runs in the ARM oracle to prepare
the snapshot. It is not evidence that native Windows startup, graphics, audio,
or input work. Reproduction commands and receipts live in
[the private harness README](../../.scratch/phase-windows/README.md),
[instruction receipt](../../.scratch/phase-windows/instruction-verification.json),
[selector receipt](../../.scratch/phase-windows/native-selector-verification.json),
the [conversion receipt](../../.scratch/phase-windows/native-conversion-verification.json),
and [output receipt](../../.scratch/phase-windows/native-output-verification.json).

## Host interfaces are the larger porting task

The following counts come from the local import inventory. "Referenced" means
ordinals with recorded static call sites in that inventory; it is not a complete
dynamic call-coverage claim.

| Phase framework | Declared slots | Statically referenced slots |
|---|---:|---:|
| AsyncFileIO | 17 | 5 |
| Audio | 54 | 9 |
| DebugUtil | 5 | 1 |
| InputEvents | 2 | 2 |
| MemoryAlloc | 3 | 1 |
| Metadata | 169 | 13 |
| miscTBD | 13 | 6 |
| OpenGLES | 170 | 21 |
| Settings | 1 | 1 |
| SoundEffect | 42 | 14 |
| Users | 10 | 0 |

Source: [Phase import inventory][imports]. These counts are useful scope clues,
not a measure of implementation difficulty.

Vortex has three explicit Metadata bindings, whose implementation primarily
models an empty music library plus registered soundtrack streams. Phase needs a
real selection adapter: Playlist and Track identities, locations, titles,
durations, and its companion index/chart files. Its known Track-location and
title slots are 100 and 101, for example. An empty-library answer cannot validate
user-song gameplay. [Upstream Metadata implementation][metadata],
[Phase metadata research](phase-application-contract.md#classic-game-facing-metadata-api-follow-up).

None of the five inspected generated-game import maps binds a framework named
SoundEffect, MemoryAlloc, or DebugUtil. Existing sound-effects code operates
through Audio instead. It may offer reusable host operations, but binding names
and ordinal numbers must be established for Phase rather than copied wholesale.
Generated unbound import handlers log and return; that makes linking possible,
not behavior correct. [Vortex binding map][bindings],
[upstream Audio implementation][audio], [generator][generator].

The shared music decoder exposes open/read/restart/close, without a general seek
or playback-position interface. A rhythm-game port needs verified agreement
between the song clock, displayed gems, and button judgment. Adding a window
without establishing that agreement would give misleading feedback about chart
quality. This is a required validation target inferred from the game's purpose,
not a claim that the existing decoder cannot be extended. [Decoder][decoder].

The file adapter currently resolves resources relative to a game's asset
directory and a save store. Phase also requires the Phase Library and per-Track
charts under `iPod_Control/GameData_RW/1D000/Phase Data`, plus music locations.
A private fixture directory containing one Track is sufficient for an initial
test; there is no reason for the port to mutate the Active iPod.
[File adapter][files], [Phase application contract](phase-application-contract.md).

## Smallest milestones that answer the user's question

1. **Translation smoke test:** fix and test the decoder/import issues, generate
   Phase code using its own bindings, and record unresolved instructions and
   functions. Keep the original binary and generated C++ in ignored local paths.
2. **Native gem-conversion probe:** extend the existing offline native parser
   harness through the PHZ-to-gem consumer. For a fixed song, difficulty, and
   random seed, report gem times, lanes, total count, and empty active intervals.
   Compare a bundled chart and an iOpenPod chart. This is the earliest milestone
   that can distinguish sparse analysis from native filtering of that analysis;
   it does not require the full Windows port.
3. **Windows first frame:** create a Phase-specific frame pump and minimal
   framework adapters, serve original assets, and reach a repeatable title/menu
   screenshot in a bounded headless run and an SDL window. Treat unsupported
   critical calls as diagnostics, not silent success.
4. **One playable song:** support one local Track and chart, deterministic input,
   all required audio callbacks, and validated playback position. Complete a
   song with visible gems and working judgment before using the port to tune the
   analyzer. Compare audible and visual timing with the device.
5. **A/B feedback loop:** reload chart variants, retain difficulty/seed, and expose
   gem density and timing traces alongside gameplay. Only then generalize to the
   whole Phase Playlist.

These are proposed increments. The existing parser-only harness supports the
second milestone's starting point; none establishes that a complete Phase game
already boots. [Native PHZ probe][phz-probe],
[upstream headless and desktop build][cmake].

Windows already has two upstream build routes: native CMake/MSVC or the shared
Docker/MinGW cross-build script. The inspected source requires CMake 3.21+, C++17,
SDL3, and zlib; the Python generator requires Python 3.10+. The container script
pins SDL3 3.4.16. No new Python package or production application dependency is
needed merely to run the image/discovery experiment above. This investigation
did not execute either complete-game build route; the follow-up uses a smaller
MSVC diagnostic build. [Build instructions][vortex-readme],
[container build script][windows-build].

Keep the port as an offline verification project while these contracts are
unsettled. That follows ADR-0210's existing boundary for game executables and
emulators. Upstream separates MIT tooling from GPL-3.0-or-later runtime/port code
and keeps user-supplied game material out of its repository. Preserve that source
separation when preparing a reusable port. [ADR-0210](../adr/0210-analyze-phase-playlist-audio-with-librosa.md),
[upstream licensing statement][licensing].

## Native phrase-selection follow-up

Read-only Ghidra exports located a useful seam below the full game. The program
hash remains the Phase hash above. Exports and probe results are private artifacts
under `.scratch/phase-windows/density-research`; the existing lab database was
opened with `-readOnly -noanalysis`, and the export logs confirm that its changes
were discarded.

The following are static findings from those exports:

| Function | Observed role |
|---|---|
| `0x18068C0C` | Loading state machine; case 3 constructs the converter, case 7 selects candidates, and later cases perform additional processing |
| `0x18056FB8` | Converter constructor; parses PHZ into field `+0x8C`, creates beat analysis at `+0x90`, and prepares per-transient beat classification |
| `0x18053580` | Reads difficulty-specific rate/spacing configuration, groups candidates into phrases, scores them, and calls the selector |
| `0x18030964` | Builds a candidate from native transient data, retaining its time/index and band information |
| `0x18055798` | Applies beat-class-dependent score amplification |
| `0x18055224` | Selects strong candidates subject to a target count and minimum temporal separation |
| `0x18056070` | Removes nearby candidates from the remaining index list |

Evidence: [loading/conversion exports][density-export3],
[phrase/config exports][density-export2]. The decompiler's inferred signatures
are not independently reliable; the selector harness used the ARM instructions
to verify its eight-argument calling convention and 20-byte candidate records.

The difficulty mapping is established by two assets: the English locale names
`difficulty_description_3_trad` **Hard**, and every matching `game_type` entry
uses Track index 2. The four analysis slots therefore map to Easy 0, Medium 1,
Hard 2, and Expert 3; extra Insane entries reuse index 3. At index 2, conversion
configuration requests 4.0 gems/second with a minimum interval of approximately
0.219986 seconds in normal passages, and 2.5 gems/second with approximately
0.269989 seconds in soft passages. Native fixed-point conversion to milliseconds
produces 219 and 269 respectively. These are selection settings, not a guarantee
of the final visible rate. [English locale][locale], [game settings][phase-config],
[conversion settings][conv-config], [native phrase reader][density-phrase].

The script [probe_selector.py][selector-probe] executes unchanged ARM code at
`0x18055224` with authored positive-strength candidates. Its only adapters are
bounded allocation at `0x1800DA64` and a no-op free at `0x1800CB98`. Candidate
selection, vector growth/copying, strongest-first comparisons, exclusion, and
result sorting execute natively. Every case supplies a target of eight candidates
and a 219 ms minimum interval, representing the normal Hard settings for a
two-second phrase. The caller's phrase classification and target calculation are
outside this probe.

| Authored candidate input | Native selected count | What it demonstrates |
|---|---:|---|
| 39 evenly weighted events, 50 ms apart | 8 | A dense pool can satisfy the target |
| 8 events, 250 ms apart | 8 | Adequately separated input survives |
| Only 3 separated events | 3 | The selector does not create missing candidates |
| 19 equally weighted events, 100 ms apart | 7 | Spacing and greedy choice can leave the target unfilled |
| 8 events exactly 219 ms apart | 8 | The exact interval boundary is retained |
| Events at 100, 200, 300, 500 ms; 200 ms has twice the strength | 2 | The strongest event removes its nearby weaker neighbors |
| 8 events at 100 + 250n ms, with a previously selected event at 0 ms | 7 | Spacing carries across phrase boundaries |

All seven cases passed, including ordered output and interval checks. The full
receipt records selected indices/times and allocation sizes.
[Native selector receipt][selector-results]. Reproduce from the repository root
with `uv run .scratch/phase-windows/density-research/probe_selector.py`.

One initially plausible explanation is specifically **not supported**: zero
`offbeat_amplifiers` does not directly delete offbeat events. The amplification
routine multiplies a candidate's score by `1.0 + configured_amplifier` in Q16
arithmetic. The separate lookup chooses beat/offbeat/no-beat configuration and
difficulty. Thus zero preserves the incoming score; a positive beat amplifier
still gives on-beat events a relative preference when candidates compete.
This conclusion is from the native instructions/decompilation, not full gameplay.
[Amplifier routine][density-amplify], [configuration lookup][density-lookup].

These measurements demonstrate that candidate scarcity and strength/spacing
competition can reduce the pool further. They do **not** reproduce the reported
song, run the complete PHZ-to-gem pipeline, validate final lanes, or establish the
cause of its sparse gameplay. Later conversion stages and native phrase/soft
classification remain part of the next acceptance milestone.

### Authored sparse-lead reproduction

A separate private probe passes authored source evidence through iOpenPod's actual
`direct_parts` implementation, then through the native selector above in fixed
two-second windows. It uses 16 seconds of drum attacks spaced 250 ms apart and
vocal attacks spaced two seconds apart, with sustained vocal energy greater than
the drum energy. This models a strong held lead over an active accompaniment;
it does not synthesize audio or invoke a source-separation model.

| Input to the same director | Directed transients | Native fixed-window selections |
|---|---:|---:|
| Drums alone | 64 | 64 |
| The same drums plus sustained vocals | 8 | 8 |

All four passages choose vocals in the second case. The baseline director permits
a part with only one detected attack in a passage to compete for focus, scores
prominence/clarity/recurrence without a density requirement, and permits answering
attacks only when the selected part's energy falls below 40% of its typical level.
Sustained vocals can therefore remove a dense audible accompaniment from the
candidate pool. Native selection cannot restore those discarded candidates.
This is a reproducible failure mode of the baseline source director, without a
claim that it is the exact mechanism on the user's Track.
[Baseline receipt and source hash][directed-results],
[reproduction script][directed-probe].

The 8-to-64 comparison is deliberately **not** labeled a final game gem count:
the experiment supplies fixed windows, normal Hard rates, and candidate strengths
directly, omitting the native phrase analyzer, beat-dependent amplification, and
later transformation stages. Reproduce with
`uv run --with unicorn==2.1.4 python .scratch/phase-windows/density-research/probe_directed_pool.py`.
The baseline count assertions should fail after a successful behavior change.

## Native conversion with the real configuration

A subsequent experiment advanced beyond the fixed-window selector. The private
[conversion probe][conversion-probe] runs the original ARM converter constructor
`0x18056FB8`, checkpoint generation `0x18055D1C`, and phrase selection
`0x18053580`. It uses the exact `conv` and `beatmatcher` arrays from extracted
`phase.json`, represented as native DataArray/DataNode objects. Native lookup and
numeric getters execute unchanged. The adapters supply canonical string symbols,
allocation/free, and the same PHZ cryptographic boundary already used by the
parser probe. No config rates, beat classifications, or selected candidates are
substituted in the original-input runs.

The native constructor accepts `(converter, phz_bytes, byte_count, difficulty)`;
the measured Hard runs pass difficulty 2. Its resulting converter fields include:

| Offset | Observed contents |
|---|---|
| `+0x04` | Candidate vector header; count, data pointer, capacity, allocation pointer |
| `+0x54` | Checkpoint time vector |
| `+0x64` | Per-transient beat classification |
| `+0x88` | Checkpoint clearing interval in milliseconds |
| `+0x8C` | Native parsed PHZ object |
| `+0x90` | Native beat/section analysis object |
| `+0xA0` | Conversion config DataArray |
| `+0xA4` | Difficulty index |

The native config root is reached through the pointer at `0x1800B464`, whose value
is `0x180E51DC`; its field `+4` receives the injected root. Beat classification
initialization also sets the amplifier config global at `0x180E5B88`.
Snapshots immediately before `0x18053580` include the 4 MiB guest RAM region,
2 MiB game image/BSS region, registers, allocation cursor, canonical symbol map,
and adapter descriptions. They are private binary fixtures for comparing the
translated Windows executable against ARM execution, not distributable assets.
[Conversion probe][conversion-probe], [Poppies snapshot state][snapshot-state].

Read-only analysis of the local *Poppies* FLAC supplied charts before and after
the sustained-lead support change. They have the same 400 beat records, with
570 and 705 transients respectively. This is real audio rather than the earlier
authored vocal/drum evidence; it may differ from the device's encoding. Input
hashes, image/config hashes, records, and per-phrase calls are retained in each
receipt.

| Input | Transients | Selected before checkpoint exclusion | After checkpoint exclusion |
|---|---:|---:|---:|
| Poppies before | 570 | 414 | 377 |
| Poppies after | 705 | 416 | 378 |
| Bundled `fff.phz` | 510 | 366 | 332 |

Sources: [Poppies before][conversion-before],
[Poppies after][conversion-after], [bundled control][conversion-fff].
The support change fixes the authored starvation case but barely changes native
selection on this song. The extra 135 input events must not be presented as 135
extra gameplay notes.

Poppies produces seven identical power sections in both variants. Calls to the
native selector divide as follows:

| Class | Phrases | Combined duration | Requested count | Before: pool / selected | After: pool / selected |
|---|---:|---:|---:|---:|---:|
| Soft, 269 ms spacing | 72 | 105.83 s | 253 | 384 / 250 | 459 / 251 |
| Normal, 219 ms spacing | 35 | 54.24 s | 215 | 185 / 164 | 245 / 165 |

These selected counts precede checkpoint exclusion. They are totals of actual
native calls, not estimates from the song duration. Soft phrases almost fill
their requested count; the normal phrases remain constrained by candidate
distribution, strength selection, and spacing. The bundled control has 44 soft
and 42 normal phrases, about 68.86 and 67.22 seconds respectively.
[Per-call receipts][conversion-before], [control receipt][conversion-fff].

### Which beat field controls density

The native beat constructor `0x18061FC8` initializes its power records from
parsed beat field `+8`, the PHZ byte's **low nibble** (named `accent` by the
iPodDB codec). It smooths those values, computes a trimmed-average threshold,
labels sufficiently strong regions normal, and combines short sections. The
high nibble at parsed beat `+4` is not this power input. This establishes a native
consumer for the low nibble; it does not reconstruct what signal iTunes originally
measured to produce it. [Native beat analysis][native-beat-analysis],
[native parser][native-phz-parser].

Counterfactual runs changed one decoded beat field before native beat analysis,
leaving the original PHZ file and transient stream intact:

| Poppies before-chart variant | Sections | Selected after checkpoints |
|---|---:|---:|
| Original fields | 7 | 377 |
| High nibble forced to 15 | 7, same section records | 377 |
| Low nibble replaced by the original high-nibble values, with native low-nibble scaling | 9 | 394 |
| Low nibble held at 8 | 1 soft section | 346 |

The constant-energy control is particularly useful: simply raising or flattening
that field does not ensure a dense chart. Native classification depends on the
song's relative power distribution. These are sensitivity experiments, not
proposed production mappings or evidence of a fixed game-quality issue.
[Counterfactual receipts][counterfactual-high], [swapped source][counterfactual-swap],
[constant control][counterfactual-constant].

### Native lane/sweep processing and output boundary

The [output probe][output-probe] continues through `0x18053F14` and
`0x18053CEC`, then executes `0x18056720` and `0x180563B8` with a recording sink.
The sink captures virtual calls at offsets `+8`, `+0xC`, `+0x10`, and `+0x24`;
it replaces storage/listener behavior rather than the native conversion logic.
The later native stages are therefore callable without rendering, playback, or
a complete emulated iPod library.

| Input | Candidates after checkpoint exclusion | After sweep/lane processing | Emitted tap records |
|---|---:|---:|---:|
| Poppies before | 377 | 317 | 282 |
| Poppies after | 378 | 319 | 284 |
| Bundled `fff.phz` | 332 | 283 | 250 |

Both Poppies variants also emit 437 timed annotation calls: 399 of type 4,
30 of type 2, 2 of type 1, and 6 of type 0, plus eight textual markers.
Tap records contain lane masks 1, 2, and 4 and millisecond times; their captured
native output permits a meaningful chart preview. These tap counts are **not**
counts of every playable object: the annotation stream includes sweep-related
interaction, and runtime interpretation, judgment, display, and audio timing
remain unverified. The result still does not establish that the complete Phase
application boots on Windows.
[Before output receipt][output-before], [after output receipt][output-after],
[bundled output receipt][output-fff].

[overview]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/README.md
[common]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/README.md
[vortex-readme]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/README.md
[cmake]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/CMakeLists.txt
[common-cmake]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/CMakeLists.txt
[main]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/src/runtime/main.cpp
[files]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/src/libeapp/async_file.cpp
[decoder]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/src/ipod/platform/sdl3/music_decoder.h
[image]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/tools/recomp/image.py
[arm]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/tools/recomp/arm.py
[cfg]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/tools/recomp/cfg.py
[cpp]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/tools/recomp/cpp.py
[funcs]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/tools/funcs.py
[generator]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/tools/recomp/generate.py
[bindings]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/src/libeapp/imports.json
[metadata]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/src/libeapp/metadata.cpp
[audio]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/Vortex/src/libeapp/audio.cpp
[windows-build]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/common/tools/windows-build.sh
[licensing]: https://github.com/DogParty/iPodClickWheelRecomps/blob/8a7afced6b30ff9dd3ef71aeebf620f34ced5317/LICENSING.md
[decryption]: ../../../ipod-firmware-lab/artifacts/phase-game/native-decryption.json
[imports]: ../../../ipod-firmware-lab/artifacts/phase-game/imports.json
[survey]: ../../../ipod-firmware-lab/artifacts/phase-game/survey/all-functions.tsv
[assets]: ../../../ipod-firmware-lab/artifacts/phase-assets/index.json
[contract-probe]: ../../../ipod-firmware-lab/scripts/probe_phase_game_contract.py
[phz-probe]: ../../../ipod-firmware-lab/scripts/probe_phase_phz.py
[locale]: ../../../ipod-firmware-lab/artifacts/phase-assets/ui/eng/gen/locale.json
[phase-config]: ../../../ipod-firmware-lab/artifacts/phase-assets/config/gen/phase.json
[conv-config]: ../../../ipod-firmware-lab/artifacts/phase-assets/config/gen/conv_phase.json
[density-export2]: ../../.scratch/phase-windows/density-research/export2/index.tsv
[density-export3]: ../../.scratch/phase-windows/density-research/export3/index.tsv
[density-phrase]: ../../.scratch/phase-windows/density-research/export3/18053580.c
[density-amplify]: ../../.scratch/phase-windows/density-research/export3/18055798.c
[density-lookup]: ../../.scratch/phase-windows/density-research/export1/18078fdc.c
[selector-probe]: ../../.scratch/phase-windows/density-research/probe_selector.py
[selector-results]: ../../.scratch/phase-windows/density-research/selector-results.json
[directed-results]: ../../.scratch/phase-windows/density-research/directed-pool-results.json
[directed-probe]: ../../.scratch/phase-windows/density-research/probe_directed_pool.py
[conversion-probe]: ../../.scratch/phase-windows/density-research/probe_conversion.py
[conversion-before]: ../../.scratch/phase-windows/density-research/conversion-poppies-before.json
[conversion-after]: ../../.scratch/phase-windows/density-research/conversion-poppies-after.json
[conversion-fff]: ../../.scratch/phase-windows/density-research/conversion-fff.json
[snapshot-state]: ../../.scratch/phase-windows/density-research/poppies-before-pre53580-state.json
[native-beat-analysis]: ../../.scratch/phase-windows/density-research/export2/18061fc8.c
[native-phz-parser]: ../../.scratch/phase-windows/density-research/export1/18009dc4.c
[counterfactual-high]: ../../.scratch/phase-windows/density-research/conversion-poppies-before-strength_constant15.json
[counterfactual-swap]: ../../.scratch/phase-windows/density-research/conversion-poppies-before-accent_from_strength.json
[counterfactual-constant]: ../../.scratch/phase-windows/density-research/conversion-poppies-before-accent_constant8.json
[output-probe]: ../../.scratch/phase-windows/density-research/probe_output.py
[output-before]: ../../.scratch/phase-windows/density-research/output-poppies-before.json
[output-after]: ../../.scratch/phase-windows/density-research/output-poppies-after.json
[output-fff]: ../../.scratch/phase-windows/density-research/output-fff.json
