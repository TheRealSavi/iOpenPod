"""Firmware schema matching Original iOpenPod v1.68.1 (Nano 6 reference)."""

LIBRARY_SCHEMA = """
CREATE TABLE version_info (id INTEGER PRIMARY KEY, major INTEGER, minor INTEGER,
 compatibility INTEGER DEFAULT 0, update_level INTEGER DEFAULT 0,
 device_update_level INTEGER DEFAULT 0, platform INTEGER DEFAULT 0);
CREATE TABLE db_info (pid INTEGER NOT NULL PRIMARY KEY, primary_container_pid INTEGER,
 media_folder_url TEXT, audio_language INTEGER, subtitle_language INTEGER,
 genius_cuid TEXT, bib BLOB, rib BLOB);
CREATE TABLE genre_map (id INTEGER NOT NULL PRIMARY KEY, genre TEXT NOT NULL UNIQUE, genre_order INTEGER DEFAULT 0,
 is_unknown INTEGER DEFAULT 0, has_music INTEGER DEFAULT 0,
 artist_count_calc INTEGER NOT NULL DEFAULT 0, album_count_calc INTEGER NOT NULL DEFAULT 0,
 compilation_count_calc INTEGER NOT NULL DEFAULT 0);
CREATE TABLE location_kind_map (id INTEGER NOT NULL PRIMARY KEY, kind TEXT NOT NULL UNIQUE);
CREATE TABLE category_map (id INTEGER NOT NULL PRIMARY KEY, category TEXT NOT NULL UNIQUE);
CREATE TABLE item (pid INTEGER NOT NULL PRIMARY KEY, revision_level INTEGER,
 media_kind INTEGER DEFAULT 0, is_song INTEGER DEFAULT 0,
 is_audio_book INTEGER DEFAULT 0, is_music_video INTEGER DEFAULT 0,
 is_movie INTEGER DEFAULT 0, is_tv_show INTEGER DEFAULT 0,
 is_home_video INTEGER DEFAULT 0, is_ringtone INTEGER DEFAULT 0,
 is_tone INTEGER DEFAULT 0, is_voice_memo INTEGER DEFAULT 0,
 is_book INTEGER DEFAULT 0, is_rental INTEGER DEFAULT 0,
 is_itunes_u INTEGER DEFAULT 0, is_digital_booklet INTEGER DEFAULT 0,
 is_podcast INTEGER DEFAULT 0, date_modified INTEGER DEFAULT 0,
 year INTEGER DEFAULT 0, content_rating INTEGER DEFAULT 0,
 content_rating_level INTEGER DEFAULT 0, is_compilation INTEGER,
 is_user_disabled INTEGER DEFAULT 0, remember_bookmark INTEGER DEFAULT 0,
 exclude_from_shuffle INTEGER DEFAULT 0, part_of_gapless_album INTEGER DEFAULT 0,
 chosen_by_auto_fill INTEGER DEFAULT 0, artwork_status INTEGER,
 artwork_cache_id INTEGER DEFAULT 0, start_time_ms REAL DEFAULT 0,
 stop_time_ms REAL DEFAULT 0, total_time_ms REAL DEFAULT 0,
 total_burn_time_ms REAL, track_number INTEGER DEFAULT 0,
 track_count INTEGER DEFAULT 0, disc_number INTEGER DEFAULT 0,
 disc_count INTEGER DEFAULT 0, bpm INTEGER DEFAULT 0, relative_volume INTEGER,
 eq_preset TEXT, radio_stream_status TEXT, genius_id INTEGER DEFAULT 0,
 genre_id INTEGER DEFAULT 0, category_id INTEGER DEFAULT 0,
 album_pid INTEGER DEFAULT 0, artist_pid INTEGER DEFAULT 0,
 composer_pid INTEGER DEFAULT 0, title TEXT, artist TEXT, album TEXT,
 album_artist TEXT, composer TEXT, sort_title TEXT, sort_artist TEXT,
 sort_album TEXT, sort_album_artist TEXT, sort_composer TEXT,
 title_order INTEGER, artist_order INTEGER, album_order INTEGER,
 genre_order INTEGER, composer_order INTEGER, album_artist_order INTEGER,
 album_by_artist_order INTEGER, series_name_order INTEGER, comment TEXT,
 grouping TEXT, description TEXT, description_long TEXT,
 collection_description TEXT, copyright TEXT, track_artist_pid INTEGER DEFAULT 0,
 physical_order INTEGER, has_lyrics INTEGER DEFAULT 0,
 date_released INTEGER DEFAULT 0);
CREATE TABLE album (pid INTEGER NOT NULL PRIMARY KEY, kind INTEGER, artwork_status INTEGER,
 artwork_item_pid INTEGER, artist_pid INTEGER, user_rating INTEGER, name TEXT,
 name_order INTEGER, all_compilations INTEGER, feed_url TEXT, season_number INTEGER,
 is_unknown INTEGER DEFAULT 0, has_songs INTEGER DEFAULT 0,
 has_music_videos INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0,
 artist_order INTEGER DEFAULT 0, has_any_compilations INTEGER DEFAULT 0,
 sort_name TEXT, artist_count_calc INTEGER NOT NULL DEFAULT 0, has_movies INTEGER DEFAULT 0,
 item_count INTEGER DEFAULT 0);
CREATE TABLE artist (pid INTEGER NOT NULL PRIMARY KEY, kind INTEGER, artwork_status INTEGER,
 artwork_album_pid INTEGER, name TEXT, name_order INTEGER, sort_name TEXT,
 is_unknown INTEGER DEFAULT 0, has_songs INTEGER DEFAULT 0,
 has_music_videos INTEGER DEFAULT 0);
CREATE TABLE track_artist (pid INTEGER NOT NULL PRIMARY KEY, name TEXT, name_order INTEGER,
 sort_name TEXT, has_songs INTEGER DEFAULT 0, has_music_videos INTEGER DEFAULT 0,
 has_non_compilation_tracks INTEGER DEFAULT 0, is_unknown INTEGER DEFAULT 0,
 album_count INTEGER DEFAULT 0);
CREATE TABLE composer (pid INTEGER NOT NULL PRIMARY KEY, name TEXT, name_order INTEGER,
 sort_name TEXT, is_unknown INTEGER DEFAULT 0, has_music INTEGER DEFAULT 0);
CREATE TABLE avformat_info (item_pid INTEGER NOT NULL, sub_id INTEGER NOT NULL DEFAULT 0,
 audio_format INTEGER, bit_rate INTEGER DEFAULT 0, channels INTEGER DEFAULT 0,
 sample_rate REAL DEFAULT 0, duration INTEGER, gapless_heuristic_info INTEGER,
 gapless_encoding_delay INTEGER, gapless_encoding_drain INTEGER,
 gapless_last_frame_resynch INTEGER, analysis_inhibit_flags INTEGER,
 audio_fingerprint INTEGER, volume_normalization_energy INTEGER,
 PRIMARY KEY (item_pid, sub_id));
CREATE TABLE container (pid INTEGER NOT NULL PRIMARY KEY, distinguished_kind INTEGER,
 date_created INTEGER, date_modified INTEGER, name TEXT, name_order INTEGER,
 parent_pid INTEGER, media_kinds INTEGER, workout_template_id INTEGER,
 is_hidden INTEGER, smart_is_folder INTEGER, smart_is_dynamic INTEGER,
 smart_is_filtered INTEGER, smart_is_genius INTEGER, smart_enabled_only INTEGER,
 smart_is_limited INTEGER, smart_limit_kind INTEGER, smart_limit_order INTEGER,
 smart_evaluation_order INTEGER, smart_limit_value INTEGER,
 smart_reverse_limit_order INTEGER, smart_criteria BLOB, description TEXT);
CREATE TABLE item_to_container (item_pid INTEGER, container_pid INTEGER,
 physical_order INTEGER, shuffle_order INTEGER);
CREATE TABLE container_seed (container_pid INTEGER NOT NULL, item_pid INTEGER NOT NULL,
 seed_order INTEGER DEFAULT 0, UNIQUE (container_pid, item_pid));
CREATE TABLE video_info (item_pid INTEGER NOT NULL PRIMARY KEY, has_alternate_audio INTEGER,
 has_subtitles INTEGER, characteristics_valid INTEGER, has_closed_captions INTEGER,
 is_self_contained INTEGER, is_compressed INTEGER, is_anamorphic INTEGER,
 is_hd INTEGER, season_number INTEGER, audio_language INTEGER,
 audio_track_index INTEGER, audio_track_id INTEGER, subtitle_language INTEGER,
 subtitle_track_index INTEGER, subtitle_track_id INTEGER, series_name TEXT,
 sort_series_name TEXT, episode_id TEXT, episode_sort_id INTEGER,
 network_name TEXT, extended_content_rating TEXT, movie_info TEXT);
CREATE TABLE video_characteristics (item_pid INTEGER, sub_id INTEGER DEFAULT 0,
 track_id INTEGER, height INTEGER, width INTEGER, depth INTEGER, codec INTEGER,
 frame_rate REAL, percentage_encrypted REAL, bit_rate INTEGER,
 peak_bit_rate INTEGER, buffer_size INTEGER, profile INTEGER, level INTEGER,
 complexity_level INTEGER, UNIQUE (item_pid, sub_id, track_id));
CREATE TABLE podcast_info (item_pid INTEGER NOT NULL PRIMARY KEY, date_released INTEGER DEFAULT 0,
 external_guid TEXT, feed_url TEXT, feed_keywords TEXT);
CREATE TABLE store_info (item_pid INTEGER NOT NULL PRIMARY KEY, store_kind INTEGER,
 date_purchased INTEGER DEFAULT 0, date_released INTEGER DEFAULT 0,
 account_id INTEGER, key_versions INTEGER, key_platform_id INTEGER, key_id INTEGER,
 key_id2 INTEGER, store_item_id INTEGER, artist_id INTEGER, composer_id INTEGER,
 genre_id INTEGER, playlist_id INTEGER, storefront_id INTEGER,
 store_link_id INTEGER, relevance REAL, popularity REAL, xid TEXT, flavor TEXT);
CREATE TABLE store_link (id INTEGER NOT NULL PRIMARY KEY, url TEXT);
CREATE TABLE track_size_calc (pid INTEGER NOT NULL PRIMARY KEY, kind TEXT NOT NULL UNIQUE, size INTEGER NOT NULL);
CREATE INDEX idx_item_album_pid ON item (album_pid);
CREATE INDEX idx_item_track_artist_pid ON item (track_artist_pid);
CREATE INDEX item_album_order_idx
 ON item (album_order, disc_number, track_number, artist_order, sort_title, physical_order);
CREATE INDEX item_artist_sort_order_idx
 ON item (artist_order, album_order, disc_number, track_number, sort_title, physical_order);
CREATE INDEX item_composer_order_idx ON item (composer_pid, composer_order, media_kind);
CREATE INDEX item_genre_id_idx ON item (genre_id);
CREATE INDEX item_title_order_idx ON item (title_order, media_kind);
CREATE INDEX item_to_container_container_pid_idx
 ON item_to_container (container_pid, physical_order, item_pid);
CREATE INDEX item_to_container_physical_order_idx ON item_to_container (physical_order);
"""

LOCATIONS_SCHEMA = """
CREATE TABLE base_location (id INTEGER NOT NULL PRIMARY KEY, path TEXT);
CREATE TABLE location (item_pid INTEGER NOT NULL, sub_id INTEGER NOT NULL DEFAULT 0,
 base_location_id INTEGER DEFAULT 0, location_type INTEGER, location TEXT,
 extension INTEGER, kind_id INTEGER DEFAULT 0, date_created INTEGER DEFAULT 0,
 file_size INTEGER DEFAULT 0, file_creator INTEGER, file_type INTEGER,
 num_dir_levels_file INTEGER, num_dir_levels_lib INTEGER,
 PRIMARY KEY (item_pid, sub_id));
"""

DYNAMIC_SCHEMA = """
CREATE TABLE item_stats (item_pid INTEGER NOT NULL PRIMARY KEY, has_been_played INTEGER DEFAULT 0,
 date_played INTEGER DEFAULT 0, play_count_user INTEGER DEFAULT 0,
 play_count_recent INTEGER DEFAULT 0, date_skipped INTEGER DEFAULT 0,
 skip_count_user INTEGER DEFAULT 0, skip_count_recent INTEGER DEFAULT 0,
 bookmark_time_ms REAL, bookmark_time_ms_common REAL, user_rating INTEGER DEFAULT 0,
 user_rating_common INTEGER DEFAULT 0, rental_expired INTEGER DEFAULT 0,
 play_count_user_original INTEGER DEFAULT 0, skip_count_user_original INTEGER DEFAULT 0,
 genius_id INTEGER DEFAULT 0);
CREATE TABLE container_ui (container_pid INTEGER NOT NULL PRIMARY KEY, play_order INTEGER DEFAULT 0,
 is_reversed INTEGER DEFAULT 0, album_field_order INTEGER DEFAULT 0,
 repeat_mode INTEGER DEFAULT 0, shuffle_items INTEGER DEFAULT 0,
 has_been_shuffled INTEGER DEFAULT 0);
CREATE TABLE rental_info (item_pid INTEGER NOT NULL PRIMARY KEY,
 rental_date_started INTEGER DEFAULT 0, rental_duration INTEGER DEFAULT 0,
 rental_playback_date_started INTEGER DEFAULT 0,
 rental_playback_duration INTEGER DEFAULT 0, is_demo INTEGER DEFAULT 0);
"""

EXTRAS_SCHEMA = """
CREATE TABLE chapter (item_pid INTEGER NOT NULL PRIMARY KEY, data BLOB);
CREATE TABLE lyrics (item_pid INTEGER NOT NULL PRIMARY KEY, checksum INTEGER, lyrics TEXT);
"""

GENIUS_SCHEMA = """
CREATE TABLE genius_config (id INTEGER NOT NULL PRIMARY KEY, version INTEGER UNIQUE,
 default_num_results INTEGER DEFAULT 0, min_num_results INTEGER DEFAULT 0, data BLOB);
CREATE TABLE genius_metadata (genius_id INTEGER NOT NULL PRIMARY KEY, version INTEGER, data BLOB);
CREATE TABLE genius_similarities (genius_id INTEGER NOT NULL PRIMARY KEY, version INTEGER, data BLOB);
"""
