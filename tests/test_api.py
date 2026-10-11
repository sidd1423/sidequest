import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    from backend.main import app

    with TestClient(app) as c:
        yield c


VALID = {
    "interests": ["nature", "photography"],
    "custom_interests": [" Birdwatching ", "birdwatching", ""],
    "availability": {"duration_minutes": 25},
    "difficulty": "easy",
    "energy_level": 2,
    "accessibility": {"needs": ["step_free"], "notes": "bring a stool"},
    "environment": {
        "crowd_tolerance": "quiet",
        "group_size": "pair",
        "max_travel_km": 1.5,
    },
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_user_returns_404(client):
    assert client.get("/users/nobody/preferences").status_code == 404


def test_save_and_load_roundtrip(client):
    r = client.put("/users/gowtham/preferences", json=VALID)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "gowtham"
    assert body["custom_interests"] == ["birdwatching"]  # cleaned + deduped

    loaded = client.get("/users/gowtham/preferences").json()
    assert "weather" not in loaded and "surroundings" not in loaded["environment"]
    assert loaded["environment"]["max_travel_km"] == 1.5


def test_old_weather_and_surroundings_fields_are_ignored(client):
    """Older apps / queued offline edits still send them - accepted, then dropped
    (weather and what's around you are looked up live now)."""
    old = {**VALID, "environment": {**VALID["environment"], "surroundings": ["waterfront"]},
           "weather": {"avoid": ["rain"], "min_temp_c": 8, "max_temp_c": 28}}
    r = client.put("/users/gowtham/preferences", json=old)
    assert r.status_code == 200, r.text
    assert "weather" not in r.json() and "surroundings" not in r.json()["environment"]


def test_update_keeps_created_at(client):
    first = client.put("/users/gowtham/preferences", json=VALID).json()
    second = client.put("/users/gowtham/preferences", json={**VALID, "energy_level": 5}).json()
    assert second["energy_level"] == 5
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


@pytest.mark.parametrize(
    "patch",
    [
        {"interests": [], "custom_interests": []},
        {"energy_level": 9},
        {"difficulty": "impossible"},
        {"environment": {"crowd_tolerance": "rowdy"}},
        {"availability": {"duration_minutes": 45}},
        {"availability": {"duration_minutes": 2}},
        {"environment": {"max_travel_km": 20}},
        {"availability": {"duration_minutes": 20, "preferred_times": ["morning"]}},
        {"environment": {"setting": "indoor"}},
        {"unexpected_field": True},
    ],
)
def test_rejects_invalid(client, patch):
    assert client.put("/users/gowtham/preferences", json={**VALID, **patch}).status_code == 422


def test_rejects_bad_user_id(client):
    assert client.put("/users/a/preferences", json=VALID).status_code == 422


def test_delete(client):
    client.put("/users/gowtham/preferences", json=VALID)
    assert client.delete("/users/gowtham/preferences").status_code == 204
    assert client.get("/users/gowtham/preferences").status_code == 404


def test_old_stored_preferences_still_load(client, tmp_path):
    """Preferences saved before the quick-outdoor redesign (indoor/outdoor,
    time of day, hours-long durations, long travel) are upgraded on read."""
    import json
    import os
    import sqlite3

    old = {**VALID,
           "availability": {"duration_minutes": 180, "preferred_times": ["morning", "evening"]},
           "environment": {**VALID["environment"], "setting": "indoor", "max_travel_km": 25}}
    conn = sqlite3.connect(os.environ["DATABASE_PATH"])
    conn.execute("INSERT INTO user_preferences VALUES (?, ?, ?, ?)",
                 ("legacy", json.dumps(old), "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
    conn.commit()
    conn.close()

    r = client.get("/users/legacy/preferences")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["availability"] == {"duration_minutes": 30}
    assert "setting" not in body["environment"] and body["environment"]["max_travel_km"] == 5.0
