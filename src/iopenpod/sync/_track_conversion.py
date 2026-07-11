"""Track conversion helpers — map between parsed dicts, PCTrack, and TrackInfo.

Extracted from sync_executor.py to keep the orchestrator focused on
flow control.  These are pure data-mapping functions with no side effects.
"""

from pathlib import Path

from iopenpod.itunesdb_shared.constants import (
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VIDEO_PODCAST,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo

# Filetype string → writer filetype code.  Checked in order; first
# substring match wins.  Falls back to "mp3".
_FILETYPE_MAP: list[tuple[str, str]] = [
    ("AAC", "m4a"), ("M4A", "m4a"), ("Lossless", "m4a"),
    ("Protected", "m4p"), ("Audiobook", "m4b"),
    ("WAV", "wav"), ("AIFF", "aiff"),
    ("M4V", "m4v"), ("MP4", "mp4"),
]


def track_dict_to_info(t: dict) -> TrackInfo:
    """Convert parsed track dict to TrackInfo for writing."""
    filetype = t.get("filetype", "MP3")
    filetype_code = "mp3"
    for needle, code in _FILETYPE_MAP:
        if needle in filetype:
            filetype_code = code
            break
    return TrackInfo(
        title=t.get("Title", "Unknown"),
        location=t.get("Location", ""),
        size=t.get("size", 0),
        length=t.get("length", 0),
        filetype=filetype_code,
        bitrate=t.get("bitrate", 0),
        sample_rate=t.get("sample_rate_1", 44100),
        vbr=bool(t.get("vbr_flag", 0)),
        artist=t.get("Artist"),
        album=t.get("Album"),
        album_artist=t.get("Album Artist"),
        genre=t.get("Genre"),
        composer=t.get("Composer"),
        comment=t.get("Comment"),
        grouping=t.get("Grouping"),
        year=t.get("year", 0),
        track_number=t.get("track_number", 0),
        total_tracks=t.get("total_tracks", 0),
        disc_number=t.get("disc_number", 1),
        total_discs=t.get("total_discs", 1),
        bpm=t.get("bpm", 0),
        compilation_flag=bool(t.get("compilation_flag", t.get("compilation", 0))),
        skip_when_shuffling=bool(t.get("skip_when_shuffling", 0)),
        remember_position=bool(t.get("remember_position", 0)),
        rating=t.get("rating", 0),
        # play_count_1 is the cumulative count (already includes any
        # Play Counts deltas folded into the DB or merged at load time).
        play_count=t.get("play_count_1", 0),
        play_count_2=t.get("play_count_2", t.get("recent_playcount", 0)),
        skip_count=t.get("skip_count", 0),
        volume=t.get("volume", 0),
        start_time=t.get("start_time", 0),
        stop_time=t.get("stop_time", 0),
        sound_check=t.get("sound_check", 0),
        bookmark_time=t.get("bookmark_time", 0),
        checked_flag=t.get("checked_flag", t.get("checked", 0)),
        gapless_data=t.get("gapless_audio_payload_size", 0),
        gapless_track_flag=t.get("gapless_track_flag", 0),
        gapless_album_flag=t.get("gapless_album_flag", 0),
        pregap=t.get("pregap", 0),
        postgap=t.get("postgap", 0),
        sample_count=t.get("sample_count", 0),
        encoder_flag=t.get("encoder", 0),
        explicit_flag=t.get("explicit_flag", 0),
        purchased_aac_flag=t.get("purchased_aac_flag", 0),
        has_lyrics=bool(t.get("lyrics_flag", 0)),
        lyrics=t.get("Lyrics"),
        eq_setting=t.get("eq_setting"),
        date_added=t.get("date_added", 0),
        date_released=t.get("date_released", 0),
        last_played=t.get("last_played", 0),
        last_skipped=t.get("last_skipped", 0),
        last_modified=t.get("last_modified", 0),
        date_added_to_itunes=t.get("date_added_to_itunes", 0),
        db_track_id=t.get("db_track_id", t.get("db_id", 0)),
        media_type=t.get("media_type", 1),
        movie_file_flag=t.get("movie_flag", 0),
        source_path=t.get("source_path") or t.get("Source Path"),
        source_relative_path=t.get("source_relative_path") or t.get("Source Relative Path"),
        season_number=t.get("season_number", 0),
        episode_number=t.get("episode_number", 0),
        artwork_count=t.get("artwork_count", 0),
        artwork_size=t.get("artwork_size", 0),
        mhii_link=t.get("artwork_id_ref", 0),
        sort_artist=t.get("Sort Artist"),
        sort_name=t.get("Sort Title") or t.get("Sort Name"),
        sort_album=t.get("Sort Album"),
        sort_album_artist=t.get("Sort Album Artist"),
        sort_composer=t.get("Sort Composer"),
        filetype_desc=t.get("filetype"),
        # Video string fields from parsed MHOD types
        show_name=t.get("Show"),
        episode_id=t.get("Episode"),
        description=t.get("Description Text"),
        subtitle=t.get("Subtitle"),
        network_name=t.get("TV Network"),
        sort_show=t.get("Sort Show"),
        show_locale=t.get("Show Locale"),
        keywords=t.get("Track Keywords"),
        # Podcast/audiobook fields from parsed track
        podcast_enclosure_url=t.get("Podcast Enclosure URL"),
        podcast_rss_url=t.get("Podcast RSS URL"),
        category=t.get("Category"),
        played_mark=t.get("not_played_flag", -1),
        podcast_flag=t.get("use_podcast_now_playing_flag", 0),
        # Round-trip fields (preserved from existing iPod database)
        user_id=t.get("user_id", 0),
        app_rating=t.get("app_rating", 0),
        mpeg_audio_type=t.get("mpeg_audio_type", t.get("unk144", 0)),
        store_track_id=t.get("store_track_id", 0),
        store_encoder_version=t.get("store_encoder_version", 0),
        store_artist_id=t.get("store_artist_id", 0),
        store_album_id=t.get("store_album_id", 0),
        store_content_flag=t.get("store_content_flag", 0),
        album_id=t.get("album_id", 0),
        artist_id=t.get("artist_id_ref", t.get("artist_id", 0)),
        composer_id=t.get("composer_id", 0),
        chapter_data=t.get("chapter_data"),
    )


def pc_track_to_info(
    pc_track,
    ipod_location: str,
    was_transcoded: bool,
    ipod_file_path: Path | None = None,
    existing_media_type: int | None = None,
    transcode_options=None,
) -> TrackInfo:
    """Convert PCTrack to TrackInfo for writing.

    Args:
        pc_track: Source track metadata from PC.
        ipod_location: iPod-style colon-separated path.
        was_transcoded: Whether the file was format-converted.
        ipod_file_path: Actual file on iPod (for accurate size after transcode).
        existing_media_type: If provided, preserve this media_type instead of
                            recalculating from pc_track.video_kind. Used for
                            UPDATE operations to preserve the original type.
    """
    ext = Path(ipod_location.replace(":", "/")).suffix.lower().lstrip(".")
    if ext in ("m4a", "aac", "alac"):
        filetype = "m4a"
    elif ext == "mp3":
        filetype = "mp3"
    else:
        filetype = ext

    # Rating: PCTrack already stores 0-100 (stars × 20), same as iPod
    rating = pc_track.rating or 0

    # File size: use actual iPod file size (especially important after transcode)
    if ipod_file_path and ipod_file_path.exists():
        file_size = ipod_file_path.stat().st_size
    else:
        file_size = pc_track.size or 0

    # Bitrate/sample_rate: use source values for direct copies,
    # but for transcodes we should probe the actual file.
    # As a practical default, use AAC 256kbps for transcoded AAC.
    bitrate = pc_track.bitrate or 0
    sample_rate = pc_track.sample_rate or 44100
    if was_transcoded:
        # Lossless sources (.flac, .wav, .aif, .aiff) transcode to ALAC —
        # keep the source bitrate.  Lossy sources (.ogg, .opus, .wma) go
        # to AAC — use the user-configured bitrate.
        source_ext = pc_track.extension.lower().lstrip(".")
        is_lossless_source = source_ext in ("flac", "wav", "aif", "aiff")
        if filetype == "m4a" and not is_lossless_source:
            from .transcoder import quality_to_nominal_bitrate, resolve_transcode_plan
            plan = resolve_transcode_plan(pc_track.path)
            bitrate = quality_to_nominal_bitrate(plan.effective_quality)
        # Transcoded audio is capped at IPOD_MAX_SAMPLE_RATE; reflect that
        # in the stored sample_rate so iTunesDB is consistent with the file.
        if filetype == "m4a":
            from .transcoder import IPOD_MAX_SAMPLE_RATE as _MAX_SR
            sample_rate = min(sample_rate, _MAX_SR)

    # ── Media type auto-detection ────────────────────────────────
    # If an existing media_type is provided (for UPDATE operations), preserve it
    # instead of recalculating from the current file's video_kind metadata.
    # This prevents media_type from changing due to missing/inconsistent stik atoms.
    if existing_media_type is not None:
        media_type = existing_media_type
        # Derive flags from the preserved media_type
        movie_file_flag = 1 if existing_media_type & (MEDIA_TYPE_VIDEO | MEDIA_TYPE_MUSIC_VIDEO | MEDIA_TYPE_TV_SHOW | MEDIA_TYPE_VIDEO_PODCAST) else 0
        podcast_flag = 1 if existing_media_type & (MEDIA_TYPE_PODCAST | MEDIA_TYPE_VIDEO_PODCAST) else 0
        skip_when_shuffling = bool(existing_media_type & (MEDIA_TYPE_PODCAST | MEDIA_TYPE_AUDIOBOOK | MEDIA_TYPE_VIDEO_PODCAST))
        remember_position = bool(existing_media_type & (MEDIA_TYPE_PODCAST | MEDIA_TYPE_AUDIOBOOK | MEDIA_TYPE_VIDEO_PODCAST))
    else:
        # Normal auto-detection from PC track metadata
        is_video = pc_track.is_video
        video_kind = pc_track.video_kind or ""
        is_podcast = pc_track.is_podcast
        is_audiobook = pc_track.is_audiobook
        movie_file_flag = 0
        media_type = MEDIA_TYPE_AUDIO
        podcast_flag = 0
        skip_when_shuffling = False
        remember_position = False

        if is_video:
            movie_file_flag = 1
            if is_podcast:
                media_type = MEDIA_TYPE_VIDEO_PODCAST
                podcast_flag = 1
                skip_when_shuffling = True
                remember_position = True
            elif video_kind == "tv_show":
                media_type = MEDIA_TYPE_TV_SHOW
            elif video_kind == "music_video":
                media_type = MEDIA_TYPE_MUSIC_VIDEO
            else:
                # Default to movie for generic video files
                media_type = MEDIA_TYPE_VIDEO
        elif is_podcast:
            media_type = MEDIA_TYPE_PODCAST
            podcast_flag = 1
            skip_when_shuffling = True
            remember_position = True
        elif is_audiobook:
            media_type = MEDIA_TYPE_AUDIOBOOK
            skip_when_shuffling = True
            remember_position = True

    # ── Encoding flags ───────────────────────────────────────────
    # For direct copies read flags from the source (mutagen was accurate).
    # For transcoded files derive them from the actual encoder used, because
    # the output format/VBR mode may differ completely from the source.
    if was_transcoded and transcode_options is not None:
        from .transcoder import resolve_effective_encoder
        _target, _actual_encoder = resolve_effective_encoder(transcode_options)
        _is_manual = (transcode_options.lossy_encoder or "auto").lower() not in {"auto", ""}
        if filetype == "mp3":
            # encoder_flag=1 tells the iPod to look for a LAME gapless header.
            # libshine doesn't write one, so set 0 to avoid false gapless probing.
            encoder_flag = 1 if _actual_encoder == "libmp3lame" else 0
            # VBR: libmp3lame auto mode uses -q:a (VBR); libshine is always CBR.
            if _actual_encoder == "libshine":
                vbr = False
            elif _is_manual:
                vbr = transcode_options.bitrate_mode == "vbr"
            else:
                vbr = True  # auto libmp3lame always uses -q:a VBR for music
        elif filetype == "m4a":
            encoder_flag = 0  # AAC/ALAC do not use LAME headers
            # libfdk_aac -vbr and aac_at -aac_at_mode vbr produce genuine VBR output.
            vbr = (
                _is_manual
                and _actual_encoder in {"libfdk_aac", "aac_at"}
                and transcode_options.bitrate_mode == "vbr"
            )
        else:
            encoder_flag = 0
            vbr = False
    elif was_transcoded:
        # Options not available (dry-run / legacy call). Use format-safe defaults.
        encoder_flag = 1 if filetype == "mp3" else 0
        vbr = False if filetype == "m4a" else pc_track.vbr
    else:
        # Direct copy — source flags are correct.
        encoder_flag = 1 if filetype == "mp3" else 0
        vbr = pc_track.vbr

    # ── Gapless & encoder flags ──────────────────────────────────
    pregap = pc_track.pregap or 0
    postgap = pc_track.postgap or 0
    sample_count = pc_track.sample_count or 0
    gapless_data = pc_track.gapless_data or 0
    if was_transcoded:
        # Prefer probing the actual output file — it gives us values at the
        # correct sample rate with no floating-point error, and for files
        # encoded by Apple's Core Audio (aac_at on macOS) we also get exact
        # pregap/postgap from the iTunSMPB atom.
        if ipod_file_path and ipod_file_path.exists():
            from .pc_library import probe_gapless_info
            probed = probe_gapless_info(ipod_file_path)
            if probed.get("sample_rate"):
                sample_rate = probed["sample_rate"]
            if probed.get("sample_count"):
                sample_count = probed["sample_count"]
                pregap = probed.get("pregap", 0)
                postgap = probed.get("postgap", 0)
        else:
            # Fallback: the output file isn't available yet (dry-run, etc.).
            # Scale source values to the output sample rate to avoid the
            # early-cutoff bug described in the transcoder fix.
            src_sr = pc_track.sample_rate or 44100
            if src_sr != sample_rate:
                ratio = sample_rate / src_sr
                if sample_count:
                    sample_count = round(sample_count * ratio)
                if pregap:
                    pregap = round(pregap * ratio)
                if postgap:
                    postgap = round(postgap * ratio)
    # Gapless playback flag is OFF by default.
    # Only enable it when explicitly provided by metadata/user intent.
    gapless_track_flag = pc_track.gapless_track_flag or 0

    return TrackInfo(
        title=pc_track.title or Path(pc_track.path).stem,
        location=ipod_location,
        size=file_size,
        length=pc_track.duration_ms or 0,
        filetype=filetype,
        bitrate=bitrate,
        sample_rate=sample_rate,
        vbr=vbr,
        artist=pc_track.artist,
        album=pc_track.album,
        album_artist=pc_track.album_artist,
        genre=pc_track.genre,
        composer=pc_track.composer,
        comment=pc_track.comment,
        grouping=pc_track.grouping,
        year=pc_track.year or 0,
        track_number=pc_track.track_number or 0,
        total_tracks=pc_track.track_total or 0,
        disc_number=pc_track.disc_number or 1,
        total_discs=pc_track.disc_total or 1,
        bpm=pc_track.bpm or 0,
        rating=rating,
        play_count=pc_track.play_count or 0,
        compilation_flag=pc_track.compilation,
        sound_check=pc_track.sound_check or 0,
        pregap=pregap,
        postgap=postgap,
        sample_count=sample_count,
        gapless_data=gapless_data,
        gapless_track_flag=gapless_track_flag,
        encoder_flag=encoder_flag,
        explicit_flag=pc_track.explicit_flag or 0,
        has_lyrics=pc_track.has_lyrics,
        lyrics=pc_track.lyrics,
        date_released=pc_track.date_released or 0,
        subtitle=pc_track.subtitle,
        sort_artist=pc_track.sort_artist,
        sort_name=pc_track.sort_name,
        sort_album=pc_track.sort_album,
        sort_album_artist=pc_track.sort_album_artist,
        sort_composer=pc_track.sort_composer,
        # Video fields
        media_type=media_type,
        movie_file_flag=movie_file_flag,
        source_path=pc_track.path,
        source_relative_path=pc_track.relative_path,
        season_number=pc_track.season_number or 0,
        episode_number=pc_track.episode_number or 0,
        show_name=pc_track.show_name,
        episode_id=pc_track.episode_id,
        description=pc_track.description,
        network_name=pc_track.network_name,
        sort_show=pc_track.sort_show,
        # Podcast/audiobook flags
        podcast_flag=podcast_flag,
        skip_when_shuffling=skip_when_shuffling,
        remember_position=remember_position,
        category=pc_track.category,
        podcast_rss_url=pc_track.podcast_url,
        podcast_enclosure_url=pc_track.podcast_enclosure_url,
        # iTunesDB chapters are DB-side and not limited to AAC/M4A files.
        chapter_data={"chapters": pc_track.chapters} if pc_track.chapters else None,
    )


def trackinfo_to_eval_dict(t: TrackInfo) -> dict:
    """Convert a TrackInfo to a dict the SPL evaluator can consume.

    The evaluator expects parsed-track-style dicts with keys matching
    the accessor maps in spl_evaluator.py.  We use db_track_id as the
    track_id so that spl_update() returns db_track_ids directly.
    """
    return {
        # Use db_track_id as track_id so evaluator returns db_track_ids.
        "track_id": t.db_track_id,
        # String fields
        "Title": t.title or "",
        "Album": t.album or "",
        "Artist": t.artist or "",
        "Genre": t.genre or "",
        "filetype": t.filetype_desc or t.filetype or "",
        "Comment": t.comment or "",
        "Composer": t.composer or "",
        "Album Artist": t.album_artist or "",
        "Sort Title": t.sort_name or "",
        "Sort Album": t.sort_album or "",
        "Sort Artist": t.sort_artist or "",
        "Sort Album Artist": t.sort_album_artist or "",
        "Sort Composer": t.sort_composer or "",
        "Grouping": t.grouping or "",
        # Integer fields
        "bitrate": t.bitrate,
        "sample_rate_1": t.sample_rate,
        "year": t.year,
        "track_number": t.track_number,
        "size": t.size,
        "length": t.length,
        "play_count_1": t.play_count,
        "disc_number": t.disc_number,
        "rating": t.rating,
        "bpm": t.bpm,
        "skip_count": t.skip_count,
        # Date fields (Unix timestamps)
        "date_added": t.date_added,
        "last_played": t.last_played,
        "last_skipped": t.last_skipped,
        # Boolean fields
        "compilation_flag": 1 if t.compilation_flag else 0,
        # Binary AND fields
        "media_type": t.media_type,
        # Checked flag (0=checked, 1=unchecked in iPod convention)
        "checked_flag": t.checked_flag,
        # Video fields for smart playlist evaluation
        "season_number": t.season_number,
        "Show": t.show_name or "",
        # Podcast/audiobook fields for smart playlist evaluation
        "Description Text": t.description or "",
        "Category": t.category or "",
        "podcast_flag": t.podcast_flag,
    }
