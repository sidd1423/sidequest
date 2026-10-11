"""Group quests: invite friends, they join, the host starts one quest for everyone."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import db, friends
from backend.main import app, get_llm, get_retriever


class FakeLLM:
    model = "fake"
    prompts: list[str] = []

    def complete(self, prompt, *, temperature=0.9):
        FakeLLM.prompts.append(prompt)
        return json.dumps({"title": f"Park Relay {len(FakeLLM.prompts)}",
                           "summary": "Race each other around the park in a relay.",
                           "steps": ["Meet at the gate", "Run the loop in turns"], "estimated_minutes": 15,
                           "difficulty": "easy", "energy_required": 3, "tags": ["social"]})


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    FakeLLM.prompts = []
    app.dependency_overrides[get_llm] = FakeLLM
    app.dependency_overrides[get_retriever] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def person(api, email, name):
    s = api.post("/auth/signup", json={"email": email, "name": name, "password": "longpassword"}).json()
    uid, h = s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}
    api.put(f"/users/{uid}/preferences", headers=h, json={"interests": ["nature"]})
    return uid, h


def befriend(api, a, b):
    (ua, ha), (ub, hb) = a, b
    email = api.get("/auth/me", headers=hb).json()["email"]
    rid = api.post(f"/users/{ua}/friends/requests", headers=ha, json={"email": email}).json()["request_id"]
    assert api.post(f"/users/{ub}/friends/requests/{rid}/accept", headers=hb).status_code == 204


@pytest.fixture()
def crew(api):
    host, sam, ria, stranger = (person(api, f"{n}@example.com", n.title()) for n in ("host", "sam", "ria", "zed"))
    befriend(api, host, sam)
    befriend(api, host, ria)
    return host, sam, ria, stranger


def test_invite_join_start(api, crew):
    (h, hh), (s, sh), (r, rh), _ = crew
    created = api.post(f"/users/{h}/parties", headers=hh,
                       json={"friend_ids": [s, r], "settings": {"duration_minutes": 20}})
    assert created.status_code == 201
    party = created.json()
    pid = party["id"]
    assert party["status"] == "open" and party["my_status"] == "host" and party["joined"] == 1
    assert [(m["name"], m["status"]) for m in party["members"]] == [("Host", "joined"), ("Ria", "invited"), ("Sam", "invited")]

    # Sam sees the invite.
    invites = api.get(f"/users/{s}/parties", headers=sh).json()
    assert [(p["id"], p["my_status"], p["host_name"]) for p in invites] == [(pid, "invited", "Host")]

    # Can't start alone.
    r1 = api.post(f"/users/{h}/parties/{pid}/start", headers=hh)
    assert r1.status_code == 409 and "at least one friend" in r1.json()["detail"]

    assert api.post(f"/users/{s}/parties/{pid}/join", headers=sh).json()["my_status"] == "joined"
    assert api.post(f"/users/{s}/parties/{pid}/join", headers=sh).status_code == 409  # already joined
    assert api.post(f"/users/{s}/parties/{pid}/start", headers=sh).status_code == 403  # host only

    started = api.post(f"/users/{h}/parties/{pid}/start", headers=hh).json()
    assert started["status"] == "started" and started["size"] == 2 and started["my_quest_id"]
    assert started["quest_title"] == "Park Relay 1"
    assert len(FakeLLM.prompts) == 1  # ONE quest for the group
    assert "exactly 2 friends will do this quest TOGETHER" in FakeLLM.prompts[0]
    assert "Takes between 5 and 20 minutes" in FakeLLM.prompts[0]  # the host's settings
    assert "Works for this group right now: pair" in FakeLLM.prompts[0]

    host_q = api.get(f"/users/{h}/quests", headers=hh).json()[0]
    sam_q = api.get(f"/users/{s}/quests", headers=sh).json()[0]
    assert host_q["quest"] == sam_q["quest"] and host_q["id"] != sam_q["id"]
    assert sam_q["party"]["size"] == 2 and sam_q["party"]["host_id"] == h
    assert {(m["name"], m["status"]) for m in sam_q["party"]["members"]} == {
        ("Host", "joined"), ("Sam", "joined"), ("Ria", "invited")}

    # Each rates their own copy.
    fb = api.post(f"/users/{s}/quests/{sam_q['id']}/feedback", headers=sh, json={"completed": True, "rating": 5})
    assert fb.json()["party"]["party_id"] == pid
    assert api.get(f"/users/{h}/quests", headers=hh).json()[0]["status"] == "suggested"

    # Ria joins late and gets the same quest; the size it was made for stays 2.
    late = api.post(f"/users/{r}/parties/{pid}/join", headers=rh).json()
    assert late["my_quest_id"] and late["joined"] == 3 and late["size"] == 2
    ria_q = api.get(f"/users/{r}/quests", headers=rh).json()[0]
    assert ria_q["quest"]["title"] == "Park Relay 1" and len(FakeLLM.prompts) == 1

    assert api.post(f"/users/{h}/parties/{pid}/start", headers=hh).status_code == 409  # only once


def test_decline_and_cancel(api, crew):
    (h, hh), (s, sh), (r, rh), _ = crew
    pid = api.post(f"/users/{h}/parties", headers=hh, json={"friend_ids": [s, r]}).json()["id"]
    declined = api.post(f"/users/{r}/parties/{pid}/decline", headers=rh).json()
    assert declined["my_status"] == "declined"
    assert api.get(f"/users/{r}/parties", headers=rh).json() == []  # gone from Ria's list
    host_view = api.get(f"/users/{h}/parties", headers=hh).json()[0]
    assert {m["name"]: m["status"] for m in host_view["members"]}["Ria"] == "declined"

    assert api.delete(f"/users/{s}/parties/{pid}", headers=sh).status_code == 403
    assert api.delete(f"/users/{h}/parties/{pid}", headers=hh).status_code == 204
    assert api.get(f"/users/{s}/parties", headers=sh).json() == []
    assert api.post(f"/users/{s}/parties/{pid}/join", headers=sh).status_code == 404


def test_only_friends_and_members(api, crew):
    (h, hh), (s, sh), _, (z, zh) = crew
    r = api.post(f"/users/{h}/parties", headers=hh, json={"friend_ids": [z]})
    assert r.status_code == 422 and "your friends" in r.json()["detail"]
    assert api.post(f"/users/{h}/parties", headers=hh, json={"friend_ids": []}).status_code == 422
    assert api.post(f"/users/{h}/parties", headers=hh, json={"friend_ids": [h]}).status_code == 422
    pid = api.post(f"/users/{h}/parties", headers=hh, json={"friend_ids": [s]}).json()["id"]
    assert api.post(f"/users/{z}/parties/{pid}/join", headers=zh).status_code == 404  # not invited
    assert api.get(f"/users/{h}/parties", headers=sh).status_code == 403


def test_started_parties_drop_off_after_a_day(api, crew):
    (h, hh), (s, sh), _, _ = crew
    pid = api.post(f"/users/{h}/parties", headers=hh, json={"friend_ids": [s]}).json()["id"]
    api.post(f"/users/{s}/parties/{pid}/join", headers=sh)
    api.post(f"/users/{h}/parties/{pid}/start", headers=hh)
    assert len(api.get(f"/users/{s}/parties", headers=sh).json()) == 1
    with db.connect() as conn:
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        conn.execute("UPDATE parties SET started_at = ?", (old,))
    assert api.get(f"/users/{s}/parties", headers=sh).json() == []
    assert api.get(f"/users/{s}/quests", headers=sh).json()[0]["party"]["size"] == 2  # quest keeps its tag


def test_friend_stats(api, crew):
    (h, hh), (s, sh), _, _ = crew
    for minutes, done in [(12, True), (8, False)]:
        qid = api.post(f"/users/{s}/quests", headers=sh, json={}).json()["id"]
        body = {"completed": done, "time_logged_minutes": minutes, **({"rating": 4} if done else {})}
        api.post(f"/users/{s}/quests/{qid}/feedback", headers=sh, json=body)
    sam = next(f for f in api.get(f"/users/{h}/friends", headers=hh).json()["friends"] if f["name"] == "Sam")
    assert sam["quests_this_week"] == 1 and sam["minutes_today"] == 20 and sam["current_streak"] == 1


def test_week_and_today_boundaries(monkeypatch):
    from datetime import date

    from backend.schemas import FeedbackIn, Quest

    q = Quest(title="Some Quest", summary="Do a small thing outside.", steps=["go"], estimated_minutes=10,
              difficulty="easy", energy_required=2)
    rows = [
        (1, q, FeedbackIn(completed=True, rating=4, time_logged_minutes=10), datetime(2026, 10, 12, 15, tzinfo=timezone.utc)),  # Mon
        (2, q, FeedbackIn(completed=True, rating=4, time_logged_minutes=5), datetime(2026, 10, 11, 15, tzinfo=timezone.utc)),   # Sun before
        (3, q, FeedbackIn(completed=True, rating=4, time_logged_minutes=7), datetime(2026, 10, 15, 2, tzinfo=timezone.utc)),    # Wed 22:00 Toronto
    ]
    monkeypatch.setattr(db, "feedback_rows", lambda uid: rows)
    assert friends.week_and_today("u", -240, today=date(2026, 10, 14)) == (2, 7)
    assert friends.week_and_today("u", 0, today=date(2026, 10, 14)) == (1, 0)
