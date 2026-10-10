"""Local example-quest library: SQLite + offline embeddings.

A drop-in alternative to the Tiger Data library for local development. The
`quests` table has the same columns (quest_text, category, duration_minutes,
difficulty, tags, embedding); embeddings are float32 blobs from WordLlama and
search is a cosine-similarity scan (fast for hundreds of rows).

Re-seed from tiger/seed_quests.json with:
    python -m backend.library
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from array import array
from pathlib import Path
from typing import Sequence

from .embeddings import Embedder, EmbeddingError, LocalEmbedder
from .retrieval import RetrievalError, build_query_text, embedding_text, interest_terms
from .schemas import FeedbackEntry, PreferencesIn, QuestExample

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS quests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    quest_text        TEXT    NOT NULL UNIQUE,
    category          TEXT    NOT NULL,
    duration_minutes  INTEGER NOT NULL CHECK (duration_minutes > 0),
    difficulty        TEXT    NOT NULL CHECK (difficulty IN ('easy', 'moderate', 'challenging', 'extreme')),
    tags              TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    embedding         BLOB,                            -- float32 vector
    embedding_model   TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS quests_category_idx ON quests (category);
"""


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


def seed(path: Path | None = None, seed_file: Path = SEED_FILE, embedder: Embedder | None = None) -> int:
    """Create the library (if needed) and upsert all seed quests. Returns row count."""
    path = Path(path or library_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    embedder = embedder or LocalEmbedder()
    rows = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    for r in rows:
        QuestExample(**r)  # validate
    vectors = embedder.embed([embedding_text(r) for r in rows], task="RETRIEVAL_DOCUMENT")

    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            """
            INSERT INTO quests (quest_text, category, duration_minutes, difficulty, tags, embedding, embedding_model)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(quest_text) DO UPDATE SET
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
        return conn.execute("SELECT count(*) FROM quests").fetchone()[0]
    finally:
        conn.close()


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
                    "SELECT quest_text, category, duration_minutes, difficulty, tags, embedding, embedding_model "
                    "FROM quests WHERE embedding IS NOT NULL"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RetrievalError(f"Quest library query failed: {exc}") from exc

        model = getattr(self.embedder, "model", None)
        scored = []
        for text, cat, minutes, diff, tags, blob, emb_model in rows:
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
            scored.append((minutes > max_minutes, -score, text, cat, minutes, diff, tags, sim))

        scored.sort(key=lambda t: (t[0], t[1]))  # fitting quests first, then most similar
        return [
            QuestExample(quest_text=t, category=c, duration_minutes=m, difficulty=d,
                         tags=json.loads(tg), similarity=round(s, 4), source="local_library")
            for _, _, t, c, m, d, tg, s in scored[:k]
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
