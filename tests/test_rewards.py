"""Points, levels, streaks and badges."""

import base64
import json
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import db, rewards
from backend.main import app, get_llm, get_retriever
from backend.schemas import FeedbackIn, Quest


def q(difficulty="easy"):
    return Quest(title="Some Quest", summary="Do a small thing outside.", steps=["go"], estimated_minutes=10,
                 difficulty=difficulty, energy_required=2)


@pytest.mark.parametrize("difficulty,fb,photos,notes,expected", [
    ("easy", FeedbackIn(completed=True, rating=4), 0, 0, 10),
    ("moderate", FeedbackIn(completed=True, rating=4, time_logged_minutes=12), 0, 0, 32),
    ("extreme", FeedbackIn(completed=True, rating=5, time_logged_minutes=90), 1, 3, 50 + 30 + 5 + 2),
    ("easy", FeedbackIn(completed=False, time_logged_minutes=4), 2, 0, 5),
    ("easy", FeedbackIn(completed=False), 0, 0, 0),
])
def test_quest_points(difficulty, fb, photos, notes, expected):
    assert rewards.quest_points(q(difficulty), fb, photos, notes)[0] == expected


def test_streaks():
    d = date(2026, 10, 10)
    days = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 9), d}
    current, best, extra = rewards._streaks(days, d)
    assert (current, best, extra) == (2, 3, 3)
    assert rewards._streaks({date(2026, 10, 9)}, d)[0] == 1  # yesterday still counts
    assert rewards._streaks({date(2026, 10, 7)}, d)[0] == 0


def test_levels():
    assert rewards._level(0)[:2] == (1, "Homebody")
    assert rewards._level(149)[:2] == (2, "Stroller")
    lvl, name, floor, nxt, nxt_name = rewards._level(150)
    assert (lvl, name, floor, nxt, nxt_name) == (3, "Wanderer", 150, 300, "Explorer")
    assert rewards._level(99999)[3] is None


class FakeLLM:
    model = "fake"
    n = 0

    def complete(self, prompt, *, temperature=0.9):
        FakeLLM.n += 1
        return json.dumps({"title": f"Quest {FakeLLM.n}", "summary": "Head outside and look around you.",
                           "steps": ["go"], "estimated_minutes": 10, "difficulty": "challenging",
                           "energy_required": 3, "tags": ["nature"]})


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    app.dependency_overrides[get_llm] = FakeLLM
    app.dependency_overrides[get_retriever] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_rewards_endpoint(api):
    s = api.post("/auth/signup", json={"email": "r@example.com", "password": "longpassword"}).json()
    uid, h = s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}
    api.put(f"/users/{uid}/preferences", headers=h, json={"interests": ["nature"]})

    empty = api.get(f"/users/{uid}/rewards", headers=h).json()
    assert empty["points"] == 0 and empty["level_name"] == "Homebody" and empty["recent"] == []
    assert not any(b["earned"] for b in empty["badges"])

    q1 = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]
    q2 = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]
    api.post(f"/users/{uid}/quests/{q1}/logs", headers=h, json={
        "client_id": "photo-r001", "kind": "photo", "mime": "image/png",
        "image_base64": base64.b64encode(b"\x89PNG fake").decode()})
    api.post(f"/users/{uid}/quests/{q1}/feedback", headers=h,
             json={"completed": True, "rating": 5, "time_logged_minutes": 15})
    api.post(f"/users/{uid}/quests/{q2}/feedback", headers=h, json={"completed": False, "time_logged_minutes": 3})

    r = api.get(f"/users/{uid}/rewards", headers=h).json()
    assert r["points"] == 35 + 15 + 5 + 5  # challenging + minutes + photo, plus "gave it a go"
    assert r["level_name"] == "Stroller" and r["next_level_at"] == 150
    assert r["current_streak"] == 1 and r["completed"] == 1 and r["photos"] == 1
    earned = {b["id"] for b in r["badges"] if b["earned"]}
    assert earned == {"first_quest", "photographer", "challenger"}
    assert [e["points"] for e in r["recent"]] == [5, 55]
    assert "+5 photo" in r["recent"][1]["reasons"]

    other = api.post("/auth/signup", json={"email": "o@example.com", "password": "longpassword"}).json()
    assert api.get(f"/users/{uid}/rewards", headers={"Authorization": f"Bearer {other['token']}"}).status_code == 403


def test_streak_bonus(monkeypatch):
    rows = [(i, q(), FeedbackIn(completed=True, rating=4), datetime(2026, 10, d, 12, tzinfo=timezone.utc))
            for i, d in enumerate([8, 9, 10], 1)]
    monkeypatch.setattr(db, "feedback_rows", lambda uid: rows)
    monkeypatch.setattr(db, "journal_counts", lambda uid: {})
    r = rewards.compute("u_x", today=date(2026, 10, 10))
    assert r.current_streak == 3 and r.points == 3 * 10 + 2 * rewards.STREAK_DAY_POINTS
    assert any(b.id == "streak_3" and b.earned for b in r.badges)
