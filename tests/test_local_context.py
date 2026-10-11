"""Live location context (weather, place, nearby spots) and recorded quest routes."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import local_context
from backend.local_context import (
    build_overpass_query, compass, describe_for_search, distance_m, parse_nearby, parse_place, parse_weather,
    search_radius,
)
from backend.main import app, get_context_lookup, get_llm, get_retriever
from backend.quest_generator import build_prompt
from backend.routes import RoutePoint, measure
from backend.schemas import GeoPoint, NearbyPlace, PreferencesIn, QuestContext, WeatherNow

PROFILE = PreferencesIn.model_validate({"interests": ["nature"], "environment": {"max_travel_km": 1.0}})

FORECAST = {
    "utc_offset_seconds": -14400,
    "current": {"time": "2026-10-10T17:40", "temperature_2m": 12.3, "apparent_temperature": 9.1,
                "precipitation": 0.4, "weather_code": 61, "wind_speed_10m": 18.0, "wind_gusts_10m": 30.0,
                "uv_index": 1.2, "is_day": 1},
    "hourly": {"time": ["2026-10-10T17:00", "2026-10-10T18:00", "2026-10-10T19:00"],
               "precipitation_probability": [60, 80, 40]},
    "daily": {"sunrise": ["2026-10-10T07:21"], "sunset": ["2026-10-10T18:52"]},
}

OVERPASS = {"elements": [
    {"type": "way", "center": {"lat": 43.6705, "lon": -79.3555}, "tags": {"leisure": "park", "name": "Riverdale Park"}},
    {"type": "node", "lat": 43.6690, "lon": -79.3600, "tags": {"tourism": "viewpoint"}},
    {"type": "way", "center": {"lat": 43.6700, "lon": -79.3590}, "tags": {"waterway": "river", "name": "Don River"}},
    {"type": "way", "center": {"lat": 43.6701, "lon": -79.3556}, "tags": {"leisure": "park", "name": "Riverdale Park"}},
    {"type": "node", "lat": 43.9, "lon": -79.0, "tags": {"leisure": "park", "name": "Far Away Park"}},
    {"type": "node", "lat": 43.6680, "lon": -79.3500, "tags": {"historic": "memorial", "name": "Old Bell"}},
    {"type": "node", "lat": 43.6680, "lon": -79.3500, "tags": {"shop": "bakery", "name": "Not outdoors"}},
]}
HERE = (43.6677, -79.3534)


# ---------------------------------------------------------------------------
# Parsing the services' answers
# ---------------------------------------------------------------------------

def test_parse_weather():
    w = parse_weather(FORECAST, {"current": {"us_aqi": 42}})
    assert w.temp_c == 12.3 and w.feels_like_c == 9.1 and w.condition == "light rain"
    assert w.rain_chance_pct == 80 and w.is_day is True and w.air_quality_index == 42
    assert (w.local_time, w.sunrise, w.sunset) == ("17:40", "07:21", "18:52")


def test_parse_place():
    assert parse_place({"address": {"neighbourhood": "Riverdale", "city": "Toronto"}}) == "Riverdale, Toronto"
    assert parse_place({"address": {"village": "Elora"}}) == "Elora"
    assert parse_place({"display_name": "Somewhere, Ontario"}) == "Somewhere"


def test_parse_nearby_dedupes_sorts_and_filters():
    places = parse_nearby(OVERPASS, *HERE, radius_m=1000)
    names = [p.name for p in places]
    assert names[0] == "Old Bell"  # closest first
    assert "Far Away Park" not in names and "Not outdoors" not in names
    assert names.count("Riverdale Park") == 1
    park = next(p for p in places if p.name == "Riverdale Park")
    assert park.kind == "park" and park.direction in {"N", "NW", "NE"} and 200 < park.distance_m < 600
    assert any(p.name == "unnamed viewpoint" for p in places)
    assert next(p for p in places if p.name == "Old Bell").kind == "historic memorial"


def test_geometry_and_query():
    assert 1100 < distance_m(43.0, -79.0, 43.01, -79.0) < 1120
    assert compass(43.0, -79.0, 43.01, -79.0) == "N" and compass(43.0, -79.0, 43.0, -78.99) == "E"
    q = build_overpass_query(*HERE, 800)
    assert "around:800,43.66770,-79.35340" in q and '"leisure"~"^(park|' in q
    assert search_radius(0) == 300 and search_radius(1.5) == 1500 and search_radius(9) == 5000


def test_lookup_combines_services_and_survives_failures(monkeypatch):
    local_context.clear_cache()
    monkeypatch.setenv("LOCAL_CONTEXT", "on")

    def fake_get(url, params):
        if "air-quality" in url:
            raise TimeoutError("slow")
        if "reverse" in url:
            return {"address": {"neighbourhood": "Riverdale", "city": "Toronto"}}
        return FORECAST

    class Resp:
        def raise_for_status(self):
            raise RuntimeError("overpass is down")

    monkeypatch.setattr(local_context, "_get", fake_get)
    monkeypatch.setattr(local_context.requests, "post", lambda *a, **k: Resp())
    ctx = local_context.lookup(GeoPoint(lat=HERE[0], lon=HERE[1]), 1.0)
    assert ctx.place == "Riverdale, Toronto" and ctx.weather.condition == "light rain"
    assert ctx.weather.air_quality_index is None and ctx.nearby == []  # failed parts stay empty
    assert ctx.lat == 43.668

    calls = []
    monkeypatch.setattr(local_context, "_get", lambda url, params: calls.append(url) or FORECAST)
    local_context.lookup(GeoPoint(lat=HERE[0], lon=HERE[1]), 1.0)
    assert not any("forecast" in c for c in calls)  # weather cached
    local_context.clear_cache()


def test_lookup_disabled(monkeypatch):
    monkeypatch.setenv("LOCAL_CONTEXT", "off")
    monkeypatch.setattr(local_context, "_get", lambda *a: pytest.fail("no network when disabled"))
    ctx = local_context.lookup(GeoPoint(lat=1, lon=2), 1.0)
    assert ctx.weather is None and ctx.nearby == [] and local_context.geocode("Toronto") is None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def ctx(**weather) -> QuestContext:
    w = {"temp_c": 12, "feels_like_c": 9, "condition": "light rain", "weather_code": 61, "wind_kmh": 18,
         "rain_chance_pct": 80, "is_day": True, "local_time": "17:40", "sunset": "18:52", **weather}
    return QuestContext(place="Riverdale, Toronto", weather=WeatherNow(**w), nearby=[
        NearbyPlace(name="Riverdale Park", kind="park", distance_m=350, direction="NE")])


def test_prompt_uses_live_conditions():
    p = build_prompt(PROFILE, context=ctx())
    assert "## Right now, where they are (live)" in p
    assert "Place: Riverdale, Toronto" in p
    assert "12°C (feels like 9°C), light rain, wind 18 km/h" in p
    assert "rain/snow in the next 2 hours: 80%" in p
    assert "Riverdale Park (park, 350 m NE)" in p
    assert "Only use places from that list" in p
    assert "Fits the weather RIGHT NOW" in p
    assert "only about 72 min of daylight left" in p
    assert "THUNDERSTORM" not in p and "DARK" not in p
    assert "don't name specific places" not in p


def test_prompt_weather_rules():
    assert "THUNDERSTORM" in build_prompt(PROFILE, context=ctx(weather_code=95, condition="thunderstorm"))
    dark = build_prompt(PROFILE, context=ctx(is_day=False, local_time="21:00"))
    assert "it's DARK out" in dark and "well-lit, populated streets" in dark
    assert "dangerously cold" in build_prompt(PROFILE, context=ctx(temp_c=-12, feels_like_c=-20))
    assert "very hot" in build_prompt(PROFILE, context=ctx(temp_c=33, feels_like_c=36, weather_code=0))
    assert "Icy" in build_prompt(PROFILE, context=ctx(temp_c=-1, feels_like_c=-4, weather_code=61))
    only_place = build_prompt(PROFILE, context=QuestContext(place="Elora"))
    assert "Fit it to Elora" in only_place and "don't know the weather" in only_place.lower()


def test_search_text():
    assert describe_for_search(ctx()) == "Right now: light rain, 12 degrees; near a park."
    assert describe_for_search(None) == ""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class FakeLLM:
    model = "fake"
    prompts: list[str] = []

    def complete(self, prompt, *, temperature=0.9):
        FakeLLM.prompts.append(prompt)
        return json.dumps({"title": f"Puddle Mirror Hunt {len(FakeLLM.prompts)}",
                           "summary": "Find reflections in the puddles around Riverdale Park.",
                           "steps": ["Head NE to Riverdale Park", "Photograph 3 reflections"],
                           "estimated_minutes": 15, "difficulty": "easy", "energy_required": 2,
                           "tags": ["nature"], "weather_backup": "Shelter under the park pavilion."})


LOOKUPS: list[tuple] = []


def fake_lookup(location, max_travel_km, hint):
    LOOKUPS.append((location.lat, location.lon, max_travel_km, hint))
    c = ctx()
    if hint:
        c.place = hint
    return c


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    FakeLLM.prompts, LOOKUPS[:] = [], []
    app.dependency_overrides[get_llm] = FakeLLM
    app.dependency_overrides[get_retriever] = lambda: None
    app.dependency_overrides[get_context_lookup] = lambda: fake_lookup
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def person(api, email):
    s = api.post("/auth/signup", json={"email": email, "name": email[:3], "password": "longpassword"}).json()
    uid, h = s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}
    api.put(f"/users/{uid}/preferences", headers=h, json={"interests": ["nature"]})
    return uid, h


def test_quest_uses_device_location(api):
    uid, h = person(api, "ana@example.com")
    r = api.post(f"/users/{uid}/quests", headers=h,
                 json={"max_travel_km": 2, "location": {"lat": HERE[0], "lon": HERE[1], "accuracy_m": 12}})
    assert r.status_code == 201, r.text
    assert LOOKUPS == [(HERE[0], HERE[1], 2.0, "")]
    assert "Riverdale Park (park, 350 m NE)" in FakeLLM.prompts[0]
    rec = r.json()
    assert rec["context"]["place"] == "Riverdale, Toronto" and rec["context"]["weather"]["temp_c"] == 12
    assert rec["route"] is None
    listed = api.get(f"/users/{uid}/quests", headers=h).json()[0]
    assert listed["context"]["nearby"][0]["name"] == "Riverdale Park"


def test_quest_without_location_still_works(api):
    uid, h = person(api, "bo@example.com")
    r = api.post(f"/users/{uid}/quests", headers=h, json={"duration_minutes": 20})
    assert r.status_code == 201 and r.json()["context"] is None and LOOKUPS == []
    assert "don't name specific places" in FakeLLM.prompts[0]


def test_typed_place_is_geocoded(api, monkeypatch):
    uid, h = person(api, "cy@example.com")
    monkeypatch.setattr(local_context, "geocode", lambda q: GeoPoint(lat=43.7, lon=-80.4) if q == "Elora" else None)
    r = api.post(f"/users/{uid}/quests", headers=h, json={"place": "Elora"})
    assert r.status_code == 201 and LOOKUPS == [(43.7, -80.4, 1.0, "Elora")]
    assert r.json()["context"]["place"] == "Elora"
    r = api.post(f"/users/{uid}/quests", headers=h, json={"place": "Nowhere-ville"})
    assert r.json()["context"] == {"place": "Nowhere-ville", "lat": None, "lon": None, "weather": None, "nearby": []}
    assert "Fit it to Nowhere-ville" in FakeLLM.prompts[-1]


def test_lookup_crash_does_not_block_quest(api):
    def broken(*a):
        raise RuntimeError("boom")
    app.dependency_overrides[get_context_lookup] = lambda: broken
    uid, h = person(api, "di@example.com")
    r = api.post(f"/users/{uid}/quests", headers=h, json={"location": {"lat": 1, "lon": 2}})
    assert r.status_code == 201 and r.json()["context"] is None


def test_conditions_endpoint(api):
    uid, h = person(api, "ed@example.com")
    r = api.get(f"/users/{uid}/conditions", headers=h, params={"lat": 43.6, "lon": -79.3, "max_travel_km": 1.5})
    assert r.status_code == 200 and r.json()["weather"]["condition"] == "light rain"
    assert api.get(f"/users/{uid}/conditions", headers=h, params={"lat": 99, "lon": 0}).status_code == 422


def test_bad_location_rejected(api):
    uid, h = person(api, "fa@example.com")
    assert api.post(f"/users/{uid}/quests", headers=h, json={"location": {"lat": 200, "lon": 0}}).status_code == 422


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc)


def walk(n=5, step_deg=0.0005, accuracy=8.0):
    return [{"lat": 43.6677 + i * step_deg, "lon": -79.3534, "t": (T0 + timedelta(seconds=30 * i)).isoformat(),
             "accuracy_m": accuracy} for i in range(n)]


def test_measure_skips_glitches_and_bad_fixes():
    pts = [RoutePoint.model_validate(p) for p in walk(5)]
    dist, dur = measure(pts)
    assert 215 < dist < 230 and dur == 120  # 4 x ~55.6 m
    jump = RoutePoint(lat=44.5, lon=-79.3534, t=T0 + timedelta(seconds=45))  # 90 km in 15 s
    fuzzy = RoutePoint(lat=43.70, lon=-79.3534, t=T0 + timedelta(seconds=50), accuracy_m=500)
    assert measure(pts + [jump, fuzzy])[0] == dist
    assert measure(pts[:1]) == (0, 0)


def test_route_roundtrip_and_privacy(api):
    uid, h = person(api, "gu@example.com")
    other, oh = person(api, "ha@example.com")
    qid = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]

    assert api.get(f"/users/{uid}/quests/{qid}/route", headers=h).status_code == 404
    r = api.put(f"/users/{uid}/quests/{qid}/route", headers=h, json={"points": list(reversed(walk(5)))})
    assert r.status_code == 200, r.text
    route = r.json()
    assert route["points"][0]["t"].startswith("2026-10-10T21:00:00")  # sorted by time
    assert 215 < route["distance_m"] < 230 and route["duration_seconds"] == 120

    # Re-sending (offline outbox) just replaces it.
    again = api.put(f"/users/{uid}/quests/{qid}/route", headers=h, json={"points": walk(9)}).json()
    assert len(again["points"]) == 9 and again["distance_m"] > route["distance_m"]

    listed = api.get(f"/users/{uid}/quests", headers=h).json()[0]
    assert listed["route"] == {"distance_m": again["distance_m"], "duration_seconds": 240, "points": 9}
    fb = api.post(f"/users/{uid}/quests/{qid}/feedback", headers=h, json={"completed": True, "rating": 5})
    assert fb.json()["route"]["points"] == 9

    # Someone else can't read or write it, or put a route on a quest that isn't theirs.
    assert api.get(f"/users/{uid}/quests/{qid}/route", headers=oh).status_code == 403
    assert api.put(f"/users/{other}/quests/{qid}/route", headers=oh, json={"points": walk(2)}).status_code == 404

    assert api.delete(f"/users/{uid}/quests/{qid}/route", headers=h).status_code == 204
    assert api.get(f"/users/{uid}/quests/{qid}/route", headers=h).status_code == 404
    assert api.delete(f"/users/{uid}/quests/{qid}/route", headers=h).status_code == 204  # already gone is fine


def test_route_removed_with_account(api):
    uid, h = person(api, "ia@example.com")
    qid = api.post(f"/users/{uid}/quests", headers=h, json={}).json()["id"]
    api.put(f"/users/{uid}/quests/{qid}/route", headers=h, json={"points": walk(3)})
    assert api.request("DELETE", "/auth/me", headers=h, json={"password": "longpassword"}).status_code == 204
    from backend import db
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quest_routes").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Group quests: the host's position is sent on start, never stored on the invite
# ---------------------------------------------------------------------------

def test_party_location_only_on_start(api):
    host, hh = person(api, "jo@example.com")
    pal, ph = person(api, "ki@example.com")
    rid = api.post(f"/users/{host}/friends/requests", headers=hh, json={"email": "ki@example.com"}).json()["request_id"]
    api.post(f"/users/{pal}/friends/requests/{rid}/accept", headers=ph)
    party = api.post(f"/users/{host}/parties", headers=hh, json={
        "friend_ids": [pal], "settings": {"duration_minutes": 20, "location": {"lat": 43.6, "lon": -79.3}}}).json()
    assert party["settings"]["location"] is None and party["settings"]["duration_minutes"] == 20
    invite = api.get(f"/users/{pal}/parties", headers=ph).json()[0]
    assert invite["settings"]["location"] is None
    api.post(f"/users/{pal}/parties/{party['id']}/join", headers=ph)

    started = api.post(f"/users/{host}/parties/{party['id']}/start", headers=hh,
                       json={"location": {"lat": 43.65, "lon": -79.35}})
    assert started.status_code == 200, started.text
    assert LOOKUPS == [(43.65, -79.35, 1.0, "")]
    assert "Riverdale Park" in FakeLLM.prompts[0] and "exactly 2 friends" in FakeLLM.prompts[0]
    pal_quest = api.get(f"/users/{pal}/quests", headers=ph).json()[0]
    assert pal_quest["context"]["place"] == "Riverdale, Toronto"
