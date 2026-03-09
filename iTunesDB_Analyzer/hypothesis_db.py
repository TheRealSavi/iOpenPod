"""Persistent hypothesis database backed by SQLite.

Stores field hypotheses, pattern observations, cross-file correlations,
and version-branch annotations.  All data survives restarts and grows
incrementally as new iTunesDB files are analyzed.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


_SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingested_files (
    file_path    TEXT PRIMARY KEY,
    file_size    INTEGER NOT NULL,
    db_version   INTEGER NOT NULL,
    version_name TEXT NOT NULL,
    track_count  INTEGER NOT NULL,
    mhit_hl     INTEGER,          -- mhit header_length (schema indicator)
    ingested_at  REAL NOT NULL     -- Unix timestamp
);

CREATE TABLE IF NOT EXISTS field_hypothesis (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_type       TEXT NOT NULL,
    rel_offset       INTEGER NOT NULL,
    length           INTEGER NOT NULL,
    candidate_type   TEXT NOT NULL,     -- 'u32','u16','u8','timestamp','flag','fourcc','pointer','padding','hash'
    candidate_name   TEXT NOT NULL DEFAULT '',
    confidence       REAL NOT NULL DEFAULT 0.0,  -- 0.0..1.0
    supporting_files INTEGER NOT NULL DEFAULT 0,
    contra_files     INTEGER NOT NULL DEFAULT 0,
    rationale        TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    is_ground_truth  INTEGER NOT NULL DEFAULT 0,  -- user-asserted
    UNIQUE(chunk_type, rel_offset, length, candidate_type, candidate_name)
);

CREATE TABLE IF NOT EXISTS pattern_observation (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_type   TEXT NOT NULL,
    rel_offset   INTEGER NOT NULL,
    length       INTEGER NOT NULL,
    pattern_kind TEXT NOT NULL,   -- 'all_zero','constant','binary','range','high_entropy','distribution'
    summary      TEXT NOT NULL,   -- human-readable description
    value_json   TEXT NOT NULL DEFAULT '{}',  -- detailed data (min, max, distinct values, etc.)
    file_count   INTEGER NOT NULL DEFAULT 0,
    db_version   INTEGER,         -- NULL = cross-version
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    UNIQUE(chunk_type, rel_offset, length, pattern_kind, db_version)
);

CREATE TABLE IF NOT EXISTS cross_field_correlation (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_type    TEXT NOT NULL,
    unknown_offset INTEGER NOT NULL,
    unknown_length INTEGER NOT NULL,
    known_field   TEXT NOT NULL,
    relation      TEXT NOT NULL,   -- 'equal','plus1','minus1','times2','half','co_null','co_vary','pearson'
    strength      REAL NOT NULL,   -- correlation coefficient or match fraction
    sample_count  INTEGER NOT NULL DEFAULT 0,
    db_version    INTEGER,
    rationale     TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    UNIQUE(chunk_type, unknown_offset, unknown_length, known_field, relation, db_version)
);

CREATE TABLE IF NOT EXISTS version_branch (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_type   TEXT NOT NULL,
    rel_offset   INTEGER NOT NULL,
    length       INTEGER NOT NULL,
    observation  TEXT NOT NULL,      -- 'appears_in','disappears_in','changes_meaning'
    version_min  INTEGER,
    version_max  INTEGER,
    detail       TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    UNIQUE(chunk_type, rel_offset, length, observation, version_min, version_max)
);

CREATE INDEX IF NOT EXISTS idx_hyp_chunk ON field_hypothesis(chunk_type, rel_offset);
CREATE INDEX IF NOT EXISTS idx_pat_chunk ON pattern_observation(chunk_type, rel_offset);
CREATE INDEX IF NOT EXISTS idx_corr_chunk ON cross_field_correlation(chunk_type, unknown_offset);
CREATE INDEX IF NOT EXISTS idx_vb_chunk ON version_branch(chunk_type, rel_offset);
"""


class HypothesisDB:
    """Persistent SQLite store for analysis hypotheses and observations."""

    def __init__(self, db_path: str | Path = "hypothesis.db"):
        self._path = str(db_path)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._tx() as cur:
            cur.executescript(_DDL)
            cur.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES(?, ?)",
                ("schema_version", str(_SCHEMA_VERSION)),
            )

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    # ── Ingested files ──────────────────────────────────────────────

    def record_file(
        self,
        file_path_or_db: str | Any,
        file_size: int = 0,
        db_version: int = 0,
        version_name: str = "",
        track_count: int = 0,
        mhit_hl: Optional[int] = None,
    ) -> None:
        # Accept either a ParsedDatabase or explicit args.
        if not isinstance(file_path_or_db, str):
            db = file_path_or_db
            file_path_or_db = db.file_path
            file_size = db.file_size
            db_version = db.db_version
            version_name = db.db_version_name
            track_count = db.track_count
            mhit_hl = db.mhit_header_length
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO ingested_files
                   (file_path, file_size, db_version, version_name, track_count, mhit_hl, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (file_path_or_db, file_size, db_version, version_name, track_count, mhit_hl, now),
            )

    def ingested_files(self) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM ingested_files ORDER BY ingested_at")
        return [dict(row) for row in cur.fetchall()]

    def ingested_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM ingested_files").fetchone()[0]

    # ── Hypotheses ──────────────────────────────────────────────────

    def upsert_hypothesis(
        self,
        chunk_type: str,
        rel_offset: int,
        length: int,
        candidate_type: str,
        candidate_name: str = "",
        confidence: float = 0.0,
        supporting_files: int = 0,
        contra_files: int = 0,
        rationale: str = "",
        is_ground_truth: bool = False,
    ) -> None:
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                """INSERT INTO field_hypothesis
                   (chunk_type, rel_offset, length, candidate_type, candidate_name,
                    confidence, supporting_files, contra_files, rationale,
                    created_at, updated_at, is_ground_truth)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chunk_type, rel_offset, length, candidate_type, candidate_name)
                   DO UPDATE SET
                     confidence=excluded.confidence,
                     supporting_files=excluded.supporting_files,
                     contra_files=excluded.contra_files,
                     rationale=excluded.rationale,
                     updated_at=excluded.updated_at,
                     is_ground_truth=MAX(field_hypothesis.is_ground_truth, excluded.is_ground_truth)
                """,
                (chunk_type, rel_offset, length, candidate_type, candidate_name,
                 confidence, supporting_files, contra_files, rationale,
                 now, now, int(is_ground_truth)),
            )

    def top_hypotheses(
        self,
        limit: int = 20,
        chunk_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if chunk_type:
            cur = self._conn.execute(
                """SELECT * FROM field_hypothesis
                   WHERE chunk_type = ?
                   ORDER BY confidence DESC, supporting_files DESC
                   LIMIT ?""",
                (chunk_type, limit),
            )
        else:
            cur = self._conn.execute(
                """SELECT * FROM field_hypothesis
                   ORDER BY confidence DESC, supporting_files DESC
                   LIMIT ?""",
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]

    def hypotheses_for(
        self,
        chunk_type: str,
        rel_offset: int,
    ) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """SELECT * FROM field_hypothesis
               WHERE chunk_type = ? AND rel_offset = ?
               ORDER BY confidence DESC""",
            (chunk_type, rel_offset),
        )
        return [dict(row) for row in cur.fetchall()]

    def all_hypotheses(
        self,
        chunk_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if chunk_type:
            cur = self._conn.execute(
                "SELECT * FROM field_hypothesis WHERE chunk_type = ? ORDER BY confidence DESC",
                (chunk_type,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM field_hypothesis ORDER BY confidence DESC",
            )
        return [dict(row) for row in cur.fetchall()]

    # ── Pattern observations ────────────────────────────────────────

    def upsert_pattern(
        self,
        chunk_type: str,
        rel_offset: int,
        length: int,
        pattern_kind: str,
        summary: str,
        value_json: dict | str = "{}",
        file_count: int = 0,
        db_version: Optional[int] = None,
    ) -> None:
        now = time.time()
        vj = json.dumps(value_json) if isinstance(value_json, dict) else value_json
        with self._tx() as cur:
            cur.execute(
                """INSERT INTO pattern_observation
                   (chunk_type, rel_offset, length, pattern_kind, summary,
                    value_json, file_count, db_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chunk_type, rel_offset, length, pattern_kind, db_version)
                   DO UPDATE SET
                     summary=excluded.summary,
                     value_json=excluded.value_json,
                     file_count=excluded.file_count,
                     updated_at=excluded.updated_at
                """,
                (chunk_type, rel_offset, length, pattern_kind, summary,
                 vj, file_count, db_version, now, now),
            )

    def patterns_for(
        self,
        chunk_type: str,
        rel_offset: int,
    ) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """SELECT * FROM pattern_observation
               WHERE chunk_type = ? AND rel_offset = ?""",
            (chunk_type, rel_offset),
        )
        return [dict(row) for row in cur.fetchall()]

    # ── Cross-field correlations ────────────────────────────────────

    def upsert_correlation(
        self,
        chunk_type: str,
        unknown_offset: int,
        unknown_length: int,
        known_field: str,
        relation: str,
        strength: float,
        sample_count: int = 0,
        db_version: Optional[int] = None,
        rationale: str = "",
    ) -> None:
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                """INSERT INTO cross_field_correlation
                   (chunk_type, unknown_offset, unknown_length, known_field,
                    relation, strength, sample_count, db_version, rationale, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chunk_type, unknown_offset, unknown_length, known_field, relation, db_version)
                   DO UPDATE SET
                     strength=excluded.strength,
                     sample_count=excluded.sample_count,
                     rationale=excluded.rationale
                """,
                (chunk_type, unknown_offset, unknown_length, known_field,
                 relation, strength, sample_count, db_version, rationale, now),
            )

    def correlations_for(
        self,
        known_field: Optional[str] = None,
        chunk_type: Optional[str] = None,
        unknown_offset: Optional[int] = None,
        min_strength: float = 0.0,
    ) -> list[dict[str, Any]]:
        clauses = ["strength >= ?"]
        params: list[Any] = [min_strength]
        if known_field:
            clauses.append("known_field = ?")
            params.append(known_field)
        if chunk_type:
            clauses.append("chunk_type = ?")
            params.append(chunk_type)
        if unknown_offset is not None:
            clauses.append("unknown_offset = ?")
            params.append(unknown_offset)
        where = " AND ".join(clauses)
        cur = self._conn.execute(
            f"SELECT * FROM cross_field_correlation WHERE {where} ORDER BY strength DESC",
            params,
        )
        return [dict(row) for row in cur.fetchall()]

    # ── Version branches ────────────────────────────────────────────

    def upsert_version_branch(
        self,
        chunk_type: str,
        rel_offset: int,
        length: int,
        observation: str,
        version_min: Optional[int] = None,
        version_max: Optional[int] = None,
        detail: str = "",
    ) -> None:
        now = time.time()
        with self._tx() as cur:
            cur.execute(
                """INSERT INTO version_branch
                   (chunk_type, rel_offset, length, observation, version_min, version_max, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chunk_type, rel_offset, length, observation, version_min, version_max)
                   DO UPDATE SET detail=excluded.detail
                """,
                (chunk_type, rel_offset, length, observation, version_min, version_max, detail, now),
            )

    def version_branches(self) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM version_branch ORDER BY chunk_type, rel_offset")
        return [dict(row) for row in cur.fetchall()]

    # ── Summary ─────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        c = self._conn
        return {
            "files_ingested": c.execute("SELECT COUNT(*) FROM ingested_files").fetchone()[0],
            "total_hypotheses": c.execute("SELECT COUNT(*) FROM field_hypothesis").fetchone()[0],
            "ground_truths": c.execute("SELECT COUNT(*) FROM field_hypothesis WHERE is_ground_truth=1").fetchone()[0],
            "pattern_observations": c.execute("SELECT COUNT(*) FROM pattern_observation").fetchone()[0],
            "correlations": c.execute("SELECT COUNT(*) FROM cross_field_correlation").fetchone()[0],
            "version_branches": c.execute("SELECT COUNT(*) FROM version_branch").fetchone()[0],
            "high_confidence": c.execute("SELECT COUNT(*) FROM field_hypothesis WHERE confidence >= 0.85").fetchone()[0],
        }
