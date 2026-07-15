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

    # Minimal SCC payload.  This is deliberately simple; ffmpeg will tell us
    # whether this build can convert or mux it into a playable MP4/MOV path.
    scc.write_text(
        "Scenarist_SCC V1.0\n\n"
        "00:00:01:00\t9420 94ae 94ae 9420 8080\n",
        encoding="ascii",
    )
    return {"utf8_srt": utf8_srt, "mac_srt": mac_srt, "scc": scc}


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


def install(ipod: Path, workdir: Path, variants: list[Variant]) -> dict[str, Any]:
    generated = [Path(v.path) for v in variants if v.generated and Path(v.path).suffix.lower() in {".m4v", ".mp4", ".mkv"}]
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

    plan = SyncPlan()
    for path in installable:
        track = scanned.get(path.resolve())
        if track is None:
            continue
        digest = hashlib.sha1(path.read_bytes()).hexdigest()
        transcode_plan = resolve_transcode_plan(path)
        plan.to_add.append(SyncItem(
            action=SyncAction.ADD_TO_IPOD,
            fingerprint=f"caption-probe:{path.name}:{digest}",
            pc_track=track,
            estimated_size=transcode_plan.estimate_output_size(
                source_size=track.size,
                duration_ms=track.duration_ms,
            ),
            transcode_plan=transcode_plan,
            description=track.title,
        ))
        plan.storage.bytes_to_add += plan.to_add[-1].estimated_size or track.size

    mapping_manager = MappingManager(ipod)
    mapping = mapping_manager.load()
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
    for item in plan.to_add:
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
        "planned": len(plan.to_add),
        "success": outcome.success,
        "errors": getattr(outcome, "errors", []),
        "tracks_added": getattr(outcome, "tracks_added", 0),
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
    title_to_variant = {v.title: v for v in variants}
    for track in data.get("tracks", []):
        title = str(track.get("Title") or track.get("title") or "")
        variant = title_to_variant.get(title)
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
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    ipod = Path(args.ipod).expanduser().resolve()
    variants = generate(workdir)
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
