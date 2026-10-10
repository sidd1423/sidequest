"""Duolingo-style daily streak: one completed quest a day keeps it going.

Rules
- A day counts when you complete (not skip) at least one quest that day, in
  YOUR time zone (the app sends its UTC offset).
- Miss a day and the streak resets to 0 - unless you hold a streak freeze,
  which is used up automatically to cover that day. Frozen days keep the
  streak alive but don't add to it.
- Today never breaks the streak: until midnight it's just "at risk".
- Freezes: hold at most MAX_FREEZES. You get one free every FREEZE_EVERY
  streak days, or buy one for FREEZE_COST points (POST .../streak/freeze).
- Milestones (3, 7, 14, 30 ... days) are celebrated in the app.

Like rewards.py, everything is replayed from stored data (completion times +
freeze purchases), so nothing can drift out of sync and the rules can change
without a migration. Only freeze purchases need their own table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel

from . import db

MAX_FREEZES = 2
FREEZE_COST = 100  # points
FREEZE_EVERY = 7  # a free freeze every 7 streak days
MILESTONES = [3, 7, 14, 30, 50, 100, 180, 365, 500, 1000]
CALENDAR_DAYS = 400  # how far back the calendar data goes
MAX_TZ_OFFSET = 14 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS streak_freezes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    cost        INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_streak_freezes_user ON streak_freezes (user_id);
"""


def init_streaks() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


class Streak(BaseModel):
    current: int  # streak days (frozen days don't add)
    best: int
    extended_today: bool  # today already has a completed quest
    at_risk: bool  # a streak is running but today isn't done yet
    freezes: int  # held right now (0..max_freezes)
    max_freezes: int
    freeze_cost: int
    freeze_every: int
    spendable_points: int  # lifetime points minus points spent on freezes
    can_buy_freeze: bool
    next_milestone: int | None
    milestones: list[int]
    lost_streak: int  # length of the streak that broke most recently (0 if none / since rebuilt)
    today: date  # the user's local date used for all of the above
    completed_days: list[date]  # for the calendar (last CALENDAR_DAYS days)
    frozen_days: list[date]


@dataclass
class Replay:
    current: int = 0
    best: int = 0
    freezes: int = 0
    lost: int = 0
    bonus_days: int = 0  # completed days that extended a streak of 2+ (rewards' streak bonus)
    frozen: set[date] = field(default_factory=set)


def local_day(when: datetime, tz_offset_minutes: int = 0) -> date:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when.astimezone(timezone.utc) + timedelta(minutes=tz_offset_minutes)).date()


def local_today(tz_offset_minutes: int = 0) -> date:
    return local_day(datetime.now(timezone.utc), tz_offset_minutes)


def replay(completed: set[date], purchases: list[date], today: date) -> Replay:
    """Walk day by day from the first activity to today and apply the rules."""
    r = Replay()
    starts = [d for d in (min(completed, default=None), min(purchases, default=None)) if d is not None]
    if not starts:
        return r
    bought: dict[date, int] = {}
    for d in purchases:
        bought[d] = bought.get(d, 0) + 1
    day = min(starts)
    while day <= today:
        r.freezes = min(MAX_FREEZES, r.freezes + bought.get(day, 0))
        if day in completed:
            r.current += 1
            r.best = max(r.best, r.current)
            if r.current >= 2:
                r.bonus_days += 1
            if r.current % FREEZE_EVERY == 0:
                r.freezes = min(MAX_FREEZES, r.freezes + 1)
            if r.current > r.lost:
                r.lost = 0  # rebuilt past the old one - stop mentioning it
        elif day < today and r.current > 0:
            if r.freezes > 0:
                r.freezes -= 1
                r.frozen.add(day)
            else:
                r.lost, r.current = r.current, 0
        day += timedelta(days=1)
    return r


def completed_days(user_id: str, tz_offset_minutes: int = 0) -> set[date]:
    return {local_day(when, tz_offset_minutes) for when in db.completion_times(user_id)}


def purchase_days(user_id: str, tz_offset_minutes: int = 0) -> list[date]:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute("SELECT created_at FROM streak_freezes WHERE user_id = ?", (user_id,)).fetchall()
    return [local_day(datetime.fromisoformat(r["created_at"]), tz_offset_minutes) for r in rows]


def points_spent(user_id: str) -> int:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT COALESCE(SUM(cost), 0) FROM streak_freezes WHERE user_id = ?", (user_id,)).fetchone()
    return int(row[0])


def compute(user_id: str, lifetime_points: int, tz_offset_minutes: int = 0, today: date | None = None) -> Streak:
    today = today or local_today(tz_offset_minutes)
    done = completed_days(user_id, tz_offset_minutes)
    r = replay(done, purchase_days(user_id, tz_offset_minutes), today)
    spendable = max(0, lifetime_points - points_spent(user_id))
    since = today - timedelta(days=CALENDAR_DAYS)
    extended = today in done
    return Streak(
        current=r.current,
        best=r.best,
        extended_today=extended,
        at_risk=r.current > 0 and not extended,
        freezes=r.freezes,
        max_freezes=MAX_FREEZES,
        freeze_cost=FREEZE_COST,
        freeze_every=FREEZE_EVERY,
        spendable_points=spendable,
        can_buy_freeze=r.freezes < MAX_FREEZES and spendable >= FREEZE_COST,
        next_milestone=next((m for m in MILESTONES if m > r.current), None),
        milestones=MILESTONES,
        lost_streak=r.lost if r.current < r.lost else 0,
        today=today,
        completed_days=sorted(d for d in done if since <= d <= today),
        frozen_days=sorted(d for d in r.frozen if d >= since),
    )


class FreezeError(Exception):
    pass


def buy_freeze(user_id: str, lifetime_points: int, tz_offset_minutes: int = 0) -> None:
    """Spend FREEZE_COST points on a freeze. Raises FreezeError if not allowed."""
    current = compute(user_id, lifetime_points, tz_offset_minutes)
    if current.freezes >= MAX_FREEZES:
        raise FreezeError(f"You already have {MAX_FREEZES} streak freezes - that's the most you can hold")
    if current.spendable_points < FREEZE_COST:
        raise FreezeError(f"A streak freeze costs {FREEZE_COST} points - you have {current.spendable_points}")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO streak_freezes (user_id, cost, created_at) VALUES (?, ?, ?)",
            (user_id, FREEZE_COST, datetime.now(timezone.utc).isoformat()),
        )


def delete_user(user_id: str) -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM streak_freezes WHERE user_id = ?", (user_id,))
