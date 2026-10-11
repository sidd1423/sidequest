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
    QuestContext,
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
    feedback_at  TEXT,
    completed_at TEXT,
    context      TEXT
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
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Columns added after the first release."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(quests)")}
    if "completed_at" not in cols:
        # When the quest was completed (for streaks). Older rows fall back to feedback_at.
        conn.execute("ALTER TABLE quests ADD COLUMN completed_at TEXT")
    if "context" not in cols:
        # Weather/place/nearby spots when the quest was generated (QuestContext JSON).
        conn.execute("ALTER TABLE quests ADD COLUMN context TEXT")


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


def delete_user_data(user_id: str) -> None:
    """Everything this user has in the main database (account deletion)."""
    with connect() as conn:
        conn.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM quests WHERE user_id = ?", (user_id,))
        for table in ("quest_logs", "streak_freezes", "quest_routes"):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))


def feedback_rows(user_id: str) -> list[tuple[int, Quest, FeedbackIn, datetime]]:
    """(quest id, quest, feedback, when it was completed - or rated, if not completed) for every rated quest."""
    with connect() as conn:
        _migrate(conn)
        rows = conn.execute(
            """SELECT id, data, feedback, COALESCE(completed_at, feedback_at, created_at) AS at FROM quests
               WHERE user_id = ? AND feedback IS NOT NULL ORDER BY at""",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        when = datetime.fromisoformat(r["at"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        out.append((r["id"], Quest.model_validate_json(r["data"]), FeedbackIn.model_validate_json(r["feedback"]), when))
    return out


def journal_counts(user_id: str) -> dict[int, tuple[int, int]]:
    """quest id -> (photos, notes) in the quest log."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'quest_logs'").fetchone():
            return {}
        rows = conn.execute(
            """SELECT quest_id, SUM(kind = 'photo') AS photos, SUM(kind = 'note') AS notes
               FROM quest_logs WHERE user_id = ? GROUP BY quest_id""",
            (user_id,),
        ).fetchall()
    return {r["quest_id"]: (r["photos"] or 0, r["notes"] or 0) for r in rows}


def quest_stats(user_id: str) -> dict[str, int]:
    """Totals for the Quest screen counter."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT status, feedback FROM quests WHERE user_id = ?", (user_id,)
        ).fetchall()
    completed = sum(1 for r in rows if r["status"] == QuestStatus.COMPLETED.value)
    minutes = 0
    for r in rows:
        if r["feedback"]:
            minutes += FeedbackIn.model_validate_json(r["feedback"]).time_logged_minutes or 0
    return {"completed": completed, "generated": len(rows), "minutes_outside": minutes}


# ---------------------------------------------------------------------------
# Quests & feedback
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_quest(row: sqlite3.Row) -> QuestRecord:
    context = row["context"] if "context" in row.keys() else None
    return QuestRecord(
        id=row["id"],
        user_id=row["user_id"],
        status=row["status"],
        quest=Quest.model_validate_json(row["data"]),
        feedback=FeedbackIn.model_validate_json(row["feedback"]) if row["feedback"] else None,
        created_at=row["created_at"],
        model=row["model"],
        context=QuestContext.model_validate_json(context) if context else None,
    )


def add_quest(user_id: str, quest: Quest, model: str = "", context: QuestContext | None = None) -> QuestRecord:
    with connect() as conn:
        _migrate(conn)
        cur = conn.execute(
            "INSERT INTO quests (user_id, data, model, created_at, context) VALUES (?, ?, ?, ?, ?)",
            (user_id, quest.model_dump_json(), model, _now(),
             context.model_dump_json() if context is not None and not context.is_empty else None),
        )
        row = conn.execute("SELECT * FROM quests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_quest(row)


def get_quest(user_id: str, quest_id: int) -> QuestRecord | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM quests WHERE id = ? AND user_id = ?", (quest_id, user_id)
        ).fetchone()
    return _row_to_quest(row) if row else None


def delete_unstarted_quest(user_id: str, quest_id: int) -> str:
    """Remove a quest the user never started (replaced by a new one), as if it
    was never made. Returns "deleted", "missing" (already gone / not theirs),
    "rated" (finished or given up - kept) or "group" (a group quest copy - kept)."""
    with connect() as conn:
        row = conn.execute("SELECT feedback FROM quests WHERE id = ? AND user_id = ?", (quest_id, user_id)).fetchone()
        if row is None:
            return "missing"
        if row["feedback"] is not None:
            return "rated"
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'party_members'").fetchone() and conn.execute(
            "SELECT 1 FROM party_members WHERE quest_id = ?", (quest_id,)
        ).fetchone():
            return "group"
        for table in ("quest_logs", "quest_routes"):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                conn.execute(f"DELETE FROM {table} WHERE user_id = ? AND quest_id = ?", (user_id, quest_id))
        conn.execute("DELETE FROM quests WHERE id = ? AND user_id = ?", (quest_id, user_id))
    return "deleted"


def list_quests(user_id: str, limit: int = 20) -> list[QuestRecord]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM quests WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
    return [_row_to_quest(r) for r in rows]


def set_feedback(user_id: str, quest_id: int, feedback: FeedbackIn) -> QuestRecord | None:
    status = QuestStatus.COMPLETED if feedback.completed else QuestStatus.SKIPPED
    with connect() as conn:
        _migrate(conn)
        row = conn.execute(
            "SELECT created_at, completed_at FROM quests WHERE id = ? AND user_id = ?", (quest_id, user_id)
        ).fetchone()
        if row is None:
            return None
        now = _now()
        completed_at = None
        if feedback.completed:
            # Keep the first completion time (re-sending/editing a rating must not move
            # the streak day). Otherwise use when the app says it happened (it may sync
            # hours later), kept between the quest's creation and now.
            completed_at = row["completed_at"] or _completion_time(feedback.completed_at, row["created_at"], now)
        conn.execute(
            """UPDATE quests SET feedback = ?, status = ?, feedback_at = ?, completed_at = ?
               WHERE id = ? AND user_id = ?""",
            (feedback.model_dump_json(exclude={"completed_at"}), status.value, now, completed_at, quest_id, user_id),
        )
        row = conn.execute("SELECT * FROM quests WHERE id = ?", (quest_id,)).fetchone()
    return _row_to_quest(row)


def _completion_time(claimed: datetime | None, created_at: str, now: str) -> str:
    if claimed is None:
        return now
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    clamped = min(max(claimed.astimezone(timezone.utc), created), datetime.fromisoformat(now))
    return clamped.isoformat()


def completion_times(user_id: str) -> list[datetime]:
    """When each completed quest was completed (UTC)."""
    with connect() as conn:
        _migrate(conn)
        rows = conn.execute(
            """SELECT COALESCE(completed_at, feedback_at, created_at) AS at FROM quests
               WHERE user_id = ? AND status = 'completed'""",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        when = datetime.fromisoformat(r["at"])
        out.append(when if when.tzinfo else when.replace(tzinfo=timezone.utc))
    return out


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
