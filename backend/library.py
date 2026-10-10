"""Local quest library: SQLite + offline embeddings.

One `quests` table holds:
  * the seeded example quests (source='seed', time_logged_minutes = 0), and
  * every sidequest the app generates (source='generated'), with the user's
    feedback (completed / rating / comment / time logged) filled in later.

Seeded quests, plus generated ones a user completed and rated 4+, are used as
retrieval examples for Gemma. Embeddings are float32 blobs from WordLlama and
search is a cosine-similarity scan (fast for thousands of rows).

Create / re-seed with:
    python -m backend.library
(The backend also creates and seeds it automatically on startup if missing.)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .embeddings import Embedder, EmbeddingError, LocalEmbedder
from .retrieval import RetrievalError, build_query_text, embedding_text, interest_terms
from .schemas import FeedbackEntry, FeedbackIn, Interest, PreferencesIn, Quest, QuestExample

log = logging.getLogger("sidequest.library")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "quest_library.db"
SEED_FILE = ROOT / "tiger" / "seed_quests.json"

# Hybrid ranking: cosine similarity plus a small boost when the quest's
# category / tags match the user's interests (keeps results on-topic with a
# lightweight local embedding model).
CATEGORY_BOOST = 0.15
TAG_BOOST = 0.05
MAX_TAG_BOOST = 0.10
MIN_EXAMPLE_RATING = 4  # generated quests become examples once rated this high

SCHEMA = """
CREATE TABLE IF NOT EXISTS quests (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_text           TEXT    NOT NULL,
    category             TEXT    NOT NULL,
    duration_minutes     INTEGER NOT NULL CHECK (duration_minutes > 0),
    difficulty           TEXT    NOT NULL CHECK (difficulty IN ('easy', 'moderate', 'challenging', 'extreme')),
    tags                 TEXT    NOT NULL DEFAULT '[]',          -- JSON array
    embedding            BLOB,                                   -- float32 vector
    embedding_model      TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    time_logged_minutes  INTEGER NOT NULL DEFAULT 0 CHECK (time_logged_minutes >= 0),
    -- where the row came from
    source               TEXT    NOT NULL DEFAULT 'seed' CHECK (source IN ('seed', 'generated')),
    -- generated quests only
    user_id              TEXT,
    app_quest_id         INTEGER,                                -- quests.id in sidequest.db
    title                TEXT,
    quest_json           TEXT,                                   -- full quest (steps, notes, ...)
    model                TEXT,
    status               TEXT CHECK (status IN ('suggested', 'completed', 'skipped')),
    completed            INTEGER CHECK (completed IN (0, 1)),
    rating               INTEGER CHECK (rating BETWEEN 1 AND 5),
    feedback_comment     TEXT,
    feedback_at          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS quests_seed_text_uq ON quests (quest_text) WHERE source = 'seed';
CREATE UNIQUE INDEX IF NOT EXISTS quests_app_quest_uq ON quests (app_quest_id) WHERE app_quest_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS quests_category_idx ON quests (category);
CREATE INDEX IF NOT EXISTS quests_user_idx ON quests (user_id);
"""

NEW_COLUMNS = [
    "time_logged_minutes", "source", "user_id", "app_quest_id", "title", "quest_json", "model",
    "status", "completed", "rating", "feedback_comment", "feedback_at",
]
ORIGINAL_COLUMNS = [
    "id", "quest_text", "category", "duration_minutes", "difficulty", "tags",
    "embedding", "embedding_model", "created_at",
]


def library_path() -> Path:
    return Path(os.getenv("LIBRARY_PATH") or DEFAULT_PATH)


def is_available() -> bool:
    return library_path().exists()


def _pack(v: Sequence[float]) -> bytes:
    return array("f", v).tobytes()


def _unpack(b: bytes) -> array:
    a = array("f")
    a.frombytes(b)
    return a


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> bool:
    """Bring an older library (without the generated/feedback columns) up to
    date, keeping every existing row. Returns True if it migrated."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(quests)")}
    if not cols or set(NEW_COLUMNS) <= cols:
        return False
    # The old table had a plain UNIQUE(quest_text); SQLite can't drop that in
    # place, so rebuild the table and copy rows across.
    conn.execute("ALTER TABLE quests RENAME TO quests_old")
    for idx in ("quests_category_idx",):
        conn.execute(f"DROP INDEX IF EXISTS {idx}")
    conn.executescript(SCHEMA)
    keep = [c for c in ORIGINAL_COLUMNS if c in cols]
    conn.execute(
        f"INSERT INTO quests ({', '.join(keep)}, time_logged_minutes, source) "
        f"SELECT {', '.join(keep)}, 0, 'seed' FROM quests_old"
    )
    conn.execute("DROP TABLE quests_old")
    conn.commit()
    log.info("Migrated quest library to include generated quests, feedback and time_logged_minutes")
    return True


def init_library(path: Path | None = None, embedder: Embedder | None = None) -> Path:
    """Make sure the library exists, has the current schema, and is seeded."""
    path = Path(path or library_path())
    if not path.exists():
        seed(path, embedder=embedder)
        log.info("Created and seeded quest library at %s", path)
        return path
    conn = _connect(path)
    try:
        migrate(conn)
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    return path


def seed(path: Path | None = None, seed_file: Path = SEED_FILE, embedder: Embedder | None = None) -> int:
    """Create the library (if needed) and upsert all seed quests. Returns seed-row count.
    Generated quests and their feedback are left untouched."""
    path = Path(path or library_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    embedder = embedder or LocalEmbedder()
    rows = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    for r in rows:
        QuestExample(**r)  # validate
    vectors = embedder.embed([embedding_text(r) for r in rows], task="RETRIEVAL_DOCUMENT")

    conn = _connect(path)
    try:
        migrate(conn)
        conn.executescript(SCHEMA)
        conn.executemany(
            """
            INSERT INTO quests (quest_text, category, duration_minutes, difficulty, tags,
                                embedding, embedding_model, source, time_logged_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', 0)
            ON CONFLICT(quest_text) WHERE source = 'seed' DO UPDATE SET
                category = excluded.category,
                duration_minutes = excluded.duration_minutes,
                difficulty = excluded.difficulty,
                tags = excluded.tags,
                embedding = excluded.embedding,
                embedding_model = excluded.embedding_model
            """,
            [
                (r["quest_text"], r["category"], r["duration_minutes"], r["difficulty"],
                 json.dumps(r["tags"]), _pack(v), getattr(embedder, "model", ""))
                for r, v in zip(rows, vectors)
            ],
        )
        conn.commit()
        return conn.execute("SELECT count(*) FROM quests WHERE source = 'seed'").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Generated quests + feedback
# ---------------------------------------------------------------------------

_INTEREST_VALUES = {i.value for i in Interest}


def _category(quest: Quest) -> str:
    """First tag that is one of the app's interest categories, else the first tag."""
    for t in quest.tags:
        if t in _INTEREST_VALUES:
            return t
    return quest.tags[0] if quest.tags else "general"


def add_generated(
    app_quest_id: int,
    user_id: str,
    quest: Quest,
    model: str = "",
    path: Path | None = None,
    embedder: Embedder | None = None,
) -> int:
    """Store a newly generated quest in the library (with its embedding so it
    can later be retrieved once it's been rated highly). Returns the row id."""
    path = Path(path or library_path())
    embedder = embedder or LocalEmbedder()
    row = {
        "quest_text": f"{quest.title}: {quest.summary}",
        "category": _category(quest),
        "duration_minutes": quest.estimated_minutes,
        "difficulty": quest.difficulty.value,
        "tags": quest.tags,
    }
    try:
        [vec] = embedder.embed([embedding_text(row)], task="RETRIEVAL_DOCUMENT")
        blob, emb_model = _pack(vec), getattr(embedder, "model", "")
    except EmbeddingError as exc:  # still record the quest, just without a vector
        log.warning("Couldn't embed generated quest %s: %s", app_quest_id, exc)
        blob, emb_model = None, None

    conn = _connect(path)
    try:
        cur = conn.execute(
            """
            INSERT INTO quests (quest_text, category, duration_minutes, difficulty, tags,
                                embedding, embedding_model, created_at, time_logged_minutes,
                                source, user_id, app_quest_id, title, quest_json, model, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'generated', ?, ?, ?, ?, ?, 'suggested')
            ON CONFLICT(app_quest_id) WHERE app_quest_id IS NOT NULL DO NOTHING
            """,
            (row["quest_text"], row["category"], row["duration_minutes"], row["difficulty"],
             json.dumps(row["tags"]), blob, emb_model, _now(),
             user_id, app_quest_id, quest.title, quest.model_dump_json(), model),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def record_feedback(app_quest_id: int, feedback: FeedbackIn, path: Path | None = None) -> bool:
    """Copy a user's feedback onto the generated quest's library row."""
    path = Path(path or library_path())
    conn = _connect(path)
    try:
        cur = conn.execute(
            """
            UPDATE quests SET
                status = ?, completed = ?, rating = ?, feedback_comment = ?,
                time_logged_minutes = ?, feedback_at = ?
            WHERE app_quest_id = ? AND source = 'generated'
            """,
            ("completed" if feedback.completed else "skipped", int(feedback.completed),
             feedback.rating if feedback.completed else None, feedback.comment or None,
             feedback.time_logged_minutes or 0, _now(), app_quest_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class LocalLibraryRetriever:
    def __init__(self, path: Path | None = None, embedder: Embedder | None = None):
        self.path = Path(path or library_path())
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = LocalEmbedder()
        return self._embedder

    def search(
        self, query_text: str, k: int = 3, max_minutes: int = 720, interests: set[str] | None = None
    ) -> list[QuestExample]:
        if not self.path.exists():
            raise RetrievalError(f"Quest library not found at {self.path} - run: python -m backend.library")
        try:
            [q] = self.embedder.embed([query_text], task="RETRIEVAL_QUERY")
        except EmbeddingError as exc:
            raise RetrievalError(str(exc)) from exc

        try:
            conn = sqlite3.connect(self.path)
            try:
                rows = conn.execute(
                    f"""
                    SELECT quest_text, category, duration_minutes, difficulty, tags, embedding,
                           embedding_model, source
                    FROM quests
                    WHERE embedding IS NOT NULL
                      AND (source = 'seed' OR (completed = 1 AND rating >= {MIN_EXAMPLE_RATING}))
                    """
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RetrievalError(f"Quest library query failed: {exc}") from exc

        model = getattr(self.embedder, "model", None)
        scored = []
        for text, cat, minutes, diff, tags, blob, emb_model, source in rows:
            if model and emb_model and emb_model != model:
                raise RetrievalError(
                    f"Library was embedded with {emb_model} but queries use {model} - re-run: python -m backend.library"
                )
            v = _unpack(blob)
            if len(v) != len(q):
                raise RetrievalError("Embedding size mismatch - re-run: python -m backend.library")
            sim = sum(a * b for a, b in zip(q, v))
            score = sim
            if interests:
                tag_list = json.loads(tags)
                score += CATEGORY_BOOST * (cat in interests)
                score += min(MAX_TAG_BOOST, TAG_BOOST * len(interests & set(tag_list)))
            scored.append((minutes > max_minutes, -score, text, cat, minutes, diff, tags, sim, source))

        scored.sort(key=lambda t: (t[0], t[1]))  # fitting quests first, then most similar
        return [
            QuestExample(quest_text=t, category=c, duration_minutes=m, difficulty=d,
                         tags=json.loads(tg), similarity=round(s, 4),
                         source="local_library" if src == "seed" else "local_library_rated")
            for _, _, t, c, m, d, tg, s, src in scored[:k]
        ]

    def retrieve(
        self, profile: PreferencesIn, feedback: Sequence[FeedbackEntry] | None = None, k: int = 3
    ) -> list[QuestExample]:
        results = self.search(build_query_text(profile, feedback), k=k,
                              max_minutes=profile.availability.duration_minutes,
                              interests=interest_terms(profile))
        log.info("Local library retrieval: %d examples (%s)", len(results),
                 ", ".join(f"{r.category}:{r.similarity}" for r in results))
        return results


if __name__ == "__main__":
    target = library_path()
    n = seed(target)
    print(f"Seeded {n} quests into {target}")
    sys.exit(0)
