"""Quest journal: notes and photos a user adds to a quest.

Stored in the main database (DATABASE_PATH), table `quest_logs`. Photos are
kept as BLOBs (resized by the app before upload, max MAX_PHOTO_BYTES) so
there's nothing extra to back up or clean up.

Every entry carries a `client_id` chosen by the app: re-sending the same
entry (the offline outbox retrying) updates it instead of duplicating it.
"""

from __future__ import annotations

import base64
import binascii
import sqlite3
from datetime import datetime

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS quest_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    quest_id    INTEGER NOT NULL,
    client_id   TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('note', 'photo')),
    text        TEXT NOT NULL DEFAULT '',
    image       BLOB,
    mime        TEXT,
    step        INTEGER,
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_quest_logs_quest ON quest_logs (user_id, quest_id, created_at);
"""

MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/gif"}


def init_journal() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(quest_logs)")}
        if "step" not in columns:  # added with the step-by-step quest mode
            conn.execute("ALTER TABLE quest_logs ADD COLUMN step INTEGER")


class LogIn(BaseModel):
    """A note (text) or a photo (image_base64 + mime, optional caption in text)."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    kind: str = Field(..., pattern="^(note|photo)$")
    text: str = Field("", max_length=2000)
    image_base64: str | None = None
    mime: str | None = None
    created_at: datetime | None = None  # when it was written on the device (may be offline, earlier)
    step: int | None = Field(None, ge=1, le=100)  # quest step it was taken at (1-based), for the album

    @model_validator(mode="after")
    def _check(self) -> "LogIn":
        if self.kind == "note" and not self.text.strip():
            raise ValueError("A note needs some text")
        if self.kind == "photo":
            if not self.image_base64:
                raise ValueError("A photo needs image_base64")
            if self.mime not in ALLOWED_MIME:
                raise ValueError(f"Unsupported image type {self.mime!r}")
        return self


class LogOut(BaseModel):
    id: int
    quest_id: int
    client_id: str
    kind: str
    text: str
    has_photo: bool
    mime: str | None = None
    step: int | None = None
    created_at: datetime


def _row(r: sqlite3.Row) -> LogOut:
    return LogOut(
        id=r["id"], quest_id=r["quest_id"], client_id=r["client_id"], kind=r["kind"], text=r["text"],
        has_photo=r["has_photo"] == 1, mime=r["mime"], step=r["step"], created_at=r["created_at"],
    )


_COLUMNS = "id, quest_id, client_id, kind, text, mime, step, created_at, image IS NOT NULL AS has_photo"


def _quest_belongs(conn: sqlite3.Connection, user_id: str, quest_id: int) -> None:
    if conn.execute("SELECT 1 FROM quests WHERE id = ? AND user_id = ?", (quest_id, user_id)).fetchone() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quest not found")


def add(user_id: str, quest_id: int, entry: LogIn) -> LogOut:
    image = None
    if entry.kind == "photo":
        try:
            image = base64.b64decode(entry.image_base64 or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "image_base64 isn't valid base64") from exc
        if len(image) > MAX_PHOTO_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Photo is larger than 5 MB")
    created = (entry.created_at or datetime.now().astimezone()).isoformat()
    with db.connect() as conn:
        _quest_belongs(conn, user_id, quest_id)
        conn.execute(
            """INSERT INTO quest_logs (user_id, quest_id, client_id, kind, text, image, mime, step, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (user_id, client_id) DO UPDATE SET text = excluded.text""",
            (user_id, quest_id, entry.client_id, entry.kind, entry.text.strip(), image, entry.mime, entry.step,
             created),
        )
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM quest_logs WHERE user_id = ? AND client_id = ?", (user_id, entry.client_id)
        ).fetchone()
    return _row(row)


def list_for_quest(user_id: str, quest_id: int) -> list[LogOut]:
    with db.connect() as conn:
        _quest_belongs(conn, user_id, quest_id)
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM quest_logs WHERE user_id = ? AND quest_id = ? ORDER BY created_at, id",
            (user_id, quest_id),
        ).fetchall()
    return [_row(r) for r in rows]


def photo(user_id: str, log_id: int) -> tuple[bytes, str]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT image, mime FROM quest_logs WHERE id = ? AND user_id = ? AND image IS NOT NULL", (log_id, user_id)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return row["image"], row["mime"] or "image/jpeg"


def delete(user_id: str, client_id: str) -> bool:
    with db.connect() as conn:
        return conn.execute(
            "DELETE FROM quest_logs WHERE user_id = ? AND client_id = ?", (user_id, client_id)
        ).rowcount > 0
