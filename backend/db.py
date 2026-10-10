"""SQLite storage for user preferences.

Preferences are stored as a validated JSON document per user. SQLite keeps
setup at zero; swapping to Postgres later only means changing this module.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .schemas import (
    FeedbackEntry,
    FeedbackIn,
    PreferencesIn,
    PreferencesOut,
    Quest,
    QuestRecord,
    QuestExample,
    QuestStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id     TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'suggested',
    data         TEXT NOT NULL,
    feedback     TEXT,
    model        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    feedback_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_quests_user ON quests (user_id, created_at);
"""


def db_path() -> str:
    return os.getenv("DATABASE_PATH", "sidequest.db")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _row_to_model(row: sqlite3.Row) -> PreferencesOut:
    return PreferencesOut(
        user_id=row["user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        **PreferencesIn.upgrade_stored(json.loads(row["data"])),
    )


def get_preferences(user_id: str) -> PreferencesOut | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    return _row_to_model(row) if row else None


def upsert_preferences(user_id: str, prefs: PreferencesIn) -> PreferencesOut:
    now = datetime.now(timezone.utc).isoformat()
    data = prefs.model_dump_json()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_preferences (user_id, data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (user_id, data, now, now),
        )
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    return _row_to_model(row)


def delete_preferences(user_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Quests & feedback
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_quest(row: sqlite3.Row) -> QuestRecord:
    return QuestRecord(
        id=row["id"],
        user_id=row["user_id"],
        status=row["status"],
        quest=Quest.model_validate_json(row["data"]),
        feedback=FeedbackIn.model_validate_json(row["feedback"]) if row["feedback"] else None,
        created_at=row["created_at"],
        model=row["model"],
    )


def add_quest(user_id: str, quest: Quest, model: str = "") -> QuestRecord:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO quests (user_id, data, model, created_at) VALUES (?, ?, ?, ?)",
            (user_id, quest.model_dump_json(), model, _now()),
        )
        row = conn.execute("SELECT * FROM quests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_quest(row)


def get_quest(user_id: str, quest_id: int) -> QuestRecord | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM quests WHERE id = ? AND user_id = ?", (quest_id, user_id)
        ).fetchone()
    return _row_to_quest(row) if row else None


def list_quests(user_id: str, limit: int = 20) -> list[QuestRecord]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM quests WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
    return [_row_to_quest(r) for r in rows]


def set_feedback(user_id: str, quest_id: int, feedback: FeedbackIn) -> QuestRecord | None:
    status = QuestStatus.COMPLETED if feedback.completed else QuestStatus.SKIPPED
    with connect() as conn:
        cur = conn.execute(
            "UPDATE quests SET feedback = ?, status = ?, feedback_at = ? WHERE id = ? AND user_id = ?",
            (feedback.model_dump_json(), status.value, _now(), quest_id, user_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
    return _row_to_quest(row)


def feedback_history(user_id: str, limit: int = 10) -> list[FeedbackEntry]:
    """Most recent feedback the user gave, newest first."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT data, feedback, feedback_at FROM quests
               WHERE user_id = ? AND feedback IS NOT NULL
               ORDER BY feedback_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    entries = []
    for r in rows:
        quest = Quest.model_validate_json(r["data"])
        fb = FeedbackIn.model_validate_json(r["feedback"])
        entries.append(
            FeedbackEntry(
                **fb.model_dump(), quest_title=quest.title, quest_tags=quest.tags, created_at=r["feedback_at"]
            )
        )
    return entries


def rated_quests(user_id: str, limit: int = 200) -> list[tuple[Quest, FeedbackIn]]:
    """Every quest the user gave feedback on (newest first) - what taste.learn_taste() learns from."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT data, feedback FROM quests
               WHERE user_id = ? AND feedback IS NOT NULL
               ORDER BY feedback_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [(Quest.model_validate_json(r["data"]), FeedbackIn.model_validate_json(r["feedback"])) for r in rows]


def retrieve_examples(user_id: str, profile: PreferencesIn, k: int = 3, min_rating: int = 4) -> list[QuestExample]:
    """Fallback retrieval when Tiger Data isn't configured: the user's
    best-liked completed quests, favouring tag overlap with their interests."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT data, feedback FROM quests
               WHERE user_id = ? AND status = 'completed' ORDER BY id DESC LIMIT 100""",
            (user_id,),
        ).fetchall()
    interests = {i.value for i in profile.interests} | set(profile.custom_interests)
    scored = []
    for idx, r in enumerate(rows):
        fb = FeedbackIn.model_validate_json(r["feedback"])
        if (fb.rating or 0) < min_rating:
            continue
        quest = Quest.model_validate_json(r["data"])
        overlap = len(interests & set(quest.tags))
        # rating first, then interest overlap, then recency
        scored.append(((fb.rating or 0), overlap, -idx, quest))
    scored.sort(key=lambda t: t[:3], reverse=True)
    return [QuestExample.from_quest(q) for *_, q in scored[:k]]
