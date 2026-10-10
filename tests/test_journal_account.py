"""Quest journal (notes/photos), stats, account deletion, and no reasoning field in prompts."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from backend import history, library
from backend.main import app, get_llm, get_retriever
from backend.quest_generator import build_prompt
from backend.schemas import PreferencesIn, Quest

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class FakeLLM:
    model = "fake"
    n = 0

    def complete(self, prompt, *, temperature=0.9):
        FakeLLM.n += 1
        return json.dumps({
            "title": f"Leaf Hunt {FakeLLM.n}", "summary": "Find five differently shaped leaves near you.",
            "steps": ["Step outside", "Collect leaves"], "estimated_minutes": 10, "difficulty": "easy",
            "energy_required": 2, "tags": ["nature"], "weather_backup": "Use a covered path",
        })


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    app.dependency_overrides[get_llm] = FakeLLM
    app.dependency_overrides[get_retriever] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def account(api, email="j@example.com"):
    s = api.post("/auth/signup", json={"email": email, "password": "longpassword"}).json()
    uid, h = s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}
    api.put(f"/users/{uid}/preferences", headers=h, json={"interests": ["nature"]})
    qid = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]
    return uid, h, qid


def test_prompt_no_longer_asks_for_reasoning():
    assert "why_it_fits" not in build_prompt(PreferencesIn(interests=["nature"]))
    assert Quest(title="Old one", summary="An older quest with a reason.", steps=["x"], estimated_minutes=5,
                 difficulty="easy", energy_required=1, why_it_fits="old").why_it_fits == "old"


def test_notes_and_photos(api):
    uid, h, qid = account(api)
    note = {"client_id": "note-0001", "kind": "note", "text": "Saw a heron!"}
    assert api.post(f"/users/{uid}/quests/{qid}/logs", headers=h, json=note).status_code == 201
    # retry from the offline outbox: same client_id -> no duplicate
    assert api.post(f"/users/{uid}/quests/{qid}/logs", headers=h, json={**note, "text": "Saw a heron!!"}).status_code == 201
    photo = {"client_id": "photo-0001", "kind": "photo", "text": "the heron",
             "image_base64": base64.b64encode(PNG).decode(), "mime": "image/png"}
    created = api.post(f"/users/{uid}/quests/{qid}/logs", headers=h, json=photo).json()
    assert created["has_photo"] is True

    logs = api.get(f"/users/{uid}/quests/{qid}/logs", headers=h).json()
    assert [(l["kind"], l["text"]) for l in logs] == [("note", "Saw a heron!!"), ("photo", "the heron")]
    r = api.get(f"/users/{uid}/logs/{created['id']}/photo", headers=h)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"

    assert api.delete(f"/users/{uid}/logs/note-0001", headers=h).status_code == 204
    assert api.delete(f"/users/{uid}/logs/note-0001", headers=h).status_code == 204  # idempotent
    assert len(api.get(f"/users/{uid}/quests/{qid}/logs", headers=h).json()) == 1


@pytest.mark.parametrize("bad", [
    {"client_id": "n-000001", "kind": "note", "text": "  "},
    {"client_id": "p-000001", "kind": "photo", "image_base64": "aGk=", "mime": "text/plain"},
    {"client_id": "p-000002", "kind": "photo", "mime": "image/png"},
    {"client_id": "bad id!", "kind": "note", "text": "x"},
])
def test_log_validation(api, bad):
    uid, h, qid = account(api)
    assert api.post(f"/users/{uid}/quests/{qid}/logs", headers=h, json=bad).status_code == 422


def test_journal_is_private(api):
    uid, h, qid = account(api)
    other_uid, other_h, other_qid = account(api, "other@example.com")
    note = {"client_id": "note-0002", "kind": "note", "text": "mine"}
    # can't log on someone else's quest even through your own user path
    assert api.post(f"/users/{other_uid}/quests/{qid}/logs", headers=other_h, json=note).status_code == 404
    assert api.get(f"/users/{uid}/quests/{qid}/logs", headers=other_h).status_code == 403


def test_stats(api):
    uid, h, qid = account(api)
    q2 = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]
    api.post(f"/users/{uid}/quests/{qid}/feedback", headers=h,
             json={"completed": True, "rating": 5, "time_logged_minutes": 12})
    api.post(f"/users/{uid}/quests/{q2}/feedback", headers=h, json={"completed": False, "time_logged_minutes": 3})
    assert api.get(f"/users/{uid}/stats", headers=h).json() == {"completed": 1, "generated": 2, "minutes_outside": 15}


def test_delete_account_removes_everything(api):
    uid, h, qid = account(api)
    api.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json={"completed": True, "rating": 4,
                                                                     "time_logged_minutes": 9})
    api.post(f"/users/{uid}/quests/{qid}/logs", headers=h, json={"client_id": "note-0003", "kind": "note", "text": "hi"})
    assert any(q.app_quest_id == qid for q in history.recent(uid))

    assert api.request("DELETE", "/auth/me", headers=h, json={"password": "wrong pass"}).status_code == 403
    assert api.request("DELETE", "/auth/me", headers=h, json={"password": "longpassword"}).status_code == 204

    assert api.get("/auth/me", headers=h).status_code == 401
    assert api.post("/auth/login", json={"email": "j@example.com", "password": "longpassword"}).status_code == 401
    assert history.recent(uid) == []
    import sqlite3

    lib = sqlite3.connect(library.library_path())
    assert lib.execute("SELECT COUNT(*) FROM quests WHERE user_id = ?", (uid,)).fetchone()[0] == 0
    assert lib.execute("SELECT COUNT(*) FROM quests WHERE source = 'seed'").fetchone()[0] > 0
    # the email can be used again
    assert api.post("/auth/signup", json={"email": "j@example.com", "password": "longpassword"}).status_code == 201
