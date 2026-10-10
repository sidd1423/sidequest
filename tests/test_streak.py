"""Duolingo-style daily streak: replay rules, time zones, freezes, API."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import db, streak
from backend.main import app, get_llm, get_retriever

D = date(2026, 10, 10)  # "today" in the replay tests


def days(*offsets):
    """Dates relative to D: days(0, 1) = today and yesterday."""
    return {D - timedelta(days=o) for o in offsets}


def test_no_activity():
    r = streak.replay(set(), [], D)
    assert (r.current, r.best, r.freezes, r.lost) == (0, 0, 0, 0)


def test_today_not_done_yet_keeps_the_streak():
    r = streak.replay(days(1, 2, 3), [], D)
    assert r.current == 3 and r.best == 3 and r.lost == 0


def test_today_counts():
    assert streak.replay(days(0, 1, 2), [], D).current == 3


def test_missed_day_resets_and_remembers_the_lost_streak():
    r = streak.replay(days(2, 3, 4, 5), [], D)  # yesterday missed
    assert r.current == 0 and r.best == 4 and r.lost == 4


def test_restart_after_a_gap():
    r = streak.replay(days(0, 1, 5, 6, 7), [], D)
    assert r.current == 2 and r.best == 3 and r.bonus_days == 1 + 2


def test_bought_freeze_covers_a_missed_day():
    r = streak.replay(days(0, 2, 3), [D - timedelta(days=3)], D)
    assert r.current == 3  # frozen day keeps it alive but doesn't add
    assert r.frozen == days(1) and r.freezes == 0


def test_freeze_bought_after_the_miss_is_too_late():
    r = streak.replay(days(0, 2, 3), [D], D)
    assert r.current == 1 and r.freezes == 1 and r.lost == 2


def test_two_freezes_cover_two_days_then_it_breaks():
    buy = [D - timedelta(days=10)] * 2
    assert streak.replay(days(3, 4), buy, D).current == 2  # 2 and 1 frozen
    r = streak.replay(days(4, 5), buy, D)  # 3, 2 frozen, 1 breaks
    assert r.current == 0 and r.lost == 2 and len(r.frozen) == 2


def test_freezes_are_capped():
    r = streak.replay(days(0), [D] * 5, D)
    assert r.freezes == streak.MAX_FREEZES


def test_free_freeze_every_seven_days():
    r = streak.replay(days(*range(0, 7)), [], D)
    assert r.current == 7 and r.freezes == 1
    r = streak.replay(days(*range(1, 8)), [], D)  # 7-day streak, today not done
    assert r.freezes == 1
    r = streak.replay(days(*range(2, 9)), [], D)  # missed yesterday: the earned freeze saves it
    assert r.current == 7 and r.freezes == 0 and r.frozen == days(1)


def test_no_freeze_used_without_a_streak():
    r = streak.replay(days(20), [D - timedelta(days=30)], D)
    assert r.current == 0 and r.freezes == 0  # used on day 19, gone; streak then broke on day 18
    r = streak.replay(set(), [D - timedelta(days=5)], D)
    assert r.freezes == 1  # nothing to protect - kept


def test_local_day_uses_the_offset():
    late_evening_toronto = datetime(2026, 10, 11, 2, 30, tzinfo=timezone.utc)  # 22:30 on the 10th, UTC-4
    assert streak.local_day(late_evening_toronto, -240) == date(2026, 10, 10)
    assert streak.local_day(late_evening_toronto, 0) == date(2026, 10, 11)


# --- API ---------------------------------------------------------------------

class FakeLLM:
    model = "fake"
    n = 0

    def complete(self, prompt, *, temperature=0.9):
        FakeLLM.n += 1
        return json.dumps({"title": f"Streak Quest {FakeLLM.n}", "summary": "Head outside and look around.",
                           "steps": ["go"], "estimated_minutes": 10, "difficulty": "extreme",
                           "energy_required": 3, "tags": ["nature"]})


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    app.dependency_overrides[get_llm] = FakeLLM
    app.dependency_overrides[get_retriever] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def signup(api, email="s@example.com"):
    s = api.post("/auth/signup", json={"email": email, "password": "longpassword"}).json()
    uid, h = s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}
    api.put(f"/users/{uid}/preferences", headers=h, json={"interests": ["nature"]})
    return uid, h


def complete(api, uid, h, **extra):
    qid = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]
    body = {"completed": True, "rating": 5, "time_logged_minutes": 30, **extra}
    assert api.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json=body).status_code == 200
    return qid


def test_streak_endpoint(api):
    uid, h = signup(api)
    s = api.get(f"/users/{uid}/streak", headers=h).json()
    assert s["current"] == 0 and not s["extended_today"] and not s["at_risk"]
    assert s["next_milestone"] == 3 and s["freezes"] == 0 and not s["can_buy_freeze"]

    complete(api, uid, h)
    s = api.get(f"/users/{uid}/streak", headers=h).json()
    assert s["current"] == 1 and s["extended_today"] and not s["at_risk"]
    assert s["completed_days"] == [s["today"]]


def test_rerating_does_not_move_the_streak_day(api):
    uid, h = signup(api)
    qid = complete(api, uid, h)
    with db.connect() as conn:  # pretend it was completed yesterday
        yday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute("UPDATE quests SET completed_at = ?, created_at = ? WHERE id = ?", (yday, yday, qid))
    api.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json={"completed": True, "rating": 3})
    s = api.get(f"/users/{uid}/streak", headers=h).json()
    assert s["current"] == 1 and s["at_risk"] and not s["extended_today"]
    with db.connect() as conn:
        stored = conn.execute("SELECT feedback FROM quests WHERE id = ?", (qid,)).fetchone()[0]
    assert "completed_at" not in json.loads(stored)


def test_offline_completion_time_is_used_but_clamped(api):
    uid, h = signup(api)
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    qid = complete(api, uid, h, completed_at=future)
    with db.connect() as conn:
        at = datetime.fromisoformat(conn.execute("SELECT completed_at FROM quests WHERE id = ?", (qid,)).fetchone()[0])
    assert at <= datetime.now(timezone.utc)
    # Un-completing clears it.
    api.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json={"completed": False})
    assert api.get(f"/users/{uid}/streak", headers=h).json()["current"] == 0


def test_timezone_offset_changes_today(api):
    uid, h = signup(api)
    complete(api, uid, h)
    utc = api.get(f"/users/{uid}/streak", headers=h).json()
    far = api.get(f"/users/{uid}/streak?tz_offset_minutes=840", headers=h).json()
    assert far["current"] == 1 and utc["current"] == 1
    assert api.get(f"/users/{uid}/streak?tz_offset_minutes=9999", headers=h).status_code == 422


def test_buying_freezes(api):
    uid, h = signup(api)
    assert api.post(f"/users/{uid}/streak/freeze", headers=h).status_code == 409  # 0 points
    complete(api, uid, h)
    complete(api, uid, h)  # 2 x (50 extreme + 30 minutes) = 160 points
    s = api.get(f"/users/{uid}/streak", headers=h).json()
    assert s["spendable_points"] == 160 and s["can_buy_freeze"]

    r = api.post(f"/users/{uid}/streak/freeze", headers=h)
    assert r.status_code == 201 and r.json()["freezes"] == 1 and r.json()["spendable_points"] == 60
    r = api.post(f"/users/{uid}/streak/freeze", headers=h)
    assert r.status_code == 409 and "costs 100 points" in r.json()["detail"]

    rw = api.get(f"/users/{uid}/rewards", headers=h).json()
    assert rw["points"] == 160 and rw["spendable_points"] == 60  # levels never go down

    other_uid, other_h = signup(api, "o@example.com")
    assert api.post(f"/users/{uid}/streak/freeze", headers=other_h).status_code == 403


def test_max_freezes(api, monkeypatch):
    uid, h = signup(api)
    for _ in range(4):
        complete(api, uid, h)  # 320 points
    assert api.post(f"/users/{uid}/streak/freeze", headers=h).status_code == 201
    assert api.post(f"/users/{uid}/streak/freeze", headers=h).status_code == 201
    r = api.post(f"/users/{uid}/streak/freeze", headers=h)
    assert r.status_code == 409 and "most you can hold" in r.json()["detail"]


def test_old_database_gets_the_new_column(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    import sqlite3
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE quests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'suggested', data TEXT NOT NULL, feedback TEXT, model TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, feedback_at TEXT);
        INSERT INTO quests (user_id, status, data, created_at, feedback_at)
        VALUES ('u1', 'completed', '{}', '2026-10-01T10:00:00+00:00', '2026-10-01T11:00:00+00:00');""")
    conn.commit()
    conn.close()
    db.init_db()
    assert db.completion_times("u1") == [datetime(2026, 10, 1, 11, tzinfo=timezone.utc)]
