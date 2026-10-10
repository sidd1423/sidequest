"""Accounts, sessions and per-user access control."""

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.main import app, get_llm, get_retriever

PREFS = {
    "interests": ["nature"],
    "availability": {"duration_minutes": 20},
    "difficulty": "easy",
    "energy_level": 3,
    "environment": {"max_travel_km": 1.0},
}

QUEST_JSON = """{"title": "Leaf Hunt", "summary": "Find five differently shaped leaves near you.",
"steps": ["Step outside", "Collect five leaf shapes", "Photograph them"], "estimated_minutes": %d,
"difficulty": "%s", "energy_required": %d, "tags": ["nature"], "weather_backup": "Use a covered path"}"""


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt, *, temperature=0.9):
        self.prompts.append(prompt)
        return QUEST_JSON % (12, "challenging", 4)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def sign_up(client, email="gowtham@example.com", password="correct horse", name="Gowtham"):
    r = client.post("/auth/signup", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(session):
    return {"Authorization": f"Bearer {session['token']}"}


def test_password_hashing():
    stored = auth.hash_password("hunter22!")
    assert "hunter22!" not in stored
    assert auth.verify_password("hunter22!", stored)
    assert not auth.verify_password("hunter23!", stored)
    assert not auth.verify_password("x", "garbage")


def test_sign_up_returns_session(client):
    s = sign_up(client, email="  Gowtham@Example.COM ")
    assert s["token"] and s["token_type"] == "bearer"
    assert s["user"]["email"] == "gowtham@example.com"
    assert s["user"]["id"].startswith("u_")
    assert client.get("/auth/me", headers=bearer(s)).json()["name"] == "Gowtham"


def test_token_is_not_stored_in_plain_text(client):
    s = sign_up(client)
    from backend import db

    with db.connect() as conn:
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
        pw = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert s["token"] not in stored
    assert "correct horse" not in pw


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": "longenough"},
        {"email": "a@b.co", "password": "short"},
        {"email": "a@b.co", "password": "longenough", "admin": True},
    ],
)
def test_sign_up_validation(client, body):
    assert client.post("/auth/signup", json=body).status_code == 422


def test_duplicate_email_is_rejected(client):
    sign_up(client)
    r = client.post("/auth/signup", json={"email": "GOWTHAM@example.com", "password": "another one"})
    assert r.status_code == 409


def test_log_in(client):
    created = sign_up(client)
    r = client.post("/auth/login", json={"email": "Gowtham@example.com", "password": "correct horse"})
    assert r.status_code == 200
    assert r.json()["user"]["id"] == created["user"]["id"]
    assert r.json()["token"] != created["token"]  # a new session per device/login


@pytest.mark.parametrize("email,password", [("gowtham@example.com", "wrong pass"), ("nobody@example.com", "correct horse")])
def test_log_in_failures_look_the_same(client, email, password):
    sign_up(client)
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong email or password"


def test_log_out_revokes_only_that_session(client):
    phone = sign_up(client)
    laptop = client.post("/auth/login", json={"email": "gowtham@example.com", "password": "correct horse"}).json()
    assert client.post("/auth/logout", headers=bearer(phone)).status_code == 204
    assert client.get("/auth/me", headers=bearer(phone)).status_code == 401
    assert client.get("/auth/me", headers=bearer(laptop)).status_code == 200


def test_expired_session(client, monkeypatch):
    monkeypatch.setenv("SESSION_DAYS", "-1")
    s = sign_up(client)
    assert client.get("/auth/me", headers=bearer(s)).status_code == 401


def test_update_account(client):
    s = sign_up(client)
    r = client.patch("/auth/me", headers=bearer(s), json={"name": " G ", "email": "new@example.com"})
    assert r.status_code == 200
    assert r.json()["name"] == "G" and r.json()["email"] == "new@example.com"
    other = sign_up(client, email="other@example.com")
    assert client.patch("/auth/me", headers=bearer(other), json={"email": "new@example.com"}).status_code == 409
    assert client.post("/auth/login", json={"email": "new@example.com", "password": "correct horse"}).status_code == 200


def test_user_routes_need_a_token(client):
    s = sign_up(client)
    uid = s["user"]["id"]
    assert client.get(f"/users/{uid}/preferences").status_code == 401
    assert client.put(f"/users/{uid}/preferences", json=PREFS).status_code == 401
    assert client.get(f"/users/{uid}/quests").status_code == 401
    assert client.get(f"/users/{uid}/preferences", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_users_cannot_touch_each_others_data(client):
    alice = sign_up(client, email="alice@example.com")
    bob = sign_up(client, email="bob@example.com")
    a = alice["user"]["id"]
    assert client.put(f"/users/{a}/preferences", json=PREFS, headers=bearer(alice)).status_code == 200
    for method, path, body in [
        ("GET", f"/users/{a}/preferences", None),
        ("PUT", f"/users/{a}/preferences", PREFS),
        ("DELETE", f"/users/{a}/preferences", None),
        ("GET", f"/users/{a}/quests", None),
        ("POST", f"/users/{a}/quests", None),
        ("POST", f"/users/{a}/quests/1/feedback", {"completed": False}),
    ]:
        r = client.request(method, path, json=body, headers=bearer(bob))
        assert r.status_code == 403, (method, path, r.text)


def test_full_flow_with_per_quest_settings(client):
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None
    s = sign_up(client)
    uid, h = s["user"]["id"], bearer(s)
    assert client.put(f"/users/{uid}/preferences", json=PREFS, headers=h).status_code == 200

    r = client.post(
        f"/users/{uid}/quests",
        headers=h,
        json={"duration_minutes": 15, "difficulty": "challenging", "energy_level": 4, "max_travel_km": 2.5},
    )
    assert r.status_code == 201, r.text
    prompt = llm.prompts[-1]
    assert "15" in prompt and "challenging" in prompt.lower() and "2.5" in prompt
    # the saved profile isn't changed by per-quest settings
    assert client.get(f"/users/{uid}/preferences", headers=h).json()["difficulty"] == "easy"

    qid = r.json()["id"]
    fb = {"completed": True, "rating": 5, "comment": "", "time_logged_minutes": 14}
    assert client.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json=fb).status_code == 200
    # sending the same feedback twice (offline outbox retry) is harmless
    assert client.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json=fb).status_code == 200
    quests = client.get(f"/users/{uid}/quests", headers=h).json()
    assert len(quests) == 1 and quests[0]["status"] == "completed"


def test_per_quest_settings_are_validated(client):
    s = sign_up(client)
    uid = s["user"]["id"]
    client.put(f"/users/{uid}/preferences", json=PREFS, headers=bearer(s))
    r = client.post(f"/users/{uid}/quests", headers=bearer(s), json={"duration_minutes": 90})
    assert r.status_code == 422


def test_dev_mode_allows_anonymous(client, monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    assert client.put("/users/gowtham/preferences", json=PREFS).status_code == 200
    # ...but a token still has to match the user
    s = sign_up(client)
    assert client.get("/users/gowtham/preferences", headers=bearer(s)).status_code == 403
