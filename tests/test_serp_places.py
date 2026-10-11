"""Google Maps places via SerpApi (backend/serp_places.py) - no real API calls."""

import random

import pytest

from backend import local_context, serp_places
from backend.local_context import compass, distance_m, merge_places
from backend.quest_generator import build_prompt
from backend.schemas import GeoPoint, NearbyPlace, PreferencesIn, QuestContext

HERE = (43.6677, -79.3534)

MAPS = {"local_results": [
    {"title": "Riverdale Park East", "gps_coordinates": {"latitude": 43.6705, "longitude": -79.3555},
     "rating": 4.7, "reviews": 3120, "type": "Park", "types": ["Park"], "address": "550 Broadview Ave",
     "open_state": "Open 24 hours"},
    {"title": "Old Mill Cafe", "gps_coordinates": {"latitude": 43.668, "longitude": -79.353},
     "rating": 4.5, "reviews": 200, "type": "Cafe", "types": ["Cafe", "Coffee shop"]},
    {"title": "Gone Garden", "gps_coordinates": {"latitude": 43.668, "longitude": -79.354},
     "type": "Garden", "open_state": "Permanently closed"},
    {"title": "Far Park", "gps_coordinates": {"latitude": 44.5, "longitude": -79.0}, "type": "Park"},
    {"title": "Farmers Market", "gps_coordinates": {"latitude": 43.669, "longitude": -79.352},
     "type": "Farmers' market", "types": ["Farmers' market", "Market"], "open_state": "Closed ⋅ Opens 8 AM Sat"},
    {"title": "No coords"},
]}


@pytest.fixture()
def serp(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setenv("LOCAL_CONTEXT", "on")
    local_context.clear_cache()
    calls = []

    def fake_search(params, timeout):
        calls.append(params)
        return MAPS
    monkeypatch.setattr(serp_places, "search", fake_search)
    yield calls
    local_context.clear_cache()


def test_queries_from_interests(monkeypatch):
    monkeypatch.setenv("SERPAPI_MAX_QUERIES", "3")
    q = serp_places.queries_for(["art", "birdwatching"], rng=random.Random(1))
    assert q[0] == "park" and len(q) == 3
    assert set(q[1:]) <= {"public art", "mural", "sculpture", "birdwatching"}
    monkeypatch.delenv("SERPAPI_MAX_QUERIES")
    assert serp_places.queries_for([]) == ["park"]
    assert len(serp_places.queries_for(["nature", "art"])) == 2  # default: 2 credits per quest


def test_zoom():
    assert [serp_places.zoom_for(r) for r in (300, 1000, 2500, 5000)] == [16, 15, 14, 13]


def test_parse_filters_closed_indoor_and_far():
    places = serp_places.parse_places(MAPS, *HERE, 1000, distance_m, compass)
    names = [p.name for p in places]
    assert names == ["Riverdale Park East", "Farmers Market"]
    park = places[0]
    assert park.rating == 4.7 and park.reviews == 3120 and park.source == "google"
    assert park.open_state == "Open 24 hours" and park.kind == "park" and park.direction in {"N", "NW"}
    # A single matched place comes back as place_results.
    one = {"place_results": {"title": "High Park", "gps_coordinates": {"latitude": 43.668, "longitude": -79.353},
                             "type": "Park"}}
    assert [p.name for p in serp_places.parse_places(one, *HERE, 1000, distance_m, compass)] == ["High Park"]


def test_nearby_uses_location_and_caches(serp):
    first = local_context.fetch_google_places(*HERE, 1000, ["art"])
    assert [p.name for p in first][:1] == ["Riverdale Park East"]
    assert len(serp) == 2  # "park" + one art search
    assert serp[0]["engine"] == "google_maps" and serp[0]["q"] == "park"
    assert serp[0]["ll"] == "@43.66770,-79.35340,15z"
    local_context.fetch_google_places(*HERE, 1000, ["art"])
    assert serp.count(serp[0]) == 1  # "park" here again: cached, no extra credit


def test_nearby_errors(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    local_context.clear_cache()
    monkeypatch.setattr(serp_places, "search", lambda p, t: (_ for _ in ()).throw(RuntimeError("SerpApi: Invalid API key")))
    with pytest.raises(RuntimeError, match="Invalid API key"):
        local_context.fetch_google_places(*HERE, 1000, [])


def test_search_reports_api_errors(monkeypatch):
    class Resp:
        def __init__(self, body, status=200):
            self.body, self.status_code = body, status

        def json(self):
            return self.body

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    sent = {}
    monkeypatch.setattr(serp_places.requests, "get",
                        lambda url, params, timeout: sent.update(params) or Resp({"error": "Invalid API key."}, 401))
    with pytest.raises(RuntimeError, match="Invalid API key"):
        serp_places.search({"q": "park"}, 5)
    assert sent["api_key"] == "k" and sent["hl"] == "en"
    monkeypatch.setattr(serp_places.requests, "get",
                        lambda url, params, timeout: Resp({"error": "Google hasn't returned any results for this query."}))
    assert serp_places.search({"q": "zzz"}, 5) == {}


def test_lookup_merges_google_and_osm(serp, monkeypatch):
    osm = [NearbyPlace(name="Riverdale Park East", kind="park", distance_m=360),
           NearbyPlace(name="unnamed viewpoint", kind="viewpoint", distance_m=200)]
    monkeypatch.setattr(local_context, "fetch_nearby", lambda lat, lon, r: osm)
    monkeypatch.setattr(local_context, "fetch_weather", lambda lat, lon: None)
    monkeypatch.setattr(local_context, "fetch_place", lambda lat, lon: "Riverdale, Toronto")
    ctx = local_context.lookup(GeoPoint(lat=HERE[0], lon=HERE[1]), 1.0, "", ["nature"])
    names = [p.name for p in ctx.nearby]
    assert names.count("Riverdale Park East") == 1  # Google's copy wins
    assert next(p for p in ctx.nearby if p.name == "Riverdale Park East").source == "google"
    assert "unnamed viewpoint" in names  # OSM fills in what Google doesn't list
    assert [p.distance_m for p in ctx.nearby] == sorted(p.distance_m for p in ctx.nearby)


def test_lookup_falls_back_to_osm_when_serpapi_fails(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "k")
    monkeypatch.setenv("LOCAL_CONTEXT", "on")
    local_context.clear_cache()
    monkeypatch.setattr(serp_places, "search", lambda p, t: (_ for _ in ()).throw(RuntimeError("out of searches")))
    osm = [NearbyPlace(name="Don River", kind="river", distance_m=600)]
    monkeypatch.setattr(local_context, "fetch_nearby", lambda lat, lon, r: osm)
    monkeypatch.setattr(local_context, "fetch_weather", lambda lat, lon: None)
    monkeypatch.setattr(local_context, "fetch_place", lambda lat, lon: "")
    assert [p.name for p in local_context.lookup(GeoPoint(lat=1, lon=2), 1.0).nearby] == ["Don River"]


def test_no_key_means_no_serpapi(monkeypatch):
    monkeypatch.setenv("LOCAL_CONTEXT", "on")
    local_context.clear_cache()
    monkeypatch.setattr(serp_places, "search", lambda *a: pytest.fail("no key - must not call SerpApi"))
    monkeypatch.setattr(local_context, "fetch_nearby", lambda lat, lon, r: [])
    monkeypatch.setattr(local_context, "fetch_weather", lambda lat, lon: None)
    monkeypatch.setattr(local_context, "fetch_place", lambda lat, lon: "")
    local_context.lookup(GeoPoint(lat=1, lon=2), 1.0, "", ["art"])


def test_geocode_with_serpapi(serp, monkeypatch):
    found = {"place_results": {"title": "Elora", "gps_coordinates": {"latitude": 43.68, "longitude": -80.43}}}
    monkeypatch.setattr(serp_places, "search", lambda params, timeout: found)
    monkeypatch.setattr(local_context, "_get", lambda *a: pytest.fail("SerpApi answered - no Nominatim call"))
    p = local_context.geocode("Elora")
    assert (p.lat, p.lon) == (43.68, -80.43)


def test_merge_ranks_close_well_rated_first():
    g = [NearbyPlace(name=f"P{i}", kind="park", distance_m=100 * i, rating=4.0, reviews=10, source="google")
         for i in range(1, 15)]
    merged = merge_places(g, [NearbyPlace(name="Trail", kind="trail", distance_m=50)])
    assert len(merged) == 12 and "Trail" in [p.name for p in merged]


def test_prompt_shows_rating_and_hours():
    ctx = QuestContext(place="Riverdale", nearby=[NearbyPlace(
        name="Riverdale Park East", kind="park", distance_m=350, direction="NE", rating=4.7, reviews=3120,
        open_state="Open 24 hours", source="google")])
    p = build_prompt(PreferencesIn.model_validate({"interests": ["nature"]}), context=ctx)
    assert "Riverdale Park East (park, 350 m NE, rated 4.7/5 by 3120, Open 24 hours)" in p
    assert "closed right now" in p
