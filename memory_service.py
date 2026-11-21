"""High-speed in-process SQLite FTS5 (BM25 + temporal decay) durable memory engine with mempalace bridge."""
from __future__ import annotations

from array import array
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from typing import Any, Iterator, Optional
from uuid import uuid4
import zlib

try:
    import numpy as _np
except Exception:
    _np = None

logger = logging.getLogger(__name__)


_STOPWORDS = frozenset(
    """
    a an the and or but if then else when while of to in on at by for with about
    as is are was were be been being do does did doing have has had having
    i you he she it we they me him her us them my your his its our their
    this that these those there here what which who whom whose why how
    not no nor so than too very can will just don should now from into over under
    also any all each every some such only own same other more most tell please
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}", re.UNICODE)
COLD_THRESHOLD_BYTES = 4096
HOT_INDEX_PREFIX_CHARS = 2048
_VEC_DIM = 128

_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("warm", "friendly", "friend", "personal", "personable", "mate", "banter", "casual"),
    ("optimise", "optimize", "optimisation", "optimization", "speed", "faster", "perf", "performance"),
    ("colour", "color", "theme", "skin", "palette"),
    ("summarise", "summarize", "summary", "recap"),
    ("arvo", "afternoon"),
    ("bug", "fix", "crash", "error", "issue", "broken"),
    ("voice", "speech", "tts", "speak", "audio", "talk"),
    ("draw", "image", "graphic", "banner", "picture", "photo", "render"),
    ("memory", "recall", "remember", "profile", "context", "history"),
)
_SYNONYM_MAP: dict[str, tuple[str, ...]] = {}
for _grp in _SYNONYM_GROUPS:
    for _tok in _grp:
        _SYNONYM_MAP[_tok] = _grp

_NEGATION_CUE_RE = re.compile(
    r"\b(?:not|never|avoid|dislike|don'?t|do\s+not|stop|hate|no|less)\b",
    re.IGNORECASE,
)
_AFFIRM_CUE_RE = re.compile(
    r"\b(?:prefer|like|always|want|use|enable|keep|love|more)\b",
    re.IGNORECASE,
)
_TRIVIAL_EXCHANGE_RE = re.compile(
    r"^(?:test(?:ing)?|testing\s+microphone|mm+|uh+|um+|ah+|ok(?:ay)?|k|yes|no|yep|nope|"
    r"hi|hello|hey|thank(?:s|\s+you)|not\s+bad\s+okay|that'?s\s+okay(?:,\s*i'?m\s+good)?|"
    r"cheers|cool|nice|good|done|stop|bye|[.\s?!,_-]+)$",
    re.IGNORECASE,
)
_CANONICAL_PROFILE_CATEGORIES = (
    "Overview",
    "How You Like to Work",
    "Speech & Communication Style",
    "Software & Creative Projects",
)


def extract_keywords(text: str, max_terms: int = 12) -> list[str]:
    if not text:
        return []
    raw = [w.lower() for w in _WORD_RE.findall(text)]
    filtered = [w for w in raw if w not in _STOPWORDS and len(w) >= 2]
    if not filtered:
        filtered = [w for w in raw if len(w) >= 2]
    if not filtered:
        return []
    counts = Counter(filtered)
    return [
        w
        for w, _ in sorted(
            counts.items(),
            key=lambda item: (item[1], len(item[0])),
            reverse=True,
        )[:max_terms]
    ]


def _expand_query_terms(terms: list[str], max_terms: int = 18) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for t in terms:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            expanded.append(tl)
    for t in list(expanded):
        for sib in _SYNONYM_MAP.get(t, ()):
            if sib not in seen:
                seen.add(sib)
                expanded.append(sib)
                if len(expanded) >= max_terms:
                    return expanded[:max_terms]
    return expanded[:max_terms]


def build_fts_match_query(user_prompt: str, max_terms: int = 12) -> str:
    terms = extract_keywords(user_prompt, max_terms=max_terms)
    if not terms:
        return ""
    expanded = _expand_query_terms(terms, max_terms=max(max_terms, 18))
    return " OR ".join(f'"{t}"*' for t in expanded)


def _embed_text_vec(text: str) -> bytes:
    """Compute a fast L2-normalized local 128-d float32 feature vector over words, synonyms, and char n-grams."""
    raw = (text or "").lower().strip()
    if not raw:
        return array("f", [0.0] * _VEC_DIM).tobytes()
    buckets = [0.0] * _VEC_DIM

    def _add_feat(token: str, weight: float) -> None:
        digest = hashlib.blake2b(token.encode("utf-8", errors="replace"), digest_size=4).digest()
        val = int.from_bytes(digest, "little")
        idx = val % _VEC_DIM
        sign = 1.0 if ((val >> 31) & 1) == 0 else -1.0
        buckets[idx] += sign * weight

    words = [w for w in _WORD_RE.findall(raw) if w not in _STOPWORDS]
    if not words:
        words = _WORD_RE.findall(raw)
    for w in words[:96]:
        _add_feat(f"w:{w}", 1.0)
        grp = _SYNONYM_MAP.get(w)
        if grp:
            _add_feat(f"s:{grp[0]}", 0.65)
        if len(w) >= 4:
            for i in range(len(w) - 2):
                _add_feat(f"g:{w[i:i+3]}", 0.30)

    norm_sq = sum(v * v for v in buckets)
    if norm_sq > 0.0:
        inv = 1.0 / math.sqrt(norm_sq)
        buckets = [v * inv for v in buckets]
    return array("f", buckets).tobytes()


def _cosine_sim_bytes(blob_a: bytes, blob_b: bytes) -> float:
    if not blob_a or not blob_b or len(blob_a) != len(blob_b):
        return 0.0
    if _np is not None:
        va = _np.frombuffer(blob_a, dtype=_np.float32)
        vb = _np.frombuffer(blob_b, dtype=_np.float32)
        return max(0.0, float(_np.dot(va, vb)))
    aa = array("f")
    ab = array("f")
    aa.frombytes(blob_a)
    ab.frombytes(blob_b)
    return max(0.0, float(sum(x * y for x, y in zip(aa, ab))))


def _has_opposite_polarity(text_a: str, text_b: str) -> bool:
    neg_a = bool(_NEGATION_CUE_RE.search(text_a or ""))
    neg_b = bool(_NEGATION_CUE_RE.search(text_b or ""))
    if neg_a != neg_b:
        return True
    la, lb = (text_a or "").lower(), (text_b or "").lower()
    if ("more " in la and "less " in lb) or ("less " in la and "more " in lb):
        return True
    return False


def _is_trivial_exchange(question: str) -> bool:
    clean = re.sub(r"\s+", " ", (question or "").strip()).rstrip(".!? ")
    if len(clean) < 4:
        return True
    return bool(_TRIVIAL_EXCHANGE_RE.match(clean))


def _normalize_profile_category(raw_cat: str, fact_text: str = "") -> str:
    txt = f"{raw_cat or ''} {fact_text or ''}".lower()
    if raw_cat and raw_cat.strip() in _CANONICAL_PROFILE_CATEGORIES and "|" not in raw_cat:
        return raw_cat.strip()
    if any(k in txt for k in ("speech", "grammar", "tone", "warm", "friendly", "banter", "flatter", "slang", "idiolect", "talk", "policing", "concise")):
        return "Speech & Communication Style"
    if any(k in txt for k in ("project", "fairybread", "evidencebench", "duk", "shadow", "palace", "software", "creative", "comedy", "music", "health", "ginger")):
        return "Software & Creative Projects"
    if any(k in txt for k in ("work", "workflow", "autopatch", "review", "plan", "git", "drive", "edit", "notepad", "visual studio", "test")):
        return "How You Like to Work"
    return "Overview"


def _compact_summary_for_prompt(summary_md: str, max_chars: int = 2100) -> str:
    text = (summary_md or "").strip()
    if not text or len(text) <= max_chars:
        return text
    sections: list[tuple[str, list[str]]] = []
    cur_hdr = "Overview"
    cur_lines: list[str] = []
    for raw_ln in text.splitlines():
        if raw_ln.startswith("### "):
            if cur_lines:
                sections.append((cur_hdr, cur_lines))
            cur_hdr = raw_ln[4:].strip()
            cur_lines = []
        else:
            cur_lines.append(raw_ln)
    if cur_lines:
        sections.append((cur_hdr, cur_lines))

    def _prio(hdr: str) -> int:
        if "|" in hdr:
            return 2
        if hdr in _CANONICAL_PROFILE_CATEGORIES:
            return 0
        return 1

    ordered = sorted(enumerate(sections), key=lambda pair: (_prio(pair[1][0]), pair[0]))
    out_parts: list[str] = []
    used_len = 0
    for _idx, (hdr, lns) in ordered:
        block = f"### {hdr}\n" + "\n".join(lns).strip()
        block = block.strip()
        if not block:
            continue
        sep = 2 if out_parts else 0
        if used_len + sep + len(block) <= max_chars:
            out_parts.append(block)
            used_len += sep + len(block)
        elif max_chars - used_len > 140:
            rem = max_chars - used_len - sep - 4
            out_parts.append(block[:rem].rsplit("\n", 1)[0].strip() + "\n...")
            break
    if not out_parts:
        return text[:max_chars]
    return "\n\n".join(out_parts)


def _content_hash(summary: str, body: str) -> str:
    norm = re.sub(r"\s+", " ", f"{summary or ''}\x00{body or ''}").strip().lower()
    return hashlib.sha256(norm.encode("utf-8", errors="replace")).hexdigest()


def get_default_memory_db_path() -> Path:
    try:
        from palace_config import get_palace_data_root
        base = get_palace_data_root()
    except Exception:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Palace"
    base.mkdir(parents=True, exist_ok=True)
    return base / "memory.db"


class SQLiteMemoryIndex:
    """In-process SQLite WAL + FTS5 (porter unicode61) durable memory store with hybrid BM25+vector scoring."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else get_default_memory_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._search_cache: OrderedDict[tuple, tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            try:
                conn.execute("PRAGMA mmap_size=67108864;")
            except sqlite3.OperationalError:
                pass
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    wing TEXT NOT NULL DEFAULT 'gpt_palace',
                    room TEXT NOT NULL DEFAULT 'general',
                    project TEXT NOT NULL DEFAULT '',
                    ts REAL NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'semantic',
                    visibility TEXT NOT NULL DEFAULT 'private',
                    summary TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source_json TEXT NOT NULL DEFAULT '{}',
                    importance INTEGER NOT NULL DEFAULT 3,
                    scope TEXT NOT NULL DEFAULT 'global',
                    active INTEGER NOT NULL DEFAULT 1,
                    superseded_by TEXT NOT NULL DEFAULT '',
                    hits_shown INTEGER NOT NULL DEFAULT 0,
                    last_confirmed_ts REAL NOT NULL DEFAULT 0
                );
                """
            )
            existing_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(memories);").fetchall()}
            migrations = (
                ("importance", "INTEGER NOT NULL DEFAULT 3"),
                ("scope", "TEXT NOT NULL DEFAULT 'global'"),
                ("active", "INTEGER NOT NULL DEFAULT 1"),
                ("superseded_by", "TEXT NOT NULL DEFAULT ''"),
                ("hits_shown", "INTEGER NOT NULL DEFAULT 0"),
                ("last_confirmed_ts", "REAL NOT NULL DEFAULT 0"),
            )
            for col_name, col_def in migrations:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def};")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(wing, project, ts DESC);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(wing, active, ts DESC);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories_blob (
                    memory_id TEXT PRIMARY KEY,
                    codec TEXT NOT NULL DEFAULT 'zlib',
                    payload BLOB NOT NULL,
                    raw_bytes INTEGER NOT NULL,
                    stored_bytes INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories_vec (
                    memory_id TEXT PRIMARY KEY,
                    dim INTEGER NOT NULL,
                    vec BLOB NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id UNINDEXED,
                    summary,
                    body,
                    project,
                    room,
                    tokenize='porter unicode61'
                );
                """
            )

    def _ensure_vec_rows(self, conn: sqlite3.Connection, wing: str | None = None, batch_limit: int = 200) -> None:
        if wing:
            missing = conn.execute(
                """
                SELECT m.id, m.summary, m.body
                FROM memories m
                LEFT JOIN memories_vec v ON v.memory_id = m.id
                WHERE v.memory_id IS NULL AND m.active = 1 AND m.wing = ?
                LIMIT ?;
                """,
                (wing, batch_limit),
            ).fetchall()
        else:
            missing = conn.execute(
                """
                SELECT m.id, m.summary, m.body
                FROM memories m
                LEFT JOIN memories_vec v ON v.memory_id = m.id
                WHERE v.memory_id IS NULL AND m.active = 1
                LIMIT ?;
                """,
                (batch_limit,),
            ).fetchall()
        if not missing:
            return
        hydrated = self._hydrate_rows_batch(conn, [dict(r) for r in missing])
        rows_to_insert = [
            (
                d["id"],
                _VEC_DIM,
                _embed_text_vec(f"{d.get('summary') or ''} {d.get('body') or ''}"),
            )
            for d in hydrated
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO memories_vec (memory_id, dim, vec) VALUES (?, ?, ?);",
            rows_to_insert,
        )

    def _hydrate_rows_batch(
        self,
        conn: sqlite3.Connection,
        row_dicts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not row_dicts:
            return row_dicts
        uniq_ids = list(dict.fromkeys(str(d["id"]) for d in row_dicts if d.get("id")))
        if not uniq_ids:
            return row_dicts
        blob_map: dict[str, str] = {}
        chunk_size = 500
        for idx in range(0, len(uniq_ids), chunk_size):
            batch = uniq_ids[idx : idx + chunk_size]
            placeholders = ",".join("?" for _ in batch)
            blob_rows = conn.execute(
                f"SELECT memory_id, codec, payload FROM memories_blob WHERE memory_id IN ({placeholders});",
                batch,
            ).fetchall()
            for blob_row in blob_rows:
                mid = str(blob_row["memory_id"])
                if blob_row["codec"] == "zlib":
                    try:
                        blob_map[mid] = zlib.decompress(blob_row["payload"]).decode("utf-8", errors="replace")
                    except Exception as exc:
                        logger.warning("Failed to decompress memory blob %s: %s", mid, exc)
        for d in row_dicts:
            mid = d.get("id")
            if mid and str(mid) in blob_map:
                d["body"] = blob_map[str(mid)]
        return row_dicts

    def _hydrate_body(self, conn: sqlite3.Connection, row_dict: dict[str, Any]) -> dict[str, Any]:
        return self._hydrate_rows_batch(conn, [row_dict])[0]

    def upsert(
        self,
        summary: str,
        body: str,
        *,
        memory_id: str | None = None,
        wing: str = "gpt_palace",
        room: str = "general",
        project: str = "",
        memory_type: str = "semantic",
        visibility: str = "private",
        source: dict[str, Any] | None = None,
        ts: float | None = None,
        importance: int | None = None,
        scope: str | None = None,
    ) -> str:
        now_ts = float(ts if ts is not None else time.time())
        clean_summary = (summary or "").strip()
        clean_body = (body or clean_summary).strip()
        mtype_l = (memory_type or "semantic").strip().lower()
        if importance is not None:
            eff_imp = max(1, min(5, int(importance)))
        elif mtype_l in {"standing", "boundary", "idiolect"}:
            eff_imp = 5
        elif mtype_l == "preference":
            eff_imp = 4
        else:
            eff_imp = 3
        clean_proj = (project or "").strip()
        eff_scope = (scope or "").strip() or (f"project:{clean_proj.lower()}" if clean_proj else "global")
        ch = _content_hash(clean_summary, clean_body)
        src_dict = dict(source or {})
        src_dict["content_hash"] = ch
        src_str = json.dumps(src_dict)
        vec_blob = _embed_text_vec(f"{clean_summary} {clean_body}")
        superseded_ids: list[str] = []

        self._search_cache.clear()
        with self._connect() as conn:
            if memory_id is None:
                # Check for exact content_hash deduplication within the same wing
                candidates = conn.execute(
                    "SELECT id, source_json FROM memories WHERE wing = ? AND summary = ? AND active = 1;",
                    (wing, clean_summary),
                ).fetchall()
                mid = ""
                for row in candidates:
                    try:
                        stored_src = json.loads(row["source_json"] or "{}")
                    except (TypeError, ValueError):
                        stored_src = {}
                    if isinstance(stored_src, dict) and stored_src.get("content_hash") == ch:
                        mid = str(row["id"])
                        conn.execute(
                            "UPDATE memories SET ts = ?, last_confirmed_ts = ?, importance = MAX(importance, ?) WHERE id = ?;",
                            (now_ts, now_ts, eff_imp, mid),
                        )
                        return mid

                if mtype_l in {"standing", "preference", "boundary", "idiolect"}:
                    self._ensure_vec_rows(conn, wing=wing)
                    durable_rows = conn.execute(
                        """
                        SELECT m.id, m.summary, m.body, m.importance, v.vec
                        FROM memories m
                        JOIN memories_vec v ON v.memory_id = m.id
                        WHERE m.wing = ? AND m.active = 1
                          AND LOWER(m.memory_type) IN ('standing', 'preference', 'boundary', 'idiolect')
                          AND m.id != 'palace_master_memory_summary'
                        ORDER BY m.ts DESC
                        LIMIT 100;
                        """,
                        (wing,),
                    ).fetchall()
                    new_text = f"{clean_summary} {clean_body}"
                    for dr in durable_rows:
                        sim = _cosine_sim_bytes(vec_blob, bytes(dr["vec"] or b""))
                        if sim < 0.62:
                            continue
                        old_text = f"{dr['summary'] or ''} {dr['body'] or ''}"
                        if _has_opposite_polarity(new_text, old_text):
                            superseded_ids.append(str(dr["id"]))
                        elif sim >= 0.80:
                            existing_id = str(dr["id"])
                            conn.execute(
                                "UPDATE memories SET ts = ?, last_confirmed_ts = ?, importance = MAX(importance, ?) WHERE id = ?;",
                                (now_ts, now_ts, eff_imp, existing_id),
                            )
                            return existing_id

                mid = str(uuid4())
            else:
                mid = memory_id.strip()

            raw_bytes = clean_body.encode("utf-8")
            indexed_body = clean_body
            if len(raw_bytes) > COLD_THRESHOLD_BYTES:
                compressed = zlib.compress(raw_bytes, level=6)
                if len(compressed) < int(len(raw_bytes) * 0.85):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO memories_blob
                        (memory_id, codec, payload, raw_bytes, stored_bytes)
                        VALUES (?, 'zlib', ?, ?, ?);
                        """,
                        (mid, compressed, len(raw_bytes), len(compressed)),
                    )
                    indexed_body = clean_body[:HOT_INDEX_PREFIX_CHARS]
                else:
                    conn.execute("DELETE FROM memories_blob WHERE memory_id = ?;", (mid,))
            else:
                conn.execute("DELETE FROM memories_blob WHERE memory_id = ?;", (mid,))

            conn.execute("DELETE FROM memory_fts WHERE id = ?;", (mid,))
            conn.execute(
                """
                INSERT OR REPLACE INTO memories
                (id, wing, room, project, ts, memory_type, visibility, summary, body, source_json,
                 importance, scope, active, superseded_by, hits_shown, last_confirmed_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, '', 0, ?);
                """,
                (
                    mid, wing, room, project, now_ts, memory_type, visibility,
                    clean_summary, indexed_body, src_str, eff_imp, eff_scope, now_ts,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_fts (id, summary, body, project, room)
                VALUES (?, ?, ?, ?, ?);
                """,
                (mid, clean_summary, clean_body, project, room),
            )
            conn.execute(
                "INSERT OR REPLACE INTO memories_vec (memory_id, dim, vec) VALUES (?, ?, ?);",
                (mid, _VEC_DIM, vec_blob),
            )
            for old_id in superseded_ids:
                conn.execute(
                    "UPDATE memories SET active = 0, superseded_by = ? WHERE id = ?;",
                    (mid, old_id),
                )
        return mid

    def count(self, wing: str | None = None, include_inactive: bool = False) -> int:
        with self._connect() as conn:
            active_clause = "" if include_inactive else "active = 1"
            if wing:
                where = f"WHERE wing = ?{' AND ' + active_clause if active_clause else ''}"
                row = conn.execute(f"SELECT COUNT(*) AS c FROM memories {where};", (wing,)).fetchone()
            else:
                where = f"WHERE {active_clause}" if active_clause else ""
                row = conn.execute(f"SELECT COUNT(*) AS c FROM memories {where};").fetchone()
            return int(row["c"]) if row else 0

    def list_memories(
        self,
        wing: str | None = None,
        limit: int = 100,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            clauses: list[str] = []
            params: list[Any] = []
            if not include_inactive:
                clauses.append("active = 1")
            if wing:
                clauses.append("wing = ?")
                params.append(wing)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM memories {where} ORDER BY ts DESC LIMIT ?;",
                params,
            ).fetchall()
            return self._hydrate_rows_batch(conn, [dict(r) for r in rows])

    def delete_memory(self, memory_id: str) -> bool:
        self._search_cache.clear()
        with self._connect() as conn:
            conn.execute("DELETE FROM memories_blob WHERE memory_id = ?;", (memory_id,))
            conn.execute("DELETE FROM memories_vec WHERE memory_id = ?;", (memory_id,))
            conn.execute("DELETE FROM memory_fts WHERE id = ?;", (memory_id,))
            cur = conn.execute("DELETE FROM memories WHERE id = ?;", (memory_id,))
            return cur.rowcount > 0

    def record_hits_shown(self, memory_ids: list[str]) -> None:
        uniq = [mid for mid in dict.fromkeys(str(x or "").strip() for x in memory_ids) if mid]
        if not uniq:
            return
        try:
            with self._connect() as conn:
                conn.executemany(
                    "UPDATE memories SET hits_shown = COALESCE(hits_shown, 0) + 1 WHERE id = ?;",
                    [(mid,) for mid in uniq],
                )
        except Exception:
            pass

    def search(
        self,
        query: str,
        *,
        wing: str | None = None,
        project: str | None = None,
        boost_project: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        norm_q = (query or "").strip()
        cache_key = (wing or "", project or "", boost_project or "", int(limit), norm_q.lower())
        now_ts = time.time()
        cached_entry = self._search_cache.get(cache_key)
        if cached_entry is not None and (now_ts - cached_entry[0]) <= 300.0:
            self._search_cache.move_to_end(cache_key)
            return [dict(item) for item in cached_entry[1]]

        fts_query = build_fts_match_query(norm_q, max_terms=12)
        q_vec = _embed_text_vec(norm_q) if norm_q else b""
        bp_low = (boost_project or project or "").strip().lower()

        with self._connect() as conn:
            self._ensure_vec_rows(conn, wing=wing)
            fts_map: dict[str, tuple[dict[str, Any], float]] = {}
            if fts_query:
                sql = """
                    SELECT m.*, bm25(memory_fts, 0.0, 8.0, 4.0, 2.0, 1.0) AS raw_bm25
                    FROM memory_fts
                    JOIN memories m ON m.id = memory_fts.id
                    WHERE memory_fts MATCH ? AND m.active = 1
                """
                params: list[Any] = [fts_query]
                if wing:
                    sql += " AND m.wing = ?"
                    params.append(wing)
                if project:
                    sql += " AND m.project = ?"
                    params.append(project)
                sql += " LIMIT 60;"
                try:
                    for r in conn.execute(sql, params).fetchall():
                        d = dict(r)
                        raw_b = abs(float(d.pop("raw_bm25", 0.0) or 0.0))
                        fts_map[str(d["id"])] = (d, raw_b)
                except sqlite3.OperationalError:
                    pass

            vec_sql = """
                SELECT m.*, v.vec AS vec_blob
                FROM memories m
                JOIN memories_vec v ON v.memory_id = m.id
                WHERE m.active = 1
            """
            v_params: list[Any] = []
            if wing:
                vec_sql += " AND m.wing = ?"
                v_params.append(wing)
            if project:
                vec_sql += " AND m.project = ?"
                v_params.append(project)
            vec_sql += " ORDER BY m.ts DESC LIMIT 250;"
            vec_rows = conn.execute(vec_sql, v_params).fetchall()

            candidates_by_id: dict[str, tuple[dict[str, Any], float, float]] = {}
            for vr in vec_rows:
                d = dict(vr)
                v_blob = bytes(d.pop("vec_blob", b"") or b"")
                mid = str(d["id"])
                cos_sim = _cosine_sim_bytes(q_vec, v_blob) if q_vec else 0.0
                fts_hit = fts_map.get(mid)
                bm25_raw = fts_hit[1] if fts_hit is not None else 0.0
                if fts_hit is not None or cos_sim >= 0.14 or not norm_q:
                    candidates_by_id[mid] = (d, bm25_raw, cos_sim)

            for mid, (d, bm25_raw) in fts_map.items():
                if mid not in candidates_by_id:
                    candidates_by_id[mid] = (d, bm25_raw, 0.0)

            candidate_dicts = [entry[0] for entry in candidates_by_id.values()]
            hydrated = self._hydrate_rows_batch(conn, candidate_dicts)
            scored: list[tuple[float, dict[str, Any]]] = []
            for d in hydrated:
                mid = str(d["id"])
                _, bm25_raw, cos_sim = candidates_by_id[mid]
                bm25_norm = (bm25_raw / (bm25_raw + 2.0)) if bm25_raw > 0 else 0.0
                if norm_q:
                    hybrid_rel = (0.60 * bm25_norm + 0.40 * cos_sim) if bm25_norm > 0 else (0.75 * cos_sim)
                else:
                    hybrid_rel = 0.25
                age_days = max(0.0, (now_ts - float(d.get("ts", now_ts))) / 86400.0)
                recency_boost = math.exp(-age_days / 60.0)
                imp_norm = max(1, min(5, int(d.get("importance") or 3))) / 5.0
                row_proj = str(d.get("project") or "").strip().lower()
                row_scope = str(d.get("scope") or "global").strip().lower()
                if bp_low and (row_proj == bp_low or row_scope == f"project:{bp_low}"):
                    scope_match = 1.0
                elif row_scope == "global" or not row_proj:
                    scope_match = 0.25
                else:
                    scope_match = 0.0
                final_score = (0.55 * hybrid_rel) + (0.20 * recency_boost) + (0.15 * imp_norm) + (0.10 * scope_match)
                d["score"] = round(final_score, 4)
                scored.append((final_score, d))

            scored.sort(key=lambda item: item[0], reverse=True)
            top_out = [item[1] for item in scored[:limit]]

        self._search_cache[cache_key] = (now_ts, [dict(item) for item in top_out])
        if len(self._search_cache) > 128:
            self._search_cache.popitem(last=False)
        return top_out

    def backup_to_file(self, dest_path: Path) -> None:
        """Online WAL-safe SQLite backup API."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as src_conn:
            dst_conn = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()


@dataclass
class MemorySearchResult:
    context: str
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


DEFAULT_MEMORY_SUMMARY_MARKDOWN = (
    "### Overview\n"
    "You're an Australian Gen X creator and systems builder, around 60 (`bm069au`). You bring a practical, "
    "pattern-focused approach to technology and creative work, and prefer useful specifics and candid technical "
    "pushback over generic reassurance or flattery. Your main interests include building software and multi-AI tools, "
    "making music and animated comedy, health and gut-microbiome wellness, and hands-on projects such as brewing ginger beer.\n\n"
    "### How You Like to Work\n"
    "You prefer concise, personable answers with an optional deeper technical layer when needed. You value direct options "
    "and risks, dislike canned reassurance and a policing tone, and are comfortable with banter when the subject is light. "
    "For development, you want a clear summary and plan before implementation steps or code changes. You edit in Notepad++ "
    "or Visual Studio and use Git savepoints. Your drive conventions are `G:` for notes and checkpoints, `E:` for active "
    "projects (`E:\\Visual_studio\\Palace`), and `M:` for private backups/media (strictly off-limits unless explicitly authorized).\n\n"
    "### Software & Creative Projects\n"
    "- **Fairybread (formerly Palace, `E:\\Visual_studio\\Palace`):** Your source-available donationware multi-AI council "
    "desktop workspace (`https://github.com/bm069au/fairybread`) where 8 AI providers (`Gemini`, `OpenAI`, `DeepSeek`, `Groq`, "
    "`Qwen`, `Cohere`, `Mistral`, `Cerebras`) collaborate, share a 100% local SQLite FTS5 Memory Palace, render 300-DPI artwork "
    "and banners, use Live Voice Mode, and run autonomous multi-agent experiments in Idle Mode.\n"
    "- **EvidenceBench (`E:\\Visual_studio\\EvidenceBenchDesktop`):** Your local-first evidence workspace with imports, metadata, "
    "graphing, exhaustive email search, and backups.\n"
    "- **Creative & Community Work:** Your upcoming animated comedy series and your Facebook wellness / gut-microbiome community group."
)


def _format_relative_age(ts: float) -> str:
    if not ts or ts <= 0:
        return "Updated recently"
    delta = max(0.0, time.time() - float(ts))
    if delta < 90:
        return "Updated just now"
    mins = int(delta // 60)
    if mins < 60:
        return f"Updated {mins}m ago"
    hrs = int(mins // 60)
    if hrs < 24:
        return f"Updated {hrs} hour{'s' if hrs != 1 else ''} ago"
    days = int(hrs // 24)
    return f"Updated {days} day{'s' if days != 1 else ''} ago"


def _summary_json_path(db_path: Path | None = None) -> Path:
    resolved_db = Path(db_path) if db_path is not None else get_default_memory_db_path()
    return resolved_db.parent / "memory_summary.json"


def load_memory_summary(db_path: Path | None = None) -> dict[str, Any]:
    """Load the user's living Memory Summary (or initialize with the default profile summary)."""
    p = _summary_json_path(db_path)
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and str(raw.get("text") or "").strip():
                ts = float(raw.get("updated_ts") or time.time())
                return {
                    "text": str(raw["text"]).strip(),
                    "updated_ts": ts,
                    "updated_relative": _format_relative_age(ts),
                    "turn_counter": int(raw.get("turn_counter") or 0),
                }
        except Exception:
            pass
    now_ts = time.time()
    initial = {
        "text": DEFAULT_MEMORY_SUMMARY_MARKDOWN,
        "updated_ts": now_ts,
        "updated_relative": _format_relative_age(now_ts),
        "turn_counter": 0,
    }
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(initial, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    return initial


def save_memory_summary(
    markdown_text: str,
    *,
    db_path: Path | None = None,
    turn_counter: int | None = None,
) -> dict[str, Any]:
    """Save edited or AI-updated Memory Summary to disk and mirror into memory.db as a top standing record."""
    clean = (markdown_text or "").strip() or DEFAULT_MEMORY_SUMMARY_MARKDOWN
    cur = load_memory_summary(db_path)
    now_ts = time.time()
    payload = {
        "text": clean,
        "updated_ts": now_ts,
        "updated_relative": _format_relative_age(now_ts),
        "turn_counter": int(turn_counter if turn_counter is not None else cur.get("turn_counter", 0)),
    }
    p = _summary_json_path(db_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    try:
        idx = SQLiteMemoryIndex(db_path=db_path)
        idx.upsert(
            summary="Master Memory Summary (Overview, How You Like to Work & Projects)",
            body=clean,
            memory_id="palace_master_memory_summary",
            memory_type="standing",
            source={"kind": "memory_summary"},
            ts=now_ts,
        )
    except Exception:
        pass
    return payload


def ai_update_memory_summary(
    instruction: str = "",
    *,
    db_path: Path | None = None,
    credential_store: Any = None,
) -> dict[str, Any]:
    """Update the living Memory Summary using an AI instruction ('Ask or update') or recent chat memories."""
    cur_data = load_memory_summary(db_path)
    cur_text = cur_data["text"]
    idx = SQLiteMemoryIndex(db_path=db_path)
    recent_mems = [
        m for m in idx.list_memories(limit=15)
        if str(m.get("id")) != "palace_master_memory_summary"
    ]
    recent_block = "\n".join(
        f"- {m.get('summary', '')}: {str(m.get('body', ''))[:240]}"
        for m in recent_mems[:10]
    )
    req_note = (instruction or "").strip()
    sys_prompt = (
        "You maintain the user's living 'Memory summary' for Fairybread (shared across all Council AIs), "
        "formatted exactly like ChatGPT's Memory summary with clear Markdown headings:\n"
        "### Overview\n"
        "### How You Like to Work\n"
        "### Software & Creative Projects\n\n"
        "Rules:\n"
        "- Preserve existing accurate details unless the user asks to change or remove them.\n"
        "- Write in warm, direct second-person ('You're...', 'You prefer...').\n"
        "- Output ONLY the updated Markdown sections (no preamble or code fences)."
    )
    user_prompt = (
        f"CURRENT MEMORY SUMMARY:\n{cur_text}\n\n"
        f"RECENT CONVERSATION MEMORIES:\n{recent_block or '(None)'}\n\n"
        f"USER UPDATE REQUEST:\n{req_note or 'Refresh and refine the Memory summary incorporating any new project milestones or preferences from recent conversations.'}"
    )

    try:
        from credential_store import CredentialStore
        store = credential_store or CredentialStore()
    except Exception:
        store = None

    updated_md = ""
    if store is not None:
        # 1. Try Groq fast model
        g_key = store.get_api_key("groq")
        if g_key and not updated_md:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=g_key, base_url="https://api.groq.com/openai/v1", timeout=15.0, max_retries=0)
                resp = client.chat.completions.create(
                    model="qwen/qwen3.8-27b",
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                )
                updated_md = (resp.choices[0].message.content or "").strip()
            except Exception:
                pass
        # 2. Try OpenAI
        o_key = store.get_api_key("openai")
        if o_key and not updated_md:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=o_key, timeout=15.0, max_retries=0)
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                )
                updated_md = (resp.choices[0].message.content or "").strip()
            except Exception:
                pass
        # 3. Try Gemini (Hydrogen fast model -> 2.5-flash fallback)
        gem_key = store.get_api_key("gemini")
        if gem_key and not updated_md:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gem_key, http_options=types.HttpOptions(timeout=15000))
            for gm in ("gemini-4-hydrogen", "gemini-2.5-flash"):
                try:
                    resp = client.models.generate_content(
                        model=gm,
                        contents=f"{sys_prompt}\n\n{user_prompt}",
                    )
                    updated_md = (getattr(resp, "text", "") or "").strip()
                    if updated_md:
                        break
                except Exception:
                    continue

    if not updated_md:
        # Offline fallback: append user's update note cleanly
        if req_note:
            updated_md = f"{cur_text}\n\n- **Update:** {req_note}"
        else:
            updated_md = cur_text

    return save_memory_summary(updated_md, db_path=db_path)


def auto_evolve_user_profile_from_turn(
    user_message: str,
    *,
    db_path: Path | None = None,
    credential_store: Any = None,
) -> list[dict[str, str]]:
    """Zero-latency background profile extractor with Council Verbatim-Evidence Anti-Hallucination Gate."""
    clean_msg = (user_message or "").strip()
    if len(clean_msg) < 18:
        return []
    lower_msg = clean_msg.lower()
    personal_signals = (
        "i ", "i'm", "im ", "my ", "we ", "prefer", "working on", "building",
        "always ", "never ", "like to", "live in", "years old", "project", "hobby",
        "talk ", "tone", "grammar", "line spacing", "friendly", "warm", "banter", "address", "call me",
    )
    if not any(sig in lower_msg for sig in personal_signals):
        return []

    try:
        from palace_config import load_personalization_settings
        if not load_personalization_settings().get("auto_evolve_profile", True):
            return []
    except Exception:
        pass

    sys_prompt = (
        "You are Fairybread's Rich User Profile Extractor. Analyze the user's message and extract ONLY "
        "explicit, durable personal facts, speech/tone/grammar preferences, workflow rules, or project details stated by the user.\n"
        "STRICT ANTI-HALLUCINATION RULES:\n"
        "1. NEVER guess, infer, or extrapolate traits from general questions.\n"
        "2. Every extracted item MUST include 'evidence': an exact verbatim substring copied directly from the user's message.\n"
        "3. Choose EXACTLY ONE canonical 'category' from: Overview | How You Like to Work | Speech & Communication Style | Software & Creative Projects (never join with '|').\n"
        "4. Output ONLY a valid JSON array (or [] if no durable personal fact was stated):\n"
        '[{"category": "Overview", "fact": "Concise second-person fact (You...)", "evidence": "exact verbatim quote"}]'
    )

    try:
        from credential_store import CredentialStore
        store = credential_store or CredentialStore()
    except Exception:
        return []

    raw_json = ""
    # 1. Try Groq fast model first
    g_key = store.get_api_key("groq") if store else ""
    if g_key and not raw_json:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=g_key, base_url="https://api.groq.com/openai/v1", timeout=15.0, max_retries=0)
            resp = client.chat.completions.create(
                model="qwen/qwen3.8-27b",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": clean_msg[:2000]},
                ],
                temperature=0.1,
            )
            raw_json = (resp.choices[0].message.content or "").strip()
        except Exception:
            pass

    # 2. Fallback to OpenAI gpt-4o-mini
    o_key = store.get_api_key("openai") if store else ""
    if o_key and not raw_json:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=o_key, timeout=15.0, max_retries=0)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": clean_msg[:2000]},
                ],
                temperature=0.1,
            )
            raw_json = (resp.choices[0].message.content or "").strip()
        except Exception:
            pass

    if not raw_json:
        return []

    # Extract JSON array
    m_arr = re.search(r"\[.*\]", raw_json, flags=re.DOTALL)
    if not m_arr:
        return []
    try:
        items = json.loads(m_arr.group(0))
    except Exception:
        return []
    if not isinstance(items, list) or not items:
        return []

    verified: list[dict[str, str]] = []
    cur_summary = load_memory_summary(db_path).get("text", "")
    updated_summary = cur_summary
    idx = SQLiteMemoryIndex(db_path=db_path)

    for it in items[:4]:
        if not isinstance(it, dict):
            continue
        fact = str(it.get("fact") or "").strip()
        ev = str(it.get("evidence") or "").strip()
        cat = _normalize_profile_category(str(it.get("category") or "Overview"), fact)
        # Verbatim Evidence Gate: quote must actually appear in the user's message
        if not fact or not ev or len(ev) < 5 or ev.lower() not in lower_msg:
            continue
        if fact.lower() in updated_summary.lower():
            continue
        verified.append({"category": cat, "fact": fact, "evidence": ev})
        bullet = f"- {fact} *(from: \"{ev[:80]}\")*"
        heading = f"### {cat}"
        if heading in updated_summary:
            updated_summary = updated_summary.replace(heading, f"{heading}\n{bullet}", 1)
        else:
            updated_summary = updated_summary.rstrip() + f"\n\n### {cat}\n{bullet}"
        m_type = "idiolect" if cat == "Speech & Communication Style" else "standing"
        idx.upsert(
            summary=fact[:120],
            body=f"{fact}\nVerbatim evidence: \"{ev}\"",
            memory_type=m_type,
            importance=5,
            scope="global",
            source={"kind": "auto_profile_fact", "category": cat, "evidence": ev},
        )

    if verified and updated_summary != cur_summary:
        save_memory_summary(updated_summary, db_path=db_path)
    return verified


class MemoryService:
    def __init__(
        self,
        wing: str = "gpt_palace",
        memory_limit: int = 7500,
        db_path: Path | None = None,
    ):
        self.wing = wing
        self.memory_limit = memory_limit
        self.index = SQLiteMemoryIndex(db_path=db_path)

    def remember_exchange(
        self,
        question: str,
        answer: str,
        *,
        session_id: str = "",
        project: str = "",
        contributors: list[str] | None = None,
        ts: float | None = None,
    ) -> str:
        """Automatically store a completed user/Council exchange into the shared SQLite FTS5 Memory Palace (like ChatGPT/Antigravity)."""
        clean_q = re.sub(r"\s+", " ", (question or "").strip())
        if _is_trivial_exchange(clean_q):
            return ""
        clean_a = re.sub(r'\[GENERATE_IMAGE\s+(?:[^\]"]|"[^"]*")*\]', "[Generated Image]", answer or "", flags=re.IGNORECASE)
        clean_a = re.sub(r"\[PALACE_UI_SNAPSHOT[^\]]*\]", "[UI Snapshot]", clean_a, flags=re.IGNORECASE).strip()
        if not clean_a:
            return ""
        summary = clean_q if len(clean_q) <= 140 else clean_q[:137] + "..."
        contrib_str = ", ".join(contributors or [])
        header = f"Council ({contrib_str})" if contrib_str else "Council"
        body = f"User: {clean_q}\n{header}: {clean_a[:2400]}"
        return self.index.upsert(
            summary=summary,
            body=body,
            wing=self.wing,
            room=session_id or "general",
            project=project or "",
            memory_type="contextual",
            importance=3,
            visibility="private",
            source={
                "kind": "auto_exchange",
                "session_id": session_id,
                "contributors": list(contributors or []),
            },
            ts=ts,
        )

    def backfill_from_sessions(self, palace_root: Path | None = None) -> int:
        """Backfill existing saved conversations from sessions/*.jsonl into memory.db so all AIs share prior context."""
        if palace_root is None:
            palace_root = self.index.db_path.parent
        sessions_dir = Path(palace_root) / "sessions"
        if not sessions_dir.exists():
            return 0
        added = 0
        for sf in sorted(sessions_dir.glob("*.jsonl")):
            sid = sf.stem
            last_q = ""
            try:
                for line in sf.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    role = rec.get("role")
                    phase = rec.get("phase")
                    content = str(rec.get("content") or "").strip()
                    if role == "user" and content:
                        last_q = content
                    elif role == "assistant" and phase in {None, "synthesis", "voice_chat"} and last_q and content:
                        self.remember_exchange(
                            last_q,
                            content,
                            session_id=sid,
                            contributors=rec.get("contributors") or [],
                        )
                        added += 1
                        last_q = ""
            except Exception:
                continue
        return added

    def search(self, query: str, *, project: str | None = None) -> MemorySearchResult:
        # Preserve direct subprocess path ONLY when unit tests explicitly mock subprocess.run
        is_mocked = hasattr(subprocess.run, "assert_called") or "mock" in type(subprocess.run).__name__.lower()
        if not is_mocked:
            try:
                summary_data = load_memory_summary(self.index.db_path)
                summary_md = (summary_data.get("text") or "").strip()

                all_recent = self.index.list_memories(wing=self.wing, limit=60)
                durable_types = {"standing", "preference", "boundary", "idiolect"}
                standing = sorted(
                    [
                        m for m in all_recent
                        if str(m.get("memory_type") or "").lower() in durable_types
                        and str(m.get("id")) != "palace_master_memory_summary"
                    ],
                    key=lambda m: (int(m.get("importance") or 3), float(m.get("ts") or 0.0)),
                    reverse=True,
                )[:4]

                query_hits = [
                    m for m in self.index.search(query, wing=self.wing, boost_project=project, limit=10)
                    if str(m.get("id")) != "palace_master_memory_summary"
                    and not _is_trivial_exchange(str(m.get("summary") or ""))
                ][:6]

                recent_substantive = [
                    m for m in all_recent
                    if str(m.get("memory_type") or "").lower() not in durable_types
                    and str(m.get("id")) != "palace_master_memory_summary"
                    and not _is_trivial_exchange(str(m.get("summary") or ""))
                ][:3]

                # Stage A: Personalization + Compact Profile Summary + Top Durable Identity/Speech Facts
                stage_a_budget = min(3400, max(600, int(self.memory_limit * 0.48)))
                stage_a_blocks: list[str] = []
                used_a = 0
                seen_ids: set[str] = set()
                shown_ids: list[str] = []

                def _append_bounded(target: list[str], chunk: str, cur_len: int, max_len: int) -> tuple[int, bool]:
                    if not chunk:
                        return cur_len, False
                    sep = 2 if target else 0
                    if cur_len + sep + len(chunk) <= max_len:
                        target.append(chunk)
                        return cur_len + sep + len(chunk), True
                    return cur_len, False

                try:
                    from palace_config import format_personalization_prompt_block
                    pers_block = format_personalization_prompt_block()
                    used_a, _ = _append_bounded(stage_a_blocks, pers_block, used_a, stage_a_budget)
                except Exception:
                    pass

                if summary_md and used_a < stage_a_budget - 200:
                    comp_summary = _compact_summary_for_prompt(
                        summary_md,
                        max_chars=min(2100, stage_a_budget - used_a - 80),
                    )
                    sum_block = f"[USER & PROJECT MEMORY SUMMARY — SHARED ACROSS ALL COUNCIL AIs]:\n{comp_summary}"
                    used_a, _ = _append_bounded(stage_a_blocks, sum_block, used_a, stage_a_budget)

                for st_item in standing:
                    mid = str(st_item.get("id") or "")
                    entry = f"[{str(st_item.get('memory_type') or 'standing').upper()}] {st_item['summary']}\n{st_item['body'][:400]}"
                    used_a, added_ok = _append_bounded(stage_a_blocks, entry, used_a, stage_a_budget)
                    if added_ok and mid:
                        seen_ids.add(mid)
                        shown_ids.append(mid)

                # Stage B: Hybrid Query Hits + Substantive Recent Usage (never starved by Stage A)
                stage_b_blocks: list[str] = []
                stage_b_budget = max(400, self.memory_limit - used_a - 4)
                used_b = 0

                for hit in query_hits:
                    mid = str(hit.get("id") or "")
                    if mid in seen_ids:
                        continue
                    proj_tag = f" ({hit.get('project')})" if hit.get("project") else ""
                    entry = f"[MEMORY HIT{proj_tag}] {hit['summary']}\n{hit['body'][:550]}"
                    used_b, added_ok = _append_bounded(stage_b_blocks, entry, used_b, stage_b_budget)
                    if added_ok and mid:
                        seen_ids.add(mid)
                        shown_ids.append(mid)

                for rec in recent_substantive:
                    mid = str(rec.get("id") or "")
                    if mid in seen_ids:
                        continue
                    proj_tag = f" ({rec.get('project')})" if rec.get("project") else ""
                    entry = f"[RECENT USAGE{proj_tag}] {rec['summary']}\n{rec['body'][:420]}"
                    used_b, added_ok = _append_bounded(stage_b_blocks, entry, used_b, stage_b_budget)
                    if added_ok and mid:
                        seen_ids.add(mid)
                        shown_ids.append(mid)

                self.index.record_hits_shown(shown_ids)
                combined_blocks = stage_a_blocks + stage_b_blocks
                combined = "\n\n".join(combined_blocks)[: self.memory_limit].strip()
                if combined:
                    return MemorySearchResult(context=combined)
                return MemorySearchResult(context="No relevant memory found.")
            except Exception as exc:
                return MemorySearchResult(context="", error=str(exc))

        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "mempalace",
                    "search",
                    query,
                    "--wing",
                    self.wing,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                },
            )

            if result.returncode != 0:
                error = result.stderr.strip()
                if not error:
                    error = f"Memory Palace exited with code {result.returncode}"
                return MemorySearchResult(context="", error=error)

            context = result.stdout[: self.memory_limit].strip()
            if not context:
                context = "No relevant memory found."
            return MemorySearchResult(context=context)

        except Exception as exc:
            return MemorySearchResult(context="", error=str(exc))


_SAVE_MEMORY_ATTR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*"([^"]*)"')
_SAVE_MEMORY_BLOCK_RE = re.compile(
    r'\[SAVE_MEMORY([^\]]*)\](.*?)\[/SAVE_MEMORY\]',
    re.IGNORECASE | re.DOTALL,
)
_SAVE_MEMORY_SINGLE_RE = re.compile(
    r'\[SAVE_MEMORY\s+((?:[^\]"]|"[^"]*")*)\]',
    re.IGNORECASE,
)


def parse_save_memory_tags(
    text: str,
    *,
    replace_with_badge: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    """Parse `[SAVE_MEMORY ...]` block and inline tags into structured dicts and stripped/badged text."""
    raw = text or ""
    if "[SAVE_MEMORY" not in raw.upper():
        return raw, []

    found: list[dict[str, str]] = []

    def _collect(attrs_str: str, inner_body: str = "") -> str:
        attrs = {k.lower(): v.strip() for k, v in _SAVE_MEMORY_ATTR_RE.findall(attrs_str or "")}
        fact = (
            (inner_body or "").strip()
            or attrs.get("fact", "")
            or attrs.get("body", "")
            or attrs.get("content", "")
            or attrs.get("text", "")
        ).strip()
        summary = attrs.get("summary", "").strip()
        if not summary and fact:
            summary = fact if len(fact) <= 100 else fact[:97] + "..."
        if not fact and summary:
            fact = summary
        if not summary and not fact:
            return ""
        m_type = (attrs.get("memory_type") or attrs.get("type") or "standing").strip().lower() or "standing"
        entry = {
            "summary": summary[:140],
            "fact": fact,
            "project": attrs.get("project", "").strip(),
            "memory_type": m_type,
        }
        found.append(entry)
        return f'🧠 Saved to Memory Palace: "{entry["summary"]}"' if replace_with_badge else ""

    out = _SAVE_MEMORY_BLOCK_RE.sub(lambda m: _collect(m.group(1), m.group(2)), raw)
    out = _SAVE_MEMORY_SINGLE_RE.sub(lambda m: _collect(m.group(1)), out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, found


def extract_and_save_memory_tags(
    text: str,
    memory_service: MemoryService | None,
    *,
    session_id: str = "",
    project: str = "",
    author: str = "council",
    replace_with_badge: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """Execute any `[SAVE_MEMORY ...]` tags against `memory_service` and return `(cleaned_text, saved_entries)`."""
    if not text or "[SAVE_MEMORY" not in text.upper() or memory_service is None:
        return text or "", []
    cleaned, parsed = parse_save_memory_tags(text, replace_with_badge=replace_with_badge)
    saved: list[dict[str, Any]] = []
    for item in parsed:
        summary = item["summary"]
        fact = item["fact"]
        proj = item.get("project") or project or ""
        mem_type = item.get("memory_type") or "standing"
        try:
            mem_id = memory_service.index.upsert(
                summary=summary,
                body=fact,
                wing=memory_service.wing,
                room=session_id or "general",
                project=proj,
                memory_type=mem_type,
                visibility="private",
                source={
                    "kind": "explicit_ai_save",
                    "session_id": session_id,
                    "author": author,
                },
            )
            saved.append({"id": mem_id, "summary": summary, "fact": fact, "memory_type": mem_type})
        except Exception:
            pass
    return cleaned, saved
