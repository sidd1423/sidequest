"""Friends: request by email, accept/decline, cancel, unfriend, privacy."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    with TestClient(app) as c:
        yield c


def signup(api, email, name=""):
    s = api.post("/auth/signup", json={"email": email, "name": name, "password": "longpassword"}).json()
    return s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}


def friends(api, uid, h):
    r = api.get(f"/users/{uid}/friends", headers=h)
    assert r.status_code == 200
    return r.json()


def test_request_then_accept(api):
    a, ha = signup(api, "alex@example.com", "Alex")
    b, hb = signup(api, "bo@example.com", "Bo")

    r = api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "  BO@example.com "})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert r.json()["person"] == {"user_id": b, "name": "Bo", "email": "bo@example.com"}
    rid = r.json()["request_id"]

    assert [x["person"]["name"] for x in friends(api, a, ha)["outgoing"]] == ["Bo"]
    incoming = friends(api, b, hb)["incoming"]
    assert [x["person"]["email"] for x in incoming] == ["alex@example.com"]
    assert friends(api, b, hb)["friends"] == []

    # Only Bo can accept.
    assert api.post(f"/users/{a}/friends/requests/{rid}/accept", headers=ha).status_code == 404
    assert api.post(f"/users/{b}/friends/requests/{rid}/accept", headers=hb).status_code == 204

    fa, fb = friends(api, a, ha), friends(api, b, hb)
    assert [f["name"] for f in fa["friends"]] == ["Bo"] and fa["outgoing"] == []
    assert [f["name"] for f in fb["friends"]] == ["Alex"] and fb["incoming"] == []
    friend = fa["friends"][0]
    assert friend["completed"] == 0 and friend["level_name"] == "Homebody" and friend["since"]


def test_errors(api):
    a, ha = signup(api, "alex@example.com")
    signup(api, "bo@example.com")
    send = lambda email: api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": email})
    assert send("nobody@example.com").status_code == 404
    assert send("alex@example.com").status_code == 422
    assert send("not-an-email").status_code == 422
    assert send("bo@example.com").status_code == 201
    r = send("bo@example.com")
    assert r.status_code == 409 and "already sent" in r.json()["detail"]


def test_asking_back_accepts(api):
    a, ha = signup(api, "alex@example.com")
    b, hb = signup(api, "bo@example.com")
    api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "bo@example.com"})
    r = api.post(f"/users/{b}/friends/requests", headers=hb, json={"email": "alex@example.com"})
    assert r.status_code == 201 and r.json()["status"] == "accepted"
    assert len(friends(api, a, ha)["friends"]) == 1
    r = api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "bo@example.com"})
    assert r.status_code == 409 and "already friends" in r.json()["detail"]


def test_decline_and_cancel(api):
    a, ha = signup(api, "alex@example.com")
    b, hb = signup(api, "bo@example.com")
    rid = api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "bo@example.com"}).json()["request_id"]
    assert api.post(f"/users/{b}/friends/requests/{rid}/decline", headers=hb).status_code == 204
    assert friends(api, a, ha)["outgoing"] == []

    rid = api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "bo@example.com"}).json()["request_id"]
    assert api.delete(f"/users/{b}/friends/requests/{rid}", headers=hb).status_code == 404  # not theirs to cancel
    assert api.delete(f"/users/{a}/friends/requests/{rid}", headers=ha).status_code == 204
    assert friends(api, b, hb)["incoming"] == []


def test_unfriend(api):
    a, ha = signup(api, "alex@example.com")
    b, hb = signup(api, "bo@example.com")
    rid = api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "bo@example.com"}).json()["request_id"]
    assert api.delete(f"/users/{a}/friends/{b}", headers=ha).status_code == 404  # only pending
    api.post(f"/users/{b}/friends/requests/{rid}/accept", headers=hb)
    assert api.delete(f"/users/{b}/friends/{a}", headers=hb).status_code == 204
    assert friends(api, a, ha)["friends"] == [] and friends(api, b, hb)["friends"] == []


def test_only_your_own_friends(api):
    a, ha = signup(api, "alex@example.com")
    b, hb = signup(api, "bo@example.com")
    assert api.get(f"/users/{a}/friends", headers=hb).status_code == 403
    assert api.post(f"/users/{a}/friends/requests", headers=hb, json={"email": "bo@example.com"}).status_code == 403
    assert api.get(f"/users/{a}/friends").status_code == 401


def test_deleting_an_account_removes_friendships(api):
    a, ha = signup(api, "alex@example.com")
    b, hb = signup(api, "bo@example.com")
    rid = api.post(f"/users/{a}/friends/requests", headers=ha, json={"email": "bo@example.com"}).json()["request_id"]
    api.post(f"/users/{b}/friends/requests/{rid}/accept", headers=hb)
    assert api.request("DELETE", "/auth/me", headers=hb, json={"password": "longpassword"}).status_code == 204
    assert friends(api, a, ha)["friends"] == []
    # Same email signs up again: a stranger, not a friend.
    c, hc = signup(api, "bo@example.com")
    assert friends(api, c, hc) == {"friends": [], "incoming": [], "outgoing": []}
