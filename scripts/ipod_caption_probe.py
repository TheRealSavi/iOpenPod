#!/usr/bin/env python3
"""Generate and optionally install iPod subtitle/caption probe videos.

The generated files are intentionally tiny and plainly titled.  Run without
``--install`` to create local samples and ffprobe reports only.  Run with
``--install`` to add the samples to a mounted iPod through SyncExecutor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from iopenpod.device import identify_ipod_at_path, set_current_device
from iopenpod.infrastructure.media_folders import MEDIA_TYPE_VIDEO
from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan, SyncRequest
from iopenpod.sync.mapping import MappingManager
from iopenpod.sync.pc_library import PCLibrary
from iopenpod.sync.sync_executor import SyncExecutor
from iopenpod.sync.transcoder import resolve_transcode_plan

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CommandResult:
    name: str
    ok: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""


@dataclass
class Variant:
    key: str
    title: str
    path: str
    expected: str
    generated: bool
    probe: dict[str, Any] | None = None
    commands: list[CommandResult] = field(default_factory=list)
    installed_path: str = ""
    installed_probe: dict[str, Any] | None = None


def run_cmd(name: str, cmd: list[str], *, cwd: Path) -> CommandResult:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(
        name=name,
        ok=proc.returncode == 0,
        command=cmd,
        stdout=proc.stdout[-4000:],
        stderr=proc.stderr[-4000:],
    )


def ffprobe(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    proc = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr[-4000:]}
    return json.loads(proc.stdout or "{}")


def write_text_inputs(workdir: Path) -> dict[str, Path]:
    utf8_srt = workdir / "probe_utf8.srt"
    mac_srt = workdir / "probe_macroman.srt"
    scc = workdir / "probe_608.scc"

    srt_text = (
        "1\n"
        "00:00:01,000 --> 00:00:03,500\n"
        "UTF-8 subtitle: cafe, resume, facade\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:07,500\n"
        "Accents: Caf\\u00e9, r\\u00e9sum\\u00e9, \\u00a3 sign\n\n"
        "3\n"
        "00:00:08,000 --> 00:00:11,000\n"
        "Final line: if you see this, soft subtitles rendered.\n"
    )
    utf8_srt.write_text(srt_text.encode("ascii").decode("unicode_escape"), encoding="utf-8")
    mac_srt.write_bytes(srt_text.encode("ascii").decode("unicode_escape").encode("mac_roman"))

    # A minimal, visible CEA-608 pop-on caption: "Hello World" at 00:00:01.
    # Keep this as an SCC source because FFmpeg does not encode SRT directly
    # to CEA-608.  It lets the probe distinguish MOV c608 muxing from iPod
    # M4V muxing without relying on a copyrighted media sample.
    scc.write_text(
        "Scenarist_SCC V1.0\n\n"
        "00:00:01:00\t9420 9420 94ae 94ae 94e0 94e0 "
        "c845 4c4c 4f20 574f 524c c480 942f 942f\n\n"
        "00:00:04:00\t942c 942c\n",
        encoding="ascii",
    )

    # A CEA-608 ``cdat`` sample must carry a byte pair for every video frame.
    # The compact source above puts all the visible control/text pairs in one
    # three-second sample, which FFmpeg can decode but hardware caption
    # renderers need not accept.  This source emits the same pop-on caption at
    # the nominal 29.97 fps CEA-608 cadence, with explicit null pairs between
    # caption commands.
    cadence_scc = workdir / "probe_608_frame_cadence.scc"
    caption_pairs = [
        "9420", "9420",  # resume caption loading
        "94ae", "94ae",  # select CC1
        "94e0", "94e0",  # PAC: row 15
        "c845", "4c4c", "4f20", "574f", "524c", "c480",  # HELLO WORLD
        "942f", "942f",  # end of caption / display memory
    ]
    cadence_lines = ["Scenarist_SCC V1.0", ""]
    for frame in range(90):
        second = 1 + frame // 30
        frame_in_second = frame % 30
        pair = caption_pairs[frame] if frame < len(caption_pairs) else "8080"
        cadence_lines.append(f"00:00:{second:02}:{frame_in_second:02}\t{pair}")
    # Erase the display at four seconds.  CEA-608 control codes are repeated
    # deliberately; decoders use the second copy to avoid acting on noise.
    cadence_lines.extend(["00:00:04:00\t942c", "00:00:04:01\t942c", ""])
    cadence_scc.write_text("\n".join(cadence_lines), encoding="ascii")
    return {
        "utf8_srt": utf8_srt,
        "mac_srt": mac_srt,
        "scc": scc,
        "cadence_scc": cadence_scc,
    }


def make_base(workdir: Path) -> tuple[Path, CommandResult]:
    base = workdir / "caption_probe_base.m4v"
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "1.3",
        "-pix_fmt", "yuv420p",
        "-b:v", "450k",
        "-maxrate", "700k",
        "-bufsize", "1400k",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",
        "-ar", "44100",
        "-metadata", "title=CAPTION PROBE 00 Base Control",
        "-metadata", "artist=iOpenPod Probe",
        "-metadata", "album=iOpenPod Caption Probe",
        "-movflags", "+faststart",
        "-f", "ipod",
        str(base),
    ]
    return base, run_cmd("base", cmd, cwd=workdir)


def make_2997_base(workdir: Path) -> tuple[Path, CommandResult]:
    """Make a source whose frame cadence matches the CEA-608 clock."""
    base = workdir / "caption_probe_2997_base.m4v"
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30000/1001:duration=12",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "1.3",
        "-pix_fmt", "yuv420p",
        "-b:v", "450k",
        "-maxrate", "700k",
        "-bufsize", "1400k",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",
        "-ar", "44100",
        "-metadata", "title=CAPTION PROBE 16 CEA-608 frame cadence",
        "-metadata", "artist=iOpenPod Probe",
        "-metadata", "album=iOpenPod Caption Probe",
        "-movflags", "+faststart",
        "-f", "ipod",
        str(base),
    ]
    return base, run_cmd("16_base_2997", cmd, cwd=workdir)


def make_variant(
    workdir: Path,
    key: str,
    title: str,
    expected: str,
    cmd: list[str],
) -> Variant:
    result = run_cmd(key, cmd, cwd=workdir)
    path = Path(cmd[-1])
    if not path.is_absolute():
        path = workdir / path
    return Variant(
        key=key,
        title=title,
        path=str(path),
        expected=expected,
        generated=result.ok and path.exists(),
        probe=ffprobe(path),
        commands=[result],
    )


def inject_a53_caption(
    source: Path,
    destination: Path,
    *,
    frame_number: int,
) -> CommandResult:
    """Inject one valid CEA-608 A/53 payload before a H.264 video frame."""
    command = ["embed-a53-caption", str(source), str(destination)]
    caption_pairs = [
        bytes.fromhex(pair)
        for pair in (
            "9420", "9420", "94ae", "94ae", "94e0", "94e0",
            "c845", "4c4c", "4f20", "574f", "524c", "c480",
            "942f", "942f",
        )
    ]
    return inject_a53_caption_events(
        source,
        destination,
        events={frame_number: caption_pairs},
        command=command,
    )


def inject_a53_caption_events(
    source: Path,
    destination: Path,
    *,
    events: dict[int, list[bytes]],
    command: list[str],
) -> CommandResult:
    """Inject valid A/53 CEA-608 packets at specific H.264 frame numbers."""
    try:
        raw = source.read_bytes()
        start_codes: list[tuple[int, int]] = []
        offset = 0
        while offset + 3 < len(raw):
            marker_size = (
                4 if raw[offset:offset + 4] == b"\0\0\0\1"
                else 3 if raw[offset:offset + 3] == b"\0\0\1" else 0
            )
            if marker_size:
                start_codes.append((offset, marker_size))
                offset += marker_size
            else:
                offset += 1

        output = bytearray()
        video_frames = 0
        injected_frames: set[int] = set()
        for number, (nal_offset, marker_size) in enumerate(start_codes):
            nal_end = start_codes[number + 1][0] if number + 1 < len(start_codes) else len(raw)
            nal = raw[nal_offset:nal_end]
            nal_type = nal[marker_size] & 0x1F
            if nal_type in {1, 5}:
                video_frames += 1
            if nal_type in {1, 5} and video_frames in events:
                pairs = events[video_frames]
                if not 1 <= len(pairs) <= 31 or any(len(pair) != 2 for pair in pairs):
                    raise RuntimeError(f"invalid A/53 CEA-608 packet at frame {video_frames}")
                # Registered A/53/GA94 user data: every cc_data triplet is a
                # valid field-1 CEA-608 pair.  A hardware decoder sees one
                # such SEI on every video frame, rather than a burst in one.
                triplets = b"".join(b"\xfc" + pair for pair in pairs)
                payload = (
                    b"\xb5\x00\x31GA94\x03"
                    + bytes([0x40 | len(pairs), 0x00])
                    + triplets
                    + b"\xff"
                )
                if len(payload) >= 255:
                    raise RuntimeError("A/53 SEI payload unexpectedly exceeds one-byte length")
                sei = b"\0\0\0\1\x06" + bytes([4, len(payload)]) + payload + b"\x80"
                output += sei
                injected_frames.add(video_frames)
            output += nal
        missing_frames = sorted(set(events) - injected_frames)
        if missing_frames:
            raise RuntimeError(f"could not find H.264 video frames {missing_frames}")
        destination.write_bytes(output)
        return CommandResult(name=command[0], ok=True, command=command)
    except OSError as exc:
        return CommandResult(name=command[0], ok=False, command=command, stderr=str(exc))
    except RuntimeError as exc:
        return CommandResult(name=command[0], ok=False, command=command, stderr=str(exc))


def generate(workdir: Path) -> list[Variant]:
    workdir.mkdir(parents=True, exist_ok=True)
    inputs = write_text_inputs(workdir)
    base, base_result = make_base(workdir)
    variants: list[Variant] = [
        Variant(
            key="00_base_control",
            title="CAPTION PROBE 00 Base Control",
            path=str(base),
            expected="No subtitle stream; confirms video/audio baseline playback.",
            generated=base_result.ok and base.exists(),
            probe=ffprobe(base),
            commands=[base_result],
        )
    ]
    if not base.exists():
        return variants

    variants.append(make_variant(
        workdir,
        "01_mov_text_utf8",
        "CAPTION PROBE 01 mov_text UTF-8",
        "Soft subtitle track from UTF-8 SRT, encoded as MP4 tx3g/mov_text.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(inputs["utf8_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
            "-metadata", "title=CAPTION PROBE 01 mov_text UTF-8",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mp4",
            "caption_probe_01_mov_text_utf8.m4v",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "02_mov_text_macroman",
        "CAPTION PROBE 02 mov_text MacRoman",
        "Soft subtitle track from MacRoman SRT via ffmpeg -sub_charenc macintosh.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-sub_charenc", "macintosh",
            "-i", str(inputs["mac_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
            "-metadata", "title=CAPTION PROBE 02 mov_text MacRoman",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mp4",
            "caption_probe_02_mov_text_macroman.m4v",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "03_mov_text_forced",
        "CAPTION PROBE 03 mov_text Forced",
        "Soft subtitle track marked forced and default.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(inputs["utf8_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
            "-metadata", "title=CAPTION PROBE 03 mov_text Forced",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default+forced",
            "-movflags", "+faststart",
            "-f", "mp4",
            "caption_probe_03_mov_text_forced.m4v",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "04_dual_audio_mov_text",
        "CAPTION PROBE 04 Dual Audio + Subs",
        "Two AAC audio tracks plus one mov_text subtitle track.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-f", "lavfi", "-i", "sine=frequency=880:duration=12",
            "-i", str(inputs["utf8_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:a:0", "-map", "2:0",
            "-c:v", "copy",
            "-c:a:0", "copy",
            "-c:a:1", "aac", "-b:a:1", "128k", "-ac:a:1", "2", "-ar:a:1", "44100",
            "-c:s", "mov_text",
            "-metadata", "title=CAPTION PROBE 04 Dual Audio + Subs",
            "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:1", "language=jpn",
            "-metadata:s:s:0", "language=eng",
            "-disposition:a:0", "default",
            "-disposition:a:1", "0",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mp4",
            "caption_probe_04_dual_audio_mov_text.m4v",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "05_burned_in",
        "CAPTION PROBE 05 Burned In",
        "SRT burned into the video image; should show if the video plays at all.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-vf", f"subtitles={inputs['utf8_srt'].name}",
            "-c:v", "libx264",
            "-profile:v", "baseline",
            "-level", "1.3",
            "-pix_fmt", "yuv420p",
            "-b:v", "450k",
            "-maxrate", "700k",
            "-bufsize", "1400k",
            "-c:a", "copy",
            "-metadata", "title=CAPTION PROBE 05 Burned In",
            "-movflags", "+faststart",
            "-f", "ipod",
            "caption_probe_05_burned_in.m4v",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "06_mkv_transcode_source",
        "CAPTION PROBE 06 MKV Transcode Source",
        "Non-native MKV with SRT; iOpenPod transcode path is expected to drop subtitle streams.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(inputs["utf8_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "srt",
            "-metadata", "title=CAPTION PROBE 06 MKV Transcode Source",
            "caption_probe_06_mkv_transcode_source.mkv",
        ],
    ))

    scc_convert = run_cmd(
        "07_scc_from_srt",
        ["ffmpeg", "-hide_banner", "-y", "-i", str(inputs["utf8_srt"]), "probe_from_srt.scc"],
        cwd=workdir,
    )
    scc_path = workdir / "probe_from_srt.scc"
    scc_cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(base),
        "-i", str(scc_path if scc_path.exists() else inputs["scc"]),
        "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
        "-c:v", "copy", "-c:a", "copy", "-c:s", "copy",
        "-metadata", "title=CAPTION PROBE 07 SCC Attempt",
        "-movflags", "+faststart",
        "-f", "mp4",
        "caption_probe_07_scc_attempt.m4v",
    ]
    scc_variant = make_variant(
        workdir,
        "07_scc_attempt",
        "CAPTION PROBE 07 SCC Attempt",
        "Attempt to carry SCC/CEA-608-like captions into MP4. Failure is expected on many ffmpeg builds.",
        scc_cmd,
    )
    scc_variant.commands.insert(0, scc_convert)
    variants.append(scc_variant)
    variants.append(make_variant(
        workdir,
        "08_c608_mov",
        "CAPTION PROBE 08 CEA-608 MOV",
        "QuickTime MOV with a CEA-608 c608 caption track. This is the "
        "workaround for FFmpeg's iPod M4V muxer, and requires device playback "
        "verification before being treated as supported.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(scc_path if scc_path.exists() else inputs["scc"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "copy",
            "-metadata", "title=CAPTION PROBE 08 CEA-608 MOV",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mov",
            "caption_probe_08_c608.mov",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "09_c608_audio_transcode",
        "CAPTION PROBE 09 CEA-608 Audio Transcode",
        "CEA-608 MOV with incompatible AC-3 audio. iOpenPod must preserve "
        "c608 while transcoding only audio, and write MOV output.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(scc_path if scc_path.exists() else inputs["scc"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy",
            "-c:a", "ac3", "-b:a", "192k", "-ac", "2", "-ar", "48000",
            "-c:s", "copy",
            "-metadata", "title=CAPTION PROBE 09 CEA-608 Audio Transcode",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mov",
            "caption_probe_09_c608_audio_transcode.mov",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "10_c608_video_transcode",
        "CAPTION PROBE 10 CEA-608 Video Transcode",
        "CEA-608 MOV with incompatible MPEG-4 Part 2 video. iOpenPod must "
        "preserve c608 while transcoding only video, and write MOV output.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(scc_path if scc_path.exists() else inputs["scc"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "mpeg4", "-b:v", "500k",
            "-c:a", "copy", "-c:s", "copy",
            "-metadata", "title=CAPTION PROBE 10 CEA-608 Video Transcode",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mov",
            "caption_probe_10_c608_video_transcode.mov",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "11_mov_text_ipod",
        "CAPTION PROBE 11 mov_text iPod M4V",
        "TX3G subtitle track written through FFmpeg's iPod M4V muxer, "
        "including its H.264 UUID marker.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(inputs["utf8_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
            "-metadata", "title=CAPTION PROBE 11 mov_text iPod M4V",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "ipod",
            "caption_probe_11_mov_text_ipod.m4v",
        ],
    ))
    variants.append(make_variant(
        workdir,
        "12_mov_text_640x54",
        "CAPTION PROBE 12 mov_text 640x54",
        "TX3G subtitle track written through FFmpeg's iPod M4V muxer with "
        "the 640x54 subtitle rectangle used by the known-good iTunes file.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(inputs["utf8_srt"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
            "-s:s", "640x54",
            "-metadata", "title=CAPTION PROBE 12 mov_text 640x54",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "ipod",
            "caption_probe_12_mov_text_640x54.m4v",
        ],
    ))

    # FFmpeg's MOV muxer writes a standalone c608 track, but no relationship
    # from the video presentation track to that caption track.  QuickTime's
    # ``cdsc`` reference makes that association explicit: video track ID 1
    # describes caption track ID 3.  Build it as a separate probe rather than
    # changing the working TX3G path or assuming it makes CEA-608 supported.
    c608_cdsc_source = make_variant(
        workdir,
        "13_c608_cdsc_source",
        "CAPTION PROBE 13 CEA-608 cdsc",
        "Intermediate CEA-608 MOV before its QuickTime cdsc reference is added.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-i", str(scc_path if scc_path.exists() else inputs["scc"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "copy",
            "-metadata", "title=CAPTION PROBE 13 CEA-608 cdsc",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mov",
            "caption_probe_13_c608_cdsc_source.mov",
        ],
    )
    c608_cdsc_atom = workdir / "caption_probe_cdsc.atom"
    c608_cdsc_atom.write_bytes(bytes.fromhex("00000014747265660000000c6364736300000003"))
    c608_cdsc_path = workdir / "caption_probe_13_c608_cdsc.mov"
    c608_cdsc_edit = run_cmd(
        "13_c608_cdsc",
        [
            "mp4edit",
            "--insert", f"moov/trak[0]:{c608_cdsc_atom}",
            str(c608_cdsc_source.path),
            str(c608_cdsc_path),
        ],
        cwd=workdir,
    )
    variants.append(Variant(
        key="13_c608_cdsc",
        title="CAPTION PROBE 13 CEA-608 cdsc",
        path=str(c608_cdsc_path),
        expected=(
            "CEA-608 MOV with a QuickTime cdsc reference from the video to "
            "the caption track. With Captions on, Hello World should display."
        ),
        generated=c608_cdsc_source.generated and c608_cdsc_edit.ok and c608_cdsc_path.exists(),
        probe=ffprobe(c608_cdsc_path),
        commands=[*c608_cdsc_source.commands, c608_cdsc_edit],
    ))

    # A CEA-608 sample entry must live in a ``clcp`` media track.  FFmpeg
    # creates that handler and writes the required ``cdat`` sample atoms, but
    # does not add the movie-level association from the video to that track.
    # ``cdsc`` (probe 13) is a generic descriptive-characteristics reference;
    # QuickTime's closed-caption specification instead requires ``clcp``.
    c608_clcp_atom = workdir / "caption_probe_clcp.atom"
    c608_clcp_atom.write_bytes(bytes.fromhex("00000014747265660000000c636c637000000003"))
    c608_clcp_path = workdir / "caption_probe_15_c608_clcp.mov"
    c608_clcp_edit = run_cmd(
        "15_c608_clcp",
        [
            "mp4edit",
            "--insert", f"moov/trak[0]:{c608_clcp_atom}",
            str(c608_cdsc_source.path),
            str(c608_clcp_path),
        ],
        cwd=workdir,
    )
    variants.append(Variant(
        key="15_c608_clcp",
        title="CAPTION PROBE 15 CEA-608 clcp",
        path=str(c608_clcp_path),
        expected=(
            "CEA-608 QuickTime closed-caption track with the required clcp "
            "reference from the video. With Captions on, HELLO WORLD should display."
        ),
        generated=c608_cdsc_source.generated and c608_clcp_edit.ok and c608_clcp_path.exists(),
        probe=ffprobe(c608_clcp_path),
        commands=[*c608_cdsc_source.commands, c608_clcp_edit],
    ))

    # Unlike probes 08/13/15, this track contains one CEA-608 pair for every
    # 29.97 fps video frame.  The QuickTime specification defines ``cdat`` in
    # terms of per-frame pairs; hardware decoders may reject FFmpeg's compact
    # three-second samples even though FFmpeg itself can decode them.
    cadence_base, cadence_base_result = make_2997_base(workdir)
    cadence_source = make_variant(
        workdir,
        "16_c608_frame_cadence_source",
        "CAPTION PROBE 16 CEA-608 frame cadence",
        "Intermediate 29.97 fps CEA-608 MOV with one caption pair per frame.",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(cadence_base),
            "-i", str(inputs["cadence_scc"]),
            "-map", "0:v:0", "-map", "0:a:0", "-map", "1:0",
            "-c:v", "copy", "-c:a", "copy", "-c:s", "copy",
            "-metadata", "title=CAPTION PROBE 16 CEA-608 frame cadence",
            "-metadata:s:s:0", "language=eng",
            "-disposition:s:0", "default",
            "-movflags", "+faststart",
            "-f", "mov",
            "caption_probe_16_c608_frame_cadence_source.mov",
        ],
    )
    cadence_path = workdir / "caption_probe_16_c608_frame_cadence.mov"
    cadence_edit = run_cmd(
        "16_c608_frame_cadence_clcp",
        [
            "mp4edit",
            "--insert", f"moov/trak[0]:{c608_clcp_atom}",
            str(cadence_source.path),
            str(cadence_path),
        ],
        cwd=workdir,
    )
    variants.append(Variant(
        key="16_c608_frame_cadence",
        title="CAPTION PROBE 16 CEA-608 frame cadence",
        path=str(cadence_path),
        expected=(
            "CEA-608 QuickTime closed-caption track at 29.97 fps with one "
            "cdat pair per video frame and the required clcp reference. With "
            "Captions on, HELLO WORLD should display from roughly 1 to 4 seconds."
        ),
        generated=(
            cadence_base_result.ok
            and cadence_source.generated
            and cadence_edit.ok
            and cadence_path.exists()
        ),
        probe=ffprobe(cadence_path),
        commands=[cadence_base_result, *cadence_source.commands, cadence_edit],
    ))

    a53_annex_b = workdir / "caption_probe_14_a53.h264"
    a53_extract = run_cmd(
        "14_a53_extract",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(base),
            "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_mp4toannexb",
            "-an", str(a53_annex_b),
        ],
        cwd=workdir,
    )
    a53_injected = workdir / "caption_probe_14_a53_injected.h264"
    a53_inject = inject_a53_caption(a53_annex_b, a53_injected, frame_number=25)
    a53_output = workdir / "caption_probe_14_a53.m4v"
    a53_remux = run_cmd(
        "14_a53_remux",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-r", "24", "-i", str(a53_injected), "-i", str(base),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-map_metadata", "-1",
            "-metadata", "title=CAPTION PROBE 14 A53 H264",
            "-movflags", "+faststart", "-f", "ipod", str(a53_output),
        ],
        cwd=workdir,
    )
    variants.append(Variant(
        key="14_a53_h264",
        title="CAPTION PROBE 14 A53 H264",
        path=str(a53_output),
        expected=(
            "CEA-608 carried in H.264 A/53 video user data, not as a c608 "
            "track. With Captions on, HELLO WORLD should display."
        ),
        generated=a53_extract.ok and a53_inject.ok and a53_remux.ok and a53_output.exists(),
        probe=ffprobe(a53_output),
        commands=[a53_extract, a53_inject, a53_remux],
    ))

    # A/53 closed captions are part of the H.264 elementary stream, not a
    # standalone track.  Probe 14 placed every caption pair in one SEI; this
    # variant emits one valid pair on each 29.97 fps frame from 1 to 4 seconds,
    # which is how CEA-608 data reaches broadcast-style hardware decoders.
    a53_cadence_annex_b = workdir / "caption_probe_21_a53_cadence.h264"
    a53_cadence_extract = run_cmd(
        "21_a53_cadence_extract",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(cadence_base),
            "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "h264_mp4toannexb",
            "-an", str(a53_cadence_annex_b),
        ],
        cwd=workdir,
    )
    a53_cadence_injected = workdir / "caption_probe_21_a53_cadence_injected.h264"
    a53_pairs = [
        bytes.fromhex(pair)
        for pair in (
            "9420", "9420", "94ae", "94ae", "94e0", "94e0",
            "c845", "4c4c", "4f20", "574f", "524c", "c480",
            "942f", "942f",
        )
    ]
    a53_events = {
        30 + index: [pair]
        for index, pair in enumerate(a53_pairs)
    }
    a53_events.update({frame: [b"\x80\x80"] for frame in range(44, 120)})
    a53_events[120] = [bytes.fromhex("942c")]
    a53_events[121] = [bytes.fromhex("942c")]
    a53_cadence_inject = inject_a53_caption_events(
        a53_cadence_annex_b,
        a53_cadence_injected,
        events=a53_events,
        command=["21_a53_cadence_inject", str(a53_cadence_annex_b), str(a53_cadence_injected)],
    )
    a53_cadence_output = workdir / "caption_probe_21_a53_frame_cadence.m4v"
    a53_cadence_remux = run_cmd(
        "21_a53_cadence_remux",
        [
            "ffmpeg", "-hide_banner", "-y",
            "-r", "30000/1001", "-i", str(a53_cadence_injected), "-i", str(cadence_base),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-map_metadata", "-1",
            "-metadata", "title=CAPTION PROBE 21 A53 frame cadence",
            "-movflags", "+faststart", "-f", "ipod", str(a53_cadence_output),
        ],
        cwd=workdir,
    )
    variants.append(Variant(
        key="21_a53_frame_cadence",
        title="CAPTION PROBE 21 A53 frame cadence",
        path=str(a53_cadence_output),
        expected=(
            "CEA-608 in H.264 A/53 user data at 29.97 fps. With Captions on, "
            "HELLO WORLD should display from roughly 1.4 to 4 seconds."
        ),
        generated=(
            a53_cadence_extract.ok
            and a53_cadence_inject.ok
            and a53_cadence_remux.ok
            and a53_cadence_output.exists()
        ),
        probe=ffprobe(a53_cadence_output),
        commands=[a53_cadence_extract, a53_cadence_inject, a53_cadence_remux],
    ))
    return variants


def backup_device(ipod: Path, workdir: Path) -> list[str]:
    backup_dir = workdir / "device_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for rel in (
        "iPod_Control/iTunes/iTunesDB",
        "iPod_Control/iTunes/iTunesCDB",
        "iPod_Control/iTunes/iOpenPod.json",
    ):
        src = ipod / rel
        if not src.exists():
            continue
        dst = backup_dir / Path(rel).name
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def _probe_metadata_changes(track: Any, ipod_track: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Return the small set of probe fields that should match its source."""
    fields = (
        ("title", "Title"),
        ("artist", "Artist"),
        ("album", "Album"),
        ("album_artist", "Album Artist"),
        ("duration_ms", "length"),
    )
    changes: dict[str, tuple[Any, Any]] = {}
    for pc_field, ipod_field in fields:
        new_value = getattr(track, pc_field, None)
        old_value = ipod_track.get(ipod_field)
        if new_value not in (None, "", 0) and new_value != old_value:
            changes[pc_field] = (new_value, old_value)
    return changes


def install(ipod: Path, workdir: Path, variants: list[Variant]) -> dict[str, Any]:
    device = identify_ipod_at_path(str(ipod))
    if device is None:
        raise RuntimeError(f"Could not identify iPod at {ipod}")
    set_current_device(device)

    generated = [
        Path(v.path)
        for v in variants
        if v.generated and Path(v.path).suffix.lower() in {".m4v", ".mp4", ".mkv", ".mov"}
    ]
    installable = [
        path for path in generated
        if path.name != "caption_probe_base.m4v" or path.exists()
    ]
    library = PCLibrary({
        "directory": str(workdir),
        "recurse": False,
        "media_types": [MEDIA_TYPE_VIDEO],
    })
    scanned = {
        Path(track.path).resolve(): track
        for track in library.scan(include_video=True)
    }
    variants_by_path = {Path(variant.path).resolve(): variant for variant in variants}

    mapping_manager = MappingManager(ipod)
    mapping = mapping_manager.load()
    from iopenpod.sync._db_io import read_existing_database

    database = read_existing_database(ipod)
    tracks_by_db_id = {
        int(track["db_track_id"]): track
        for track in database.get("tracks", [])
        if track.get("db_track_id")
    }
    existing_by_source = {
        entry.source_path_hint: (fingerprint, entry)
        for fingerprint, entry in mapping.all_entries()
        if entry.source_path_hint
    }

    plan = SyncPlan()
    for path in installable:
        track = scanned.get(path.resolve())
        if track is None:
            continue
        # The probe's visible label is part of the experiment.  Some derived
        # MOV probes deliberately reuse a tagged intermediate source, so do
        # not let that intermediate title become the iTunesDB title.
        track.title = variants_by_path[path.resolve()].title
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        transcode_plan = resolve_transcode_plan(path)
        estimated_size = transcode_plan.estimate_output_size(
            source_size=track.size,
            duration_ms=track.duration_ms,
        )
        existing = existing_by_source.get(track.relative_path)
        if existing is None:
            plan.to_add.append(SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                fingerprint=f"caption-probe:{path.name}:{digest}",
                pc_track=track,
                estimated_size=estimated_size,
                transcode_plan=transcode_plan,
                description=track.title,
            ))
            plan.storage.bytes_to_add += estimated_size or track.size
            continue

        fingerprint, entry = existing
        ipod_track = tracks_by_db_id.get(entry.db_track_id, {})
        plan.to_update_file.append(SyncItem(
            action=SyncAction.UPDATE_FILE,
            fingerprint=fingerprint,
            pc_track=track,
            estimated_size=estimated_size,
            transcode_plan=transcode_plan,
            db_track_id=entry.db_track_id,
            ipod_track=ipod_track,
            description=f"Repair probe file: {track.title}",
        ))
        plan.storage.bytes_to_update += estimated_size or track.size
        metadata_changes = _probe_metadata_changes(track, ipod_track)
        if metadata_changes:
            plan.to_update_metadata.append(SyncItem(
                action=SyncAction.UPDATE_METADATA,
                fingerprint=fingerprint,
                pc_track=track,
                db_track_id=entry.db_track_id,
                ipod_track=ipod_track,
                metadata_changes=metadata_changes,
                description=f"Repair probe metadata: {track.title}",
            ))

    progress_rows: list[dict[str, Any]] = []

    def on_progress(progress: Any) -> None:
        progress_rows.append({
            "stage": getattr(progress, "stage", ""),
            "current": getattr(progress, "current", 0),
            "total": getattr(progress, "total", 0),
            "message": getattr(progress, "message", ""),
        })
        print(
            f"[sync] {getattr(progress, 'stage', '')} "
            f"{getattr(progress, 'current', 0)}/{getattr(progress, 'total', 0)} "
            f"{getattr(progress, 'message', '')}"
        )

    executor = SyncExecutor(ipod, max_workers=1, max_device_write_workers=1)
    outcome = executor.execute_request(
        SyncRequest(plan=plan, mapping=mapping, progress_callback=on_progress)
    )

    mapping_after = mapping_manager.load()
    installed_by_source: dict[str, str] = {}
    for item in [*plan.to_add, *plan.to_update_file]:
        if not item.fingerprint or not item.pc_track:
            continue
        entries = mapping_after.get_entries(item.fingerprint)
        if not entries:
            continue
        _ipod_track = None
        # We cannot derive the final file path from the mapping alone, so read
        # the executor's post-sync database records through the parsed DB.
        installed_by_source[item.pc_track.path] = str(entries[-1].db_track_id)

    return {
        "device": {
            "model_number": device.model_number,
            "model_family": device.model_family,
            "generation": device.generation,
            "firmware": device.firmware,
        },
        "planned": len(plan.to_add) + len(plan.to_update_file),
        "success": outcome.success,
        "errors": getattr(outcome, "errors", []),
        "tracks_added": getattr(outcome, "tracks_added", 0),
        "tracks_updated_file": getattr(outcome, "tracks_updated_file", 0),
        "tracks_updated_metadata": getattr(outcome, "tracks_updated_metadata", 0),
        "progress": progress_rows,
        "mapping_db_ids_by_source": installed_by_source,
    }


def attach_installed_probes(ipod: Path, variants: list[Variant]) -> None:
    try:
        from iopenpod.sync._db_io import read_existing_database
    except Exception:
        return
    try:
        data = read_existing_database(ipod)
    except Exception:
        return
    title_to_variant = {v.title.casefold(): v for v in variants}
    stem_to_variant = {
        Path(v.path).stem.casefold(): v
        for v in variants
    }
    for track in data.get("tracks", []):
        title = str(track.get("Title") or track.get("title") or "")
        variant = title_to_variant.get(title.casefold()) or stem_to_variant.get(title.casefold())
        if variant is None:
            continue
        location = str(track.get("Location") or track.get("location") or "")
        if not location:
            continue
        rel = location.lstrip(":").replace(":", "/")
        path = ipod / rel
        variant.installed_path = str(path)
        variant.installed_probe = ffprobe(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workdir",
        default=str(ROOT / "tmp" / "ipod_caption_probe"),
        help="Directory for generated samples and reports.",
    )
    parser.add_argument("--ipod", default="/Volumes/iPod")
    parser.add_argument("--install", action="store_true")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="PROBE_KEY",
        help="Generate/install only the named probe keys.",
    )
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    ipod = Path(args.ipod).expanduser().resolve()
    variants = generate(workdir)
    if args.only:
        requested = set(args.only)
        available = {variant.key for variant in variants}
        missing = sorted(requested - available)
        if missing:
            parser.error(f"Unknown probe key(s): {', '.join(missing)}")
        variants = [variant for variant in variants if variant.key in requested]
    report: dict[str, Any] = {
        "workdir": str(workdir),
        "ipod": str(ipod),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "variants": [asdict(v) for v in variants],
    }

    if args.install:
        report["device_backups"] = backup_device(ipod, workdir)
        report["install"] = install(ipod, workdir, variants)
        attach_installed_probes(ipod, variants)
        report["variants"] = [asdict(v) for v in variants]

    report_path = workdir / "caption_probe_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")
    for variant in variants:
        status = "ok" if variant.generated else "failed"
        print(f"{status:6} {variant.key:28} {variant.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
