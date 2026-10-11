"""Per-user sidequest history: data/user_history.db

Holds each user's recent sidequests and how they went, so the next quest can
lean toward what they loved and steer clear of what they disliked or skipped.

* Every generated quest is added here (as well as to the quest library).
* Each user keeps their 10 most recent quests; older ones are pruned, except
  quests with logged time (time_logged_minutes > 0), which are always kept.
* Every quest-library row with time_logged_minutes > 0 is copied in: all of
  them on startup (backfill), and immediately when feedback logs time on a
  quest that had already been pruned from the user's last 10.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .library import _category
from .schemas import FeedbackIn, PastQuest, Quest

log = logging.getLogger("sidequest.history")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "user_history.db"
MAX_PER_USER = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_quest_history (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              TEXT    NOT NULL,
    app_quest_id         INTEGER UNIQUE,                 -- quests.id in sidequest.db
    title                TEXT    NOT NULL,
    quest_text           TEXT    NOT NULL,
    category             TEXT    NOT NULL,
    duration_minutes     INTEGER NOT NULL,
    difficulty           TEXT    NOT NULL,
    tags                 TEXT    NOT NULL DEFAULT '[]',  -- JSON array
    quest_json           TEXT,
    model                TEXT,
    status               TEXT    NOT NULL DEFAULT 'suggested'
                         CHECK (status IN ('suggested', 'completed', 'skipped')),
    completed            INTEGER CHECK (completed IN (0, 1)),
    rating               INTEGER CHECK (rating BETWEEN 1 AND 5),
    feedback_comment     TEXT,
    time_logged_minutes  INTEGER NOT NULL DEFAULT 0 CHECK (time_logged_minutes >= 0),
    created_at           TEXT    NOT NULL,
    feedback_at          TEXT,
    copied_from_library  INTEGER NOT NULL DEFAULT 0      -- 1 = backfilled from quest_library.db
);
CREATE INDEX IF NOT EXISTS history_user_idx ON user_quest_history (user_id, created_at);
"""


def history_path() -> Path:
    return Path(os.getenv("HISTORY_PATH") or DEFAULT_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def init_history(path: Path | None = None, library_db: Path | None = None) -> int:
    """Create the history database if needed and copy in every quest-library
    entry with time logged. Returns how many rows were copied this time."""
    path = Path(path or history_path())
    conn = _connect(path)
    try:
        if library_db is None:
            from .library import library_path

            library_db = library_path()
        if not Path(library_db).exists():
            return 0
        return copy_logged_from_library(conn, Path(library_db))
    finally:
        conn.close()


def copy_logged_from_library(conn: sqlite3.Connection, library_db: Path,
                             app_quest_id: int | None = None) -> int:
    """Copy (or refresh) quest-library rows with time_logged_minutes > 0 -
    all of them, or just the one for `app_quest_id`."""
    lib = sqlite3.connect(f"file:{library_db}?mode=ro", uri=True)
    lib.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in lib.execute("PRAGMA table_info(quests)")}
        if "time_logged_minutes" not in cols:
            return 0
        sql = "SELECT * FROM quests WHERE time_logged_minutes > 0 AND user_id IS NOT NULL"
        params: tuple = ()
        if app_quest_id is not None:
            sql += " AND app_quest_id = ?"
            params = (app_quest_id,)
        rows = lib.execute(sql, params).fetchall()
    finally:
        lib.close()

    copied = 0
    for r in rows:
        cur = conn.execute(
            """
            INSERT INTO user_quest_history (
                user_id, app_quest_id, title, quest_text, category, duration_minutes, difficulty,
                tags, quest_json, model, status, completed, rating, feedback_comment,
                time_logged_minutes, created_at, feedback_at, copied_from_library)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(app_quest_id) DO UPDATE SET
                status = excluded.status, completed = excluded.completed, rating = excluded.rating,
                feedback_comment = excluded.feedback_comment,
                time_logged_minutes = excluded.time_logged_minutes, feedback_at = excluded.feedback_at
            WHERE user_quest_history.feedback_at IS NULL
               OR user_quest_history.feedback_at < excluded.feedback_at
            """,
            (r["user_id"], r["app_quest_id"], r["title"] or r["quest_text"][:120], r["quest_text"],
             r["category"], r["duration_minutes"], r["difficulty"], r["tags"], r["quest_json"],
             r["model"], r["status"] or "completed", r["completed"], r["rating"],
             r["feedback_comment"], r["time_logged_minutes"], r["created_at"], r["feedback_at"]),
        )
        copied += cur.rowcount
    conn.commit()
    if copied:
        log.info("Copied %d quest-library entries with logged time into the user history", copied)
    return copied


def _prune(conn: sqlite3.Connection, user_id: str) -> int:
    """Keep the user's MAX_PER_USER most recent quests; older ones go unless
    they have logged time."""
    cur = conn.execute(
        """
        DELETE FROM user_quest_history
        WHERE user_id = ? AND time_logged_minutes = 0 AND id NOT IN (
            SELECT id FROM user_quest_history WHERE user_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
        )
        """,
        (user_id, user_id, MAX_PER_USER),
    )
    return cur.rowcount


def add_quest(app_quest_id: int, user_id: str, quest: Quest, model: str = "",
              path: Path | None = None) -> None:
    conn = _connect(Path(path or history_path()))
    try:
        conn.execute(
            """
            INSERT INTO user_quest_history (
                user_id, app_quest_id, title, quest_text, category, duration_minutes, difficulty,
                tags, quest_json, model, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'suggested', ?)
            ON CONFLICT(app_quest_id) DO NOTHING
            """,
            (user_id, app_quest_id, quest.title, f"{quest.title}: {quest.summary}", _category(quest),
             quest.estimated_minutes, quest.difficulty.value, json.dumps(quest.tags),
             quest.model_dump_json(), model, _now()),
        )
        _prune(conn, user_id)
        conn.commit()
    finally:
        conn.close()


def record_feedback(app_quest_id: int, feedback: FeedbackIn, path: Path | None = None,
                    library_db: Path | None = None) -> bool:
    """Store feedback on the user's history row. If the quest is no longer in
    the history (pruned from the last 10) and the feedback logs time, copy it
    back in from the quest library right away - every entry with logged time
    belongs in the history. Call this after library.record_feedback()."""
    conn = _connect(Path(path or history_path()))
    try:
        cur = conn.execute(
            """
            UPDATE user_quest_history SET
                status = ?, completed = ?, rating = ?, feedback_comment = ?,
                time_logged_minutes = ?, feedback_at = ?
            WHERE app_quest_id = ?
            """,
            ("completed" if feedback.completed else "skipped", int(feedback.completed),
             feedback.rating, feedback.comment or None,
             feedback.time_logged_minutes or 0, _now(), app_quest_id),
        )
        conn.commit()
        if cur.rowcount > 0:
            return True
        if not feedback.time_logged_minutes:
            return False
        if library_db is None:
            from .library import library_path

            library_db = library_path()
        if not Path(library_db).exists():
            return False
        copied = copy_logged_from_library(conn, Path(library_db), app_quest_id=app_quest_id)
        if copied:
            log.info("Quest %s was outside the user's last 10 - copied back in because it now has logged time",
                     app_quest_id)
        return copied > 0
    finally:
        conn.close()


def delete_quest(app_quest_id: int, path: Path | None = None) -> bool:
    """Forget one quest (deleted before it was started)."""
    path = Path(path or history_path())
    if not path.exists():
        return False
    conn = _connect(path)
    try:
        n = conn.execute("DELETE FROM user_quest_history WHERE app_quest_id = ?", (app_quest_id,)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def delete_user(user_id: str, path: Path | None = None) -> int:
    """Remove a deleted account's quest history."""
    path = Path(path or history_path())
    if not path.exists():
        return 0
    conn = _connect(path)
    try:
        n = conn.execute("DELETE FROM user_quest_history WHERE user_id = ?", (user_id,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def recent(user_id: str, limit: int = MAX_PER_USER, path: Path | None = None) -> list[PastQuest]:
    """The user's most recent sidequests (newest first) with their feedback."""
    path = Path(path or history_path())
    if not path.exists():
        return []
    conn = _connect(path)
    try:
        rows = conn.execute(
            """SELECT * FROM user_quest_history WHERE user_id = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        PastQuest(
            app_quest_id=r["app_quest_id"], title=r["title"], quest_text=r["quest_text"],
            category=r["category"], duration_minutes=r["duration_minutes"], difficulty=r["difficulty"],
            tags=json.loads(r["tags"] or "[]"), status=r["status"],
            completed=None if r["completed"] is None else bool(r["completed"]),
            rating=r["rating"], comment=r["feedback_comment"] or "",
            time_logged_minutes=r["time_logged_minutes"], created_at=r["created_at"],
        )
        for r in rows
    ]
