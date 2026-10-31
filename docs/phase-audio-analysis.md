# Phase gameplay analysis

Saving the Phase Playlist now analyzes eligible music instead of generating
regular placeholder events. Eligibility remains the firmware/game rule: music
with whole-second duration 30 through 1800. Repeated Playlist occurrences share
one chart for the Track persistent ID. Other media stays in the Playlist without
an invented analysis record.

## Audio and bounded processing

The shared FFmpeg decoder accepts a verified incoming Host file or a validated
device-relative music path. Its explicit demuxer and protocol restrictions match
Genius. Acoustic analysis requests complete mono float32 PCM at 22,050 Hz;
instrument analysis requests stereo at 44,100 Hz and derives mono for pulse
tracking. Both are capped at 1801 seconds. Decoded duration must agree with the database within three seconds;
extra encoder padding is clipped at the declared duration. Non-finite samples
and decode errors stop preparation with an error.

DSP uses librosa 0.11 with a 2048-sample centered STFT and 256-sample hop
(11.61 ms). Core blocks contain 2048 frames, with 64 context frames on either
side. HPSS uses a 31-bin median kernel and separation margins of 2. The spectral
power sent to a 64-band mel transform combines 75% percussive and 25% full
magnitude, retaining pitched attacks. A second mel transform measures harmonic
power independently for pitched attack candidates. Mel analysis begins at 20 Hz.

The implementation keeps bounded full-song PCM and compact feature vectors;
large spectrograms, HPSS intermediates and tempograms are block-local. It avoids
allocating a whole-song tempogram. Two DSP threads process at most two spectral
blocks at once, sharing read-only PCM. Their feature results are assembled in
the original order on the coordinator thread. Beat tracking, decoding, device
reads, hashing and publication remain serial. This bounds extra working memory
to another block rather than another whole decoded song.

Only the coordinator invokes the caller's cancellation checkpoint. It checks
while waiting for workers, signals them to stop on cancellation or failure, and
joins them before returning. A running native median filter must finish before
that worker can stop. FFmpeg remains cancellable through Storage's runner.

The optional `max_workers=1` argument supports diagnosis and exact serial/parallel
comparison; normal saves use two workers. The current algorithm version is
`librosa-phase-6`; older charts regenerate on the next ordinary Phase Save/Sync.

A historical version-1 benchmark of a warmed 120-second authored music fixture
measured 7.19 seconds with the original
serial code and 4.41 seconds with two workers on the development Windows host
(about 39% less DSP time). The complete chart compared exactly equal, including
all integer timestamps and magnitudes. The profile attributed 5.9 of 6.4 seconds
in an earlier serial run to HPSS, primarily native median filtering. These are
DSP measurements, not a promised end-to-end USB save speedup; startup and decoding
still contribute to the first-track cost.

## Events and strengths

For attack detection, three mel regions cover below 250 Hz, 250 to 2000 Hz, and above 2000 Hz. Positive
spectral-flux onset envelopes are balanced using each region's 95th percentile
of positive strengths. Their clipped mean drives librosa onset detection with
delta 0.1 and a minimum wait of approximately 60 ms. Centering of the provided
spectrogram is accounted for without adding a second FFT-centering delay.

These detection regions are iOpenPod policy and no longer define the encoded
strengths. Version 6 separately measures positive increases between consecutive
linear STFT magnitudes, pooling their squared values within **80–300 Hz,
400–1500 Hz, and 2000–4500 Hz**, then taking the square root and dividing by the
FFT size. Both mix and separated sources use this same measurement. These are
the shipped ranges, including their deliberate gaps; the original filter and
quantizer remain unknown. The
[native parameter research](research/phase-parameter-semantics.md) confirms that
band ordering seeds primary and alternative lanes while their sum drives stock
selection priority. Detection normalization must not define those lane strengths.

The upper beat field's original producer meaning remains unresolved.
The [consumer and lifetime audit](research/phase-beat-field-semantics.md) supports
treating it as unused for gameplay generation in build 3168002; an optional
diagnostic path reads and discards it. Encoding onset strength there is our
policy, not a verified original meaning.

Each acoustic family has independent band scaling and attack detection. Harmonic
flux uses a three-bin frequency maximum filter to reduce vibrato detections.
Harmonic candidates are gated when harmonic RMS falls below 15% of total RMS or
0.00001. These families do not identify literal vocals, guitar, or bass.
An additional articulation gate compares harmonic spectra four frames apart:
cosine distance must exceed 0.02 or magnitude norm must rise by more than 8%.
Otherwise harmonic flux is suppressed. Percussive-emphasized flux is suppressed
only when that articulation is absent and percussive RMS is below 5% of total
RMS. A loud held melody must not erase quieter real drums. This gate prevents
percentile normalization from turning tiny changes in a held tone into taps.

## Shared attack evidence

Both acoustic families contribute their detected attacks, independently of
instrument estimates. Full-mix linear spectral increases at those frames supply
the base magnitudes. One 95th-percentile scale from the strongest band at each
active mix attack calibrates all three bands and every source. If no mix attacks
are available, selected source frames supply the calibration positions.
Per-band normalization is only for detection and passage scoring: it must not
turn a quiet spectral region or source into maximum-strength notes merely
because those are its loudest attacks.

For an attack vector with maximum `peak`, its encoded maximum is
`31 * min(peak / scale, 1) ** 0.65`. Every component receives the same gain before
rounding to five bits. Compression and saturation therefore preserve the vector's
ratios; finite rounding can still create ties or remove very weak components.
The native game supplies lane variation. We neither equalize lane counts nor
assign instruments to fixed lanes. See [ADR-0221](adr/0221-preserve-phase-spectral-lane-evidence.md).

Source detections within four frames (46.44 ms) of a mix attack annotate that
attack at its existing timestamp. Other eligible source attacks add candidates.
Near-coincident detections are merged; mix timings take precedence, then stronger
source-only evidence. A selected foreground attack receives a 15% magnitude
preference before quantization, applied once even when multiple detections support
it. Accompaniment is not attenuated. Missing or empty source evidence cannot
replace the base pool with an empty chart. No random switching, copied timings,
or synthetic taps are introduced.

Pulse tracking continues to use the percussive-emphasized envelope independently.
Native Phase chooses difficulty, spacing, lanes, checkpoints, and sweeps from
this evidence. This supersedes ADR-0214's exclusive acoustic passages and
ADR-0215's 120 ms lead-priority gate and 60% supporting magnitudes. See
[ADR-0217](adr/0217-preserve-phase-evidence-for-native-difficulty.md).

## Instrument parts and recurring hooks

When Demucs and PyTorch are installed, normal Phase saves use the six-source
`htdemucs_6s` checkpoint, loaded by its fixed signature `5c90dfd2`. Its sources are
vocals, guitar, bass, drums, piano, and other. These are learned estimates, not
guaranteed labels; `other` is never relabeled guitar. The existing optional stack
can be installed with `uv sync --locked --extra synesthesia-gpu`. Restart the
application after installation. The first analysis downloads the approximately
52 MiB checkpoint to the provider's Host cache. Provider absence uses acoustic
analysis and is logged; provider failure stops preparation with its error.
The checkpoint resolves directly through Demucs RemoteRepo, using the published
hash-bearing filename and Torch cache. No Hugging Face model-alias lookup or
Hugging Face credentials are required for this model.

Inference runs on CUDA when available, otherwise CPU, with random shifts disabled.
Cores contain 344 Phase frames (about four seconds), with 86 context frames on
either side. Each block is separated, downmixed and resampled to the common
22,050 Hz grid, then reduced to band attacks, RMS, and pitch-class evidence.
Context is discarded before assembling the whole-song vectors. No full-song stem
buffers are allocated or persisted. Stereo PCM itself is bounded to about 606 MiB
at the duration limit; mono conversion and feature arrays require additional Host
memory. A model load or current inference cannot be interrupted halfway through;
checkpoints run before and after inference and between source measurements.

Source attacks use the same articulation and vibrato suppression principles as
the acoustic path. A source must reach 12% of the full-mix RMS and the
absolute audibility floor to emit candidates. Its passage power share must reach
4% to compete for focus. Scores combine square-root power share, bounded attack
clarity, recurring-note fraction, a modest preference for vocals/guitar, and a
continuity bonus. Eight-pulse and four-second opportunities define passages with
a minimum two-second residence. Audible parts with eligible passage scores also
retain their measured attacks under a sustained lead. Shared calibration and
the bounded foreground preference described above preserve their relative
strengths. If stereo sources survive a silent mono fold, their combined RMS and
summed linear attack magnitudes supply the missing mix reference; pulse events remain empty.

Hook recognition compares overlapping six-note sequences, using pitch-class
vectors just after each attack and normalized inter-attack intervals. A sequence
must span 1–12 seconds. Matches require mean pitch similarity above 0.90, interval
differences at most 0.045 of phrase duration, and a duration ratio from 0.75 to
1.33. Nonoverlapping occurrences are required. A steady single-pitch pulse alone
is rejected. Up to 128 active prototypes per source are retained, retiring the
least recently heard so late-song material can be recognized too. This is a
bounded heuristic: missed notes, transposition, or substantially altered phrasing
can prevent a match. It does not infer semantic chorus/verse labels.

All occurrences participate in scoring, including the first occurrence of a
returning phrase. A recognized hook earns preference, but cannot override the
audibility gates. Each occurrence contributes its own measured notes; no copied
timing or invented events are added. Source spectral bands augment the shared
evidence pool. Pulse tracking remains independent. See
[ADR-0215](adr/0215-follow-phase-parts-and-recurring-hooks.md).

## Native events

Frames quieter than 1% of peak spectral RMS, or below absolute threshold 0.00001,
cannot generate events. Beat tracking runs in local core blocks with 256 context
frames, allowing tempo estimates to change across the track. Overlap events are
kept only in their own core block; another 120 ms gate avoids seam duplicates.
There are no fabricated beats in silent sections.

| Event | iOpenPod mapping | Native representation |
| --- | --- | --- |
| Transient time | Detected attack frame | Absolute unsigned Q16.16 seconds after byte `0xff` |
| Three transient strengths | Linear spectral increases in the shipped bands on one shared scale, with bounded foreground preference | Three five-bit values packed into a u16; sum supplies stock priority, ordering seeds lanes |
| Beat time | Locally tracked pulse frame | Absolute unsigned Q16.16 seconds after byte `0xff` |
| Beat strength | Retained onset-envelope mapping; original producer meaning unknown | High four bits of a u8; unused for gameplay in audited build 3168002 |
| Beat accent | Full-mix spectral RMS smoothed over approximately 250 ms | Low four bits of a u8; native relative passage power |

Beat fields retain percentile scaling, clipping and exponent 0.65 before
quantization to 0–15. Attack compression uses the shared vector gain above.
Timestamps stay before the declared end of the Track. The codec
requires strictly increasing timestamps, validates magnitude bounds and limits
each stream to 20,000 events. If transient evidence exceeds that ceiling, retain
the strongest observed event in each of 20,000 equal-duration buckets. This
preserves quieter sections rather than selecting only a song's loudest events.
All timestamps remain measured attack times. Silence produces two empty streams. The old
placeholder builder remains available only for research fixtures.

These assignments are a new musical interpretation of the known packed fields.
The original iTunes analysis algorithm and all downstream gameplay semantics are
not claimed to be recovered.

## Saving and reuse

The automatic playback-history save during device selection preserves Phase
companions and their captured index precondition. It does not analyze audio or
upgrade charts. Ordinary saves and Sync perform pending analysis, including any
membership changes from selection-time Smart Playlist refresh. Shutdown shares
cancellation with the selection history transaction. See
[ADR-0216](adr/0216-defer-phase-analysis-during-device-selection.md).

Analysis happens during Library preparation, after final Track and Playlist IDs
exist and before any device writes. New audio imports are analyzed from their
prepared Host source. Existing audio is fingerprinted through Storage and those
fingerprints become transaction dependencies. Inputs are checked again after
analysis; changing inputs fail preparation or invalidate the reviewed save.

`iPod_Control/iOpenPod/phase-analysis-v1.json` stores a per-PID provenance string
containing algorithm version, source-provider identity, source content SHA-256, declared duration and chart
SHA-256. The first analysis upgrades existing untracked charts, including old
placeholders. Matching entries reuse the existing encrypted chart bytes; changed
audio, changed duration, changed algorithm or changed chart data triggers fresh
analysis. Provider identity includes the model signature, Demucs and Torch
versions, CPU/CUDA backend, zero-shift policy, and mono/stereo input mode.
Installing a provider upgrades acoustic charts; provider errors never silently
produce charts under the wrong identity. The metadata file retains only the current indexed tracks and is
bounded to 8 MiB. Charts, provenance, the Phase Library index and database changes
are published together in the normal recoverable Storage Transaction.

## Verification

Version 6 adds waveform and authored-evidence tests for shipped range gaps,
linear amplitude scaling, primary/alternative band ordering, loud-attack
saturation without artificial ties, and source/mix measurement consistency.
Existing timing, tempo, hook, cancellation, quiet-passage, and publication
regressions remain. The [version-6 evaluation](research/phase-algorithm-v6.md)
compares native lanes, timing, tap counts and inferred foreground coverage on
the five existing music fixtures. Headless output does not establish play feel.

Version 5 was iterated against the original native converter on five local music
fixtures, with and without source estimates. All four native difficulty indices
complete. Windows/ARM comparisons on Hard agree on exact tap records, annotation
payloads, and marker strings for all ten inputs. The five source-assisted Hard
tap counts change from 284/159/202/133/132 to 315/168/202/147/145. These are taps,
not counts of all interactions; native sweep annotations remain separate.
The [evaluation record](research/phase-algorithm-v5.md) gives fixture identities,
iterations, and the limits of these measurements.

New authored regressions cover incomplete source evidence, whole-mix energy
changes under constant harmony, quiet-source calibration, shared-attack
preference, and preservation of quiet sections at the codec ceiling. The mixed
melody/drum test now requires both families to survive before native selection.

Version 4 fixes a reproduced source-direction failure: adding eight sustained
vocal attacks to 64 audible accompaniment attacks previously reduced a 16-second
chart to eight events. Regression tests now retain the accompaniment while
keeping vocal attacks stronger, for both drum and guitar support. This does not
establish that every sparse-song report is fixed.

The Windows research harness executes the original phrase selector translated
to native C++, with 200 candidate-vector results matching unchanged ARM execution.
It is a headless diagnostic, not a playable Phase port. The local *Poppies* FLAC
produces 570 version-3 candidates and 705 version-4 candidates. The native
constructor, checkpoint builder, and phrase-selection stage retain 377 and 378
respectively. Later native transforms emit 282 and 284 tap records plus separate
sweep/timing annotations. The Windows translation matches the ARM output;
rendering, audio synchronization, and judgment remain unverified. More analysis
records therefore do not establish substantially denser gameplay. See the
[Windows feasibility and native-selection research](research/phase-windows-recomp-feasibility.md).

Part tests cover vocal-to-guitar handoffs, recurring guitar preference over louder
drums, timing retention under tempo variation, changed pitch-order rejection,
steady-pulse rejection, quiet leakage, invalid evidence, provider cancellation,
stereo decoding, and provider-identity cache invalidation.

On 2026-10-30, the installed Demucs 4.1.0 / Torch 2.14.0 CUDA provider analyzed the
first 45 seconds of Karissa Hobbs's *Let's Go Fishin'* twice. Both feature arrays
and final chart events compared exactly equal on this Host. The resulting 123
transients and 89 pulses were accepted by the hash-checked build-3168002 native
parser, with decoded counts and first transient fields verified. Separation and
charting for the two runs plus the parser probe took about 17 seconds on this Host;
this is not a CPU or end-to-end save benchmark. The recording is the librosa
[segmentation example](https://librosa.org/doc/0.11.0/auto_examples/plot_segmentation.html),
licensed CC-BY-NC-SA-4.0; no recording or separated waveform is committed. The
private reproduction script and receipt are under `.scratch/phase_v3_verify.py`
and `.scratch/phase-v3-verification.json`. This is an integration and repeatability
check, not a ground-truth source-identification accuracy study or gameplay test.

An authored mixture retains both pitched phrases and continuing drums, with exact
serial/parallel equality.
A sustained-tone signal with mild vibrato retains its attack without repeated
interior transients.

Authored pulse signals test attack alignment within 90 ms, multiple spectral
regions, silence, local tempo changes, magnitude limits and deterministic events.
A WAV fixture exercises real FFmpeg decoding and librosa analysis. Virtual Storage
tests cover cache reuse and source changes alongside ordinary publication tests.
Offline execution of the hash-checked Phase build-3168002 parser accepts both
musical and zero-event charts and agrees on counts, first timestamps and packed
strength decoding. Physical gameplay remains to be evaluated on an iPod.

API references: [onset detection](https://librosa.org/doc/0.11.0/generated/librosa.onset.onset_detect.html),
[beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html),
and [HPSS](https://librosa.org/doc/0.11.0/generated/librosa.decompose.hpss.html).
