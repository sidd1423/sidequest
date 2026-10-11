"""Real places near the user from Google Maps, via SerpApi (https://serpapi.com).

Used by backend/local_context.py when SERPAPI_API_KEY is set (otherwise the
free OpenStreetMap Overpass lookup is used on its own). Google Maps knows far
more named places than OSM - with ratings, reviews, addresses and whether a
place is open right now - so quests can point at a specific, well-liked spot.

Every SerpApi search uses one credit of your plan, so:
  - each quest runs at most SERPAPI_MAX_QUERIES searches (default 2): "park"
    plus one search picked from the user's interests (e.g. art -> "public art");
  - results are cached in memory for SERPAPI_CACHE_HOURS (default 24) per
    search + ~100 m area, so repeated quests from the same spot are free;
  - typed places ("Riverdale, Toronto") are geocoded with SerpApi too, cached the same way.

Config (.env): SERPAPI_API_KEY (required), SERPAPI_MAX_QUERIES, SERPAPI_CACHE_HOURS,
SERPAPI_URL (default https://serpapi.com/search.json), SERPAPI_HL (default en).
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any, Sequence

import requests

from .schemas import GeoPoint, NearbyPlace

log = logging.getLogger("sidequest.serpapi")

SERPAPI_URL = "https://serpapi.com/search.json"

# What to search Google Maps for, per interest - all outdoor, free-to-visit kinds of places.
INTEREST_QUERIES: dict[str, list[str]] = {
    "outdoors": ["hiking trail", "nature trail"],
    "nature": ["nature reserve", "garden", "ravine trail"],
    "art": ["public art", "mural", "sculpture"],
    "music": ["outdoor stage", "public square"],
    "food": ["farmers market", "picnic area"],
    "history": ["historical landmark", "monument", "heritage site"],
    "fitness": ["running trail", "outdoor fitness equipment", "sports field"],
    "photography": ["scenic lookout", "viewpoint", "bridge"],
    "gaming": ["playground", "public square"],
    "learning": ["botanical garden", "historical landmark"],
    "social": ["public square", "plaza"],
    "volunteering": ["community garden"],
    "shopping": ["outdoor market"],
    "nightlife": ["plaza", "waterfront promenade"],
    "wellness": ["garden", "quiet park"],
}
BASE_QUERY = "park"

# Google place types that are clearly indoor-only businesses - not useful for an outdoor quest.
_INDOOR_TYPES = {
    "restaurant", "bar", "cafe", "coffee shop", "store", "shopping mall", "supermarket", "grocery store",
    "bank", "pharmacy", "hotel", "gym", "movie theater", "doctor", "dentist", "hospital", "school",
    "office", "car dealer", "gas station", "clothing store", "bakery", "fast food restaurant",
}


def api_key() -> str:
    return os.getenv("SERPAPI_API_KEY", "").strip()


def is_configured() -> bool:
    return bool(api_key())


def max_queries() -> int:
    try:
        return max(1, min(5, int(os.getenv("SERPAPI_MAX_QUERIES") or 2)))
    except ValueError:
        return 2


def cache_seconds() -> float:
    try:
        return float(os.getenv("SERPAPI_CACHE_HOURS") or 24) * 3600
    except ValueError:
        return 24 * 3600.0


def zoom_for(radius_m: int) -> int:
    """Google Maps zoom so the map roughly covers the search radius."""
    if radius_m <= 600:
        return 16
    if radius_m <= 1500:
        return 15
    if radius_m <= 3000:
        return 14
    return 13


def queries_for(interests: Sequence[str], rng: random.Random | None = None) -> list[str]:
    """"park" + searches from the user's interests (a random pick each time, for variety)."""
    rng = rng or random
    options: list[str] = []
    for interest in interests:
        key = interest.strip().lower()
        if not key:
            continue
        options.extend(INTEREST_QUERIES.get(key, [key]))  # custom interests are searched as typed
    options = [o for o in dict.fromkeys(options) if o != BASE_QUERY]
    rng.shuffle(options)
    return ([BASE_QUERY] + options)[: max_queries()]


def search(params: dict[str, Any], timeout: float) -> dict:
    r = requests.get(os.getenv("SERPAPI_URL") or SERPAPI_URL,
                     params={"hl": os.getenv("SERPAPI_HL") or "en", **params, "api_key": api_key()},
                     timeout=timeout)
    try:
        data = r.json()
    except ValueError:
        r.raise_for_status()
        raise
    if data.get("error"):  # e.g. "Invalid API key", "Your account has run out of searches."
        # "hasn't returned any results" is a normal empty answer, not a failure.
        if "any results" in str(data["error"]).lower():
            return {}
        raise RuntimeError(f"SerpApi: {data['error']}")
    r.raise_for_status()
    return data


def _results(data: dict) -> list[dict]:
    """Google Maps answers a search with local_results, or place_results when it matched one place."""
    if isinstance(data.get("local_results"), list):
        return data["local_results"]
    if isinstance(data.get("place_results"), dict):
        return [data["place_results"]]
    return []


def _kind(item: dict) -> str:
    kind = (item.get("type") or "").strip()
    if not kind and item.get("types"):
        kind = str(item["types"][0])
    return kind.lower() or "place"


def _is_indoor_business(item: dict) -> bool:
    types = {str(t).strip().lower() for t in ([item.get("type")] + list(item.get("types") or [])) if t}
    outdoorish = any(w in t for t in types - _INDOOR_TYPES for w in ("park", "garden", "trail", "beach", "lookout", "landmark",
                                                       "monument", "plaza", "square", "market", "playground",
                                                       "art", "sculpture", "bridge", "reserve", "field"))
    return bool(types & _INDOOR_TYPES) and not outdoorish


def parse_places(data: dict, lat: float, lon: float, radius_m: int,
                 distance_m, compass) -> list[NearbyPlace]:
    """SerpApi Google Maps results -> NearbyPlace (within the radius, open-to-visit, outdoor-ish)."""
    out: list[NearbyPlace] = []
    for item in _results(data):
        gps = item.get("gps_coordinates") or {}
        plat, plon = gps.get("latitude"), gps.get("longitude")
        name = (item.get("title") or "").strip()
        if plat is None or plon is None or not name:
            continue
        state = (item.get("open_state") or "").strip()
        if "permanently closed" in state.lower() or "temporarily closed" in state.lower():
            continue
        if _is_indoor_business(item):
            continue
        d = distance_m(lat, lon, plat, plon)
        if d > radius_m * 1.25:
            continue
        rating = item.get("rating")
        reviews = item.get("reviews")
        out.append(NearbyPlace(
            name=name, kind=_kind(item), distance_m=int(round(d / 10) * 10),
            direction=compass(lat, lon, plat, plon) if d > 30 else "",
            lat=round(float(plat), 5), lon=round(float(plon), 5),
            rating=float(rating) if isinstance(rating, (int, float)) else None,
            reviews=int(reviews) if isinstance(reviews, (int, float)) else None,
            open_state=state[:80], address=(item.get("address") or "")[:160], source="google",
        ))
    return out


def nearby(lat: float, lon: float, radius_m: int, interests: Sequence[str], *, timeout: float,
           cached, distance_m, compass) -> list[NearbyPlace]:
    """Google Maps places for each query (cached per query + area). Raises if every search failed."""
    zoom = zoom_for(radius_m)
    found: list[NearbyPlace] = []
    errors: list[str] = []
    for q in queries_for(interests):
        def fetch(q: str = q) -> dict:
            return search({"engine": "google_maps", "type": "search", "q": q,
                           "ll": f"@{lat:.5f},{lon:.5f},{zoom}z"}, timeout)
        try:
            data = cached(("serpapi", q, round(lat, 3), round(lon, 3), zoom), cache_seconds(), fetch)
        except Exception as exc:
            errors.append(f"{q}: {exc}")
            continue
        found.extend(parse_places(data, lat, lon, radius_m, distance_m, compass))
    if errors and not found:
        raise RuntimeError("; ".join(errors))
    for e in errors:
        log.warning("SerpApi search failed (%s)", e)
    return found


def geocode(query: str, *, timeout: float) -> GeoPoint | None:
    """A typed place -> coordinates (Google Maps' best match)."""
    data = search({"engine": "google_maps", "type": "search", "q": query}, timeout)
    for item in _results(data):
        gps = item.get("gps_coordinates") or {}
        if gps.get("latitude") is not None and gps.get("longitude") is not None:
            return GeoPoint(lat=float(gps["latitude"]), lon=float(gps["longitude"]), accuracy_m=1000)
    return None
