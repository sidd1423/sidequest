"""Points, levels, streaks and badges.

Everything is computed from data the app already stores (quests, feedback,
quest-log notes/photos), so there's nothing extra to keep in sync and the
rules can change without migrating anything.

Points per quest
- Completed: base points by difficulty (easy 10, moderate 20, challenging 35,
  extreme 50) + 1 per minute spent outside (max 30) + 5 if you added a photo
  + 2 if you wrote a note.
- Didn't finish but spent time on it: 5 ("gave it a go").
- Streaks: every day in a row (after the first) with a completed quest: +10.
  Streak rules (days in your time zone, streak freezes) live in streak.py.
- Points spent on streak freezes come off `spendable_points`, never off
  `points` (so you never lose a level by buying a freeze).

Levels every few hundred points; badges for milestones.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from . import db, streak as streak_mod
from .schemas import FeedbackIn, Quest

DIFFICULTY_POINTS = {"easy": 10, "moderate": 20, "challenging": 35, "extreme": 50}
MAX_MINUTE_POINTS = 30
PHOTO_POINTS = 5
NOTE_POINTS = 2
TRIED_POINTS = 5
STREAK_DAY_POINTS = 10

# (points needed, name)
LEVELS = [
    (0, "Homebody"),
    (50, "Stroller"),
    (150, "Wanderer"),
    (300, "Explorer"),
    (500, "Trailblazer"),
    (800, "Adventurer"),
    (1200, "Pathfinder"),
    (1800, "Legend"),
]


class PointsEntry(BaseModel):
    quest_id: int
    title: str
    points: int
    reasons: list[str]
    date: datetime


class Badge(BaseModel):
    id: str
    name: str
    description: str
    earned: bool
    progress: int  # current value
    goal: int


class Rewards(BaseModel):
    points: int
    level: int  # 1-based
    level_name: str
    level_floor: int  # points where this level started
    next_level_at: int | None  # None at the top level
    next_level_name: str | None
    current_streak: int  # see streak.py (freezes keep it alive)
    best_streak: int
    spendable_points: int  # points minus what was spent on streak freezes
    completed: int
    minutes_outside: int
    photos: int
    badges: list[Badge]
    recent: list[PointsEntry]  # newest first


def quest_points(quest: Quest, fb: FeedbackIn, photos: int = 0, notes: int = 0) -> tuple[int, list[str]]:
    """Points one quest earns, with the reasons shown in the app."""
    minutes = fb.time_logged_minutes or 0
    if fb.completed:
        base = DIFFICULTY_POINTS.get(quest.difficulty.value, 10)
        points, reasons = base, [f"+{base} {quest.difficulty.value} quest"]
        if minutes:
            m = min(minutes, MAX_MINUTE_POINTS)
            points += m
            reasons.append(f"+{m} minutes outside")
        if photos:
            points += PHOTO_POINTS
            reasons.append(f"+{PHOTO_POINTS} photo")
        if notes:
            points += NOTE_POINTS
            reasons.append(f"+{NOTE_POINTS} note")
        return points, reasons
    if minutes > 0:
        return TRIED_POINTS, [f"+{TRIED_POINTS} gave it a go"]
    return 0, []


def _level(points: int) -> tuple[int, str, int, int | None, str | None]:
    idx = max(i for i, (need, _) in enumerate(LEVELS) if points >= need)
    floor, name = LEVELS[idx]
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    return idx + 1, name, floor, (nxt[0] if nxt else None), (nxt[1] if nxt else None)


def _badges(completed: int, minutes: int, photos: int, best_streak: int, hard: int) -> list[Badge]:
    specs = [
        ("first_quest", "First steps", "Complete your first quest", completed, 1),
        ("five_quests", "Getting out there", "Complete 5 quests", completed, 5),
        ("twenty_five", "Regular", "Complete 25 quests", completed, 25),
        ("hundred_minutes", "Fresh air", "Spend 100 minutes outside on quests", minutes, 100),
        ("photographer", "Snapshot", "Add a photo to a quest", photos, 1),
        ("streak_3", "On a roll", "Complete quests 3 days in a row", best_streak, 3),
        ("streak_7", "Week warrior", "Complete quests 7 days in a row", best_streak, 7),
        ("streak_30", "Unstoppable", "Keep a 30-day streak", best_streak, 30),
        ("challenger", "Challenger", "Complete a challenging or extreme quest", hard, 1),
    ]
    return [
        Badge(id=i, name=n, description=d, earned=value >= goal, progress=min(value, goal), goal=goal)
        for i, n, d, value, goal in specs
    ]


def compute(user_id: str, today: date | None = None, tz_offset_minutes: int = 0) -> Rewards:
    today = today or streak_mod.local_today(tz_offset_minutes)
    rows = db.feedback_rows(user_id)
    journal = db.journal_counts(user_id)
    entries: list[PointsEntry] = []
    days: set[date] = set()
    completed = minutes = hard = 0
    for quest_id, quest, fb, when in rows:
        photos, notes = journal.get(quest_id, (0, 0))
        pts, reasons = quest_points(quest, fb, photos, notes)
        minutes += fb.time_logged_minutes or 0
        if fb.completed:
            completed += 1
            days.add(streak_mod.local_day(when, tz_offset_minutes))
            hard += quest.difficulty.value in ("challenging", "extreme")
        if pts:
            entries.append(PointsEntry(quest_id=quest_id, title=quest.title, points=pts, reasons=reasons, date=when))

    run = streak_mod.replay(days, streak_mod.purchase_days(user_id, tz_offset_minutes), today)
    current, best = run.current, run.best
    points = sum(e.points for e in entries) + run.bonus_days * STREAK_DAY_POINTS
    level, name, floor, next_at, next_name = _level(points)
    photo_total = sum(p for p, _ in journal.values())
    entries.sort(key=lambda e: e.date, reverse=True)
    return Rewards(
        points=points, level=level, level_name=name, level_floor=floor,
        next_level_at=next_at, next_level_name=next_name,
        current_streak=current, best_streak=best,
        spendable_points=max(0, points - streak_mod.points_spent(user_id)),
        completed=completed, minutes_outside=minutes, photos=photo_total,
        badges=_badges(completed, minutes, photo_total, best, hard),
        recent=entries[:20],
    )
