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

from .schemas import PreferencesIn, PreferencesOut

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id     TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
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
        **json.loads(row["data"]),
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
