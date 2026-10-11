"""The path a user walked while doing a quest (recorded by the app's GPS tracker).

One route per quest in sidequest.db (`quest_routes`). The app uploads the
whole route with PUT (safe to re-send - the offline outbox relies on that),
so the server just stores the latest copy and works out distance/duration.
Only the quest's owner can read it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db
from .local_context import distance_m
from .schemas import QuestRecord, RouteSummary

MAX_POINTS = 20_000       # ~5.5 h at one point per second - far more than a 30 min quest needs
MAX_ACCURACY_M = 75       # points less accurate than this don't count toward the distance
MAX_SPEED_MS = 15         # ~54 km/h: faster jumps between points are GPS glitches

SCHEMA = """
CREATE TABLE IF NOT EXISTS quest_routes (
    quest_id     INTEGER PRIMARY KEY,
    user_id      TEXT NOT NULL,
    points       TEXT NOT NULL,           -- JSON [{lat, lon, t, accuracy_m}]
    distance_m   INTEGER NOT NULL,
    duration_s   INTEGER NOT NULL,
    started_at   TEXT,
    ended_at     TEXT,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_routes_user ON quest_routes (user_id);
"""


class RoutePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    t: datetime  # when the point was recorded
    accuracy_m: float | None = Field(None, ge=0, le=100_000)

    @field_validator("t")
    @classmethod
    def aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


class RouteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[RoutePoint] = Field(..., max_length=MAX_POINTS)


class RouteOut(BaseModel):
    quest_id: int
    points: list[RoutePoint]
    distance_m: int
    duration_seconds: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    updated_at: datetime


def init_routes() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def measure(points: list[RoutePoint]) -> tuple[int, int]:
    """(distance in metres, duration in seconds) - skipping inaccurate fixes and GPS jumps."""
    pts = sorted(points, key=lambda p: p.t)
    if len(pts) < 2:
        return 0, 0
    total, last = 0.0, None
    for p in pts:
        if p.accuracy_m is not None and p.accuracy_m > MAX_ACCURACY_M:
            continue
        if last is not None:
            d = distance_m(last.lat, last.lon, p.lat, p.lon)
            secs = (p.t - last.t).total_seconds()
            if secs > 0 and d / secs > MAX_SPEED_MS:
                continue  # glitch: don't count it and don't move `last`
            total += d
        last = p
    return int(round(total)), int((pts[-1].t - pts[0].t).total_seconds())


def save(user_id: str, quest_id: int, route: RouteIn) -> RouteOut:
    if db.get_quest(user_id, quest_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quest not found")
    pts = sorted(route.points, key=lambda p: p.t)
    dist, dur = measure(pts)
    now = datetime.now(timezone.utc).isoformat()
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """INSERT INTO quest_routes (quest_id, user_id, points, distance_m, duration_s, started_at, ended_at,
                                         updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(quest_id) DO UPDATE SET points = excluded.points, distance_m = excluded.distance_m,
                   duration_s = excluded.duration_s, started_at = excluded.started_at,
                   ended_at = excluded.ended_at, updated_at = excluded.updated_at""",
            (quest_id, user_id, json.dumps([p.model_dump(mode="json") for p in pts]), dist, dur,
             pts[0].t.isoformat() if pts else None, pts[-1].t.isoformat() if pts else None, now),
        )
    return get(user_id, quest_id)  # type: ignore[return-value]


def get(user_id: str, quest_id: int) -> RouteOut | None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT * FROM quest_routes WHERE quest_id = ? AND user_id = ?",
                           (quest_id, user_id)).fetchone()
    if row is None:
        return None
    return RouteOut(quest_id=quest_id, points=json.loads(row["points"]), distance_m=row["distance_m"],
                    duration_seconds=row["duration_s"], started_at=row["started_at"], ended_at=row["ended_at"],
                    updated_at=row["updated_at"])


def delete(user_id: str, quest_id: int) -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM quest_routes WHERE quest_id = ? AND user_id = ?", (quest_id, user_id))


def attach(records: list[QuestRecord]) -> list[QuestRecord]:
    """Fill QuestRecord.route (distance/duration/point count) for quests that have a route."""
    if not records:
        return records
    ids = [r.id for r in records]
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            f"""SELECT quest_id, user_id, distance_m, duration_s, json_array_length(points) AS n
                FROM quest_routes WHERE quest_id IN ({','.join('?' * len(ids))})""", ids).fetchall()
    found = {(r["quest_id"], r["user_id"]): r for r in rows}
    for rec in records:
        r = found.get((rec.id, rec.user_id))
        if r is not None:
            rec.route = RouteSummary(distance_m=r["distance_m"], duration_seconds=r["duration_s"], points=r["n"])
    return records
