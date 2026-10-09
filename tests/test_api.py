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
    "availability": {"duration_minutes": 120, "preferred_times": ["morning"]},
    "difficulty": "easy",
    "energy_level": 2,
    "accessibility": {"needs": ["step_free"], "notes": "bring a stool"},
    "environment": {
        "setting": "outdoor",
        "surroundings": ["waterfront"],
        "crowd_tolerance": "quiet",
        "group_size": "pair",
        "max_travel_km": 25,
    },
    "weather": {"avoid": ["rain", "extreme_cold"], "min_temp_c": 8, "max_temp_c": 28},
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
    assert loaded["weather"]["avoid"] == ["rain", "extreme_cold"]
    assert loaded["environment"]["max_travel_km"] == 25


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
        {"weather": {"avoid": [], "min_temp_c": 30, "max_temp_c": 10}},
        {"availability": {"duration_minutes": 5}},
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
