# Mono Audio on Classic 2.0.5

Mod Platform Version **0.12.0-dev** includes **Settings → Mono Audio** below
Sound Check. Off is the default. On averages the signed left and right samples
and sends the result to both channels. Equal signals retain their level, and
opposite signals cancel. The frame count, sample rate and stereo transport
format stay the same for headphones and docks.

## Where the output paths meet

These addresses are from the family-38 prepared OS with SHA-256
`660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e`.
The first OS body segment maps to IRAM at `0x22000000` and the segment at
prepared file offset `0xb798` maps to DRAM at `0x08000000`.

| Playback stage | Native 2.0.5 behavior |
| --- | --- |
| Output selection | `0x0818d000` selects one of two playback drivers. Initialization at `0x22007f38` and a route change at `0x220075d0` register the same refill callback, `0x22007840`. |
| Analog output | The codec driver stores the callback at object offset `0x38`. It requests 1,024 frames at startup (`0x081ea954`) and on refill (`0x081eaa4c`), then hands the buffer to DMA. This supplies the analog playback stream used by the headphone jack and dock line-out. |
| Digital dock output | The USB audio driver stores the callback at `0x08a123b0`. The packetizer calls it at `0x080f9fa8` with the total PCM frame count, then divides the returned buffer among five isochronous descriptors for endpoint `0x81`. |
| Final mix | The callback pulls queued PCM, applies channel gain and mixes up to eight additional voices. Each frame contains two signed 16-bit samples. The mod runs at the shared mixer epilogue, `0x22007ed0`, before the callback hands the buffer to either driver. |

The audio hook reads the setting once per block. When enabled, it adds the
samples in 32 bits, divides by two with rounding toward zero and writes the
result to both channels. It processes the valid frames in the current 4 KiB
buffer. File access and UI notifications run in the Settings path.

## Settings and persistence

The menu row, preview, controller capability query and inline value use the
native Settings interfaces. Mono Audio and Appearance can each be built alone
or together. Their preferences use separate files. Mono Audio reads
`iPod_Control/Device/iOPMonoAudio` during preference loading. Its 12-byte record
contains the format tag, the On/Off value and its complement. A missing, short
or invalid record selects Off. A toggle takes effect after save and readback.
On a failed save the row shows **Not saved** and playback keeps its current mode.

## Qualification

The firmware lab's `scripts/probe_classic_mono_audio.py` accepts a build output
directory and executes its ARM instructions in Unicorn. The probe exercises
the actual route selection, callback setters, ring-buffer reader, final mixer
and the digital packet descriptor offsets. The filesystem, active voice source,
driver initialization and scheduling have test substitutes.

The release and a mono-only build passed left-only, right-only, opposite-polarity,
both full-scale extremes, silence, short and empty refills, and a sound injected
by the last mixer voice. The test changes drivers with the preference set, then
turns it off and checks stereo byte-for-byte. It also reloads the saved value,
rejects corrupt records and checks the failed-write indication. The complete
release installed 117 resources in the native resource probe. Two builds with
Arm GNU 13.3.Rel1 produced the same 101,871,616-byte firmware image, SHA-256
`d2e34211ab0934c33775ae3dd1d6c12407013e85b0f63728b3d44f8cc60b8526`.

Physical acceptance remains open. With a track that alternates left-only and
right-only signals, both passages should be audible on either channel with
Mono Audio On. Check the headphone jack, analog dock line-out and a USB audio
dock, including a route change during playback and a restart. Off should restore
the track's original channel separation.

## Settings preview in 0.12.2-dev

The Mono Audio preview uses a 78 × 121 native coverage mask showing two
channels joining at a single speaker. The Settings layout binds its image
child to this mask in both switch positions. Its separate text child shows
the preference value. See the [preview verification](classic-mod-menu-2026-11-17.md#blank-gear-on-hardware-in-0121-dev).
