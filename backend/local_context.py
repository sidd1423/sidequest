"""What's around the user right now: weather, place name and real outdoor spots nearby.

Replaces the old profile questions about weather, temperature and "what's
around you" - every quest is generated for the conditions where the user
actually is. All services are free and need no API key:

  Open-Meteo forecast + air quality   https://open-meteo.com
  Nominatim reverse/forward geocoding https://nominatim.org (OpenStreetMap; max 1 request/s,
                                      needs a real User-Agent - set NOMINATIM_EMAIL if you can)
  Overpass API                        https://overpass-api.de (OpenStreetMap places)

Every lookup is optional and has a short timeout: if one fails the quest is
still generated with whatever we did get. Results are cached in memory
(weather 10 min, places 1 day) so repeated quests don't hammer the services.

Config (.env): LOCAL_CONTEXT=off disables all lookups; OPEN_METEO_URL,
AIR_QUALITY_URL, NOMINATIM_URL, OVERPASS_URL override the endpoints;
CONTEXT_TIMEOUT (seconds per request, default 6); NOMINATIM_EMAIL.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import requests

from .schemas import MAX_TRAVEL_KM, GeoPoint, NearbyPlace, QuestContext, WeatherNow

log = logging.getLogger("sidequest.context")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Sidequest/0.3 (https://github.com/sidd1423/sidequest)"

WEATHER_TTL = 10 * 60
PLACE_TTL = 24 * 3600
MAX_NEARBY = 12
MIN_RADIUS_M = 300
MAX_RADIUS_M = int(MAX_TRAVEL_KM * 1000)

# WMO weather interpretation codes (Open-Meteo `weather_code`).
WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def enabled() -> bool:
    return os.getenv("LOCAL_CONTEXT", "on").strip().lower() not in {"off", "false", "0", "no"}


def _timeout() -> float:
    try:
        return float(os.getenv("CONTEXT_TIMEOUT") or 6)
    except ValueError:
        return 6.0


def _headers() -> dict[str, str]:
    email = os.getenv("NOMINATIM_EMAIL", "").strip()
    return {"User-Agent": USER_AGENT + (f" {email}" if email else ""), "Accept-Language": "en"}


# ---------------------------------------------------------------------------
# Small TTL cache (process memory)
# ---------------------------------------------------------------------------

_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: tuple, ttl: float, fetch: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fetch()
    with _cache_lock:
        if len(_cache) > 2000:
            _cache.clear()
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _get(url: str, params: dict[str, Any]) -> Any:
    r = requests.get(url, params=params, headers=_headers(), timeout=_timeout())
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def compass(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Rough direction from point 1 to point 2: N, NE, E, ..."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((bearing + 22.5) // 45) % 8]


# ---------------------------------------------------------------------------
# Weather (Open-Meteo)
# ---------------------------------------------------------------------------

def _hhmm(iso: str | None) -> str | None:
    if not iso or "T" not in iso:
        return None
    return iso.split("T", 1)[1][:5]


def parse_weather(forecast: dict, air: dict | None = None) -> WeatherNow:
    cur = forecast.get("current") or {}
    code = cur.get("weather_code")
    hourly = forecast.get("hourly") or {}
    chances = [c for c in (hourly.get("precipitation_probability") or [])[:3] if isinstance(c, (int, float))]
    daily = forecast.get("daily") or {}
    is_day = cur.get("is_day")
    aqi = ((air or {}).get("current") or {}).get("us_aqi")
    return WeatherNow(
        temp_c=float(cur["temperature_2m"]),
        feels_like_c=cur.get("apparent_temperature"),
        condition=WMO_CODES.get(code, "") if isinstance(code, int) else "",
        weather_code=code if isinstance(code, int) else None,
        precipitation_mm=cur.get("precipitation"),
        rain_chance_pct=int(max(chances)) if chances else None,
        wind_kmh=cur.get("wind_speed_10m"),
        gusts_kmh=cur.get("wind_gusts_10m"),
        uv_index=cur.get("uv_index"),
        is_day=bool(is_day) if is_day is not None else None,
        air_quality_index=int(aqi) if isinstance(aqi, (int, float)) else None,
        local_time=_hhmm(cur.get("time")),
        sunrise=_hhmm((daily.get("sunrise") or [None])[0]),
        sunset=_hhmm((daily.get("sunset") or [None])[0]),
    )


def fetch_weather(lat: float, lon: float) -> WeatherNow | None:
    def fetch() -> WeatherNow | None:
        forecast = _get(os.getenv("OPEN_METEO_URL") or OPEN_METEO_URL, {
            "latitude": round(lat, 3), "longitude": round(lon, 3),
            "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,"
                       "wind_gusts_10m,uv_index,is_day",
            "hourly": "precipitation_probability", "forecast_hours": 3,
            "daily": "sunrise,sunset", "forecast_days": 1, "timezone": "auto",
        })
        air = None
        try:
            air = _get(os.getenv("AIR_QUALITY_URL") or AIR_QUALITY_URL, {
                "latitude": round(lat, 3), "longitude": round(lon, 3), "current": "us_aqi"})
        except Exception as exc:  # air quality is a nice-to-have
            log.info("Air quality lookup failed: %s", exc)
        return parse_weather(forecast, air)

    return _cached(("weather", round(lat, 2), round(lon, 2)), WEATHER_TTL, fetch)


# ---------------------------------------------------------------------------
# Place name (Nominatim)
# ---------------------------------------------------------------------------

def parse_place(data: dict) -> str:
    addr = data.get("address") or {}
    local = next((addr[k] for k in ("neighbourhood", "suburb", "quarter", "hamlet", "village", "city_district")
                  if addr.get(k)), "")
    town = next((addr[k] for k in ("city", "town", "village", "municipality", "county") if addr.get(k)), "")
    parts = [p for p in (local, town) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    if not parts:
        return (data.get("display_name") or "").split(",")[0].strip()
    return ", ".join(parts)


def fetch_place(lat: float, lon: float) -> str:
    def fetch() -> str:
        data = _get((os.getenv("NOMINATIM_URL") or NOMINATIM_URL).rstrip("/") + "/reverse",
                    {"lat": round(lat, 4), "lon": round(lon, 4), "format": "jsonv2", "zoom": 16,
                     "addressdetails": 1})
        return parse_place(data)

    return _cached(("place", round(lat, 3), round(lon, 3)), PLACE_TTL, fetch)


def geocode(query: str) -> GeoPoint | None:
    """A typed place ("Riverdale, Toronto") -> its coordinates, or None."""
    query = query.strip()
    if not query or not enabled():
        return None

    def fetch() -> GeoPoint | None:
        rows = _get((os.getenv("NOMINATIM_URL") or NOMINATIM_URL).rstrip("/") + "/search",
                    {"q": query, "format": "jsonv2", "limit": 1})
        if not rows:
            return None
        return GeoPoint(lat=float(rows[0]["lat"]), lon=float(rows[0]["lon"]), accuracy_m=1000)

    try:
        return _cached(("geocode", query.lower()), PLACE_TTL, fetch)
    except Exception as exc:
        log.warning("Couldn't look up %r: %s", query, exc)
        return None


# ---------------------------------------------------------------------------
# Nearby outdoor places (Overpass)
# ---------------------------------------------------------------------------

# (OSM key, value regex, require a name)
_PLACE_FILTERS = [
    ("leisure", "park|garden|playground|nature_reserve|dog_park|fitness_station|track|pitch|common", True),
    ("natural", "water|beach|wood|peak|cliff|spring", True),
    ("waterway", "river|stream|canal", True),
    ("tourism", "viewpoint|artwork|picnic_site|attraction", False),
    ("historic", ".", True),
    ("amenity", "fountain|marketplace", True),
    ("highway", "pedestrian|footway|path|cycleway", True),
]

_KIND_LABELS = {
    "nature_reserve": "nature reserve", "dog_park": "dog park", "fitness_station": "outdoor gym",
    "picnic_site": "picnic site", "track": "running track", "pitch": "sports field", "wood": "woods",
    "water": "pond/lake", "pedestrian": "pedestrian street", "footway": "footpath", "path": "trail",
    "cycleway": "bike path", "common": "green",
}


def build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    around = f"(around:{radius_m},{lat:.5f},{lon:.5f})"
    lines = []
    for key, values, named in _PLACE_FILTERS:
        name = '["name"]' if named else ""
        lines.append(f'  nwr{around}["{key}"~"^({values})$"]{name};' if values != "." else
                     f'  nwr{around}["{key}"]{name};')
    return "[out:json][timeout:8];\n(\n" + "\n".join(lines) + "\n);\nout center tags 150;"


def _kind(tags: dict) -> str | None:
    for key, _values, _named in _PLACE_FILTERS:
        if key in tags:
            value = tags[key]
            if key == "historic":
                return "historic site" if value in ("yes", "") else f"historic {value.replace('_', ' ')}"
            return _KIND_LABELS.get(value, value.replace("_", " "))
    return None


def parse_nearby(data: dict, lat: float, lon: float, radius_m: int, limit: int = MAX_NEARBY) -> list[NearbyPlace]:
    best: dict[str, NearbyPlace] = {}
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        kind = _kind(tags)
        if kind is None:
            continue
        plat = el.get("lat", (el.get("center") or {}).get("lat"))
        plon = el.get("lon", (el.get("center") or {}).get("lon"))
        if plat is None or plon is None:
            continue
        d = distance_m(lat, lon, plat, plon)
        if d > radius_m * 1.25:  # long rivers/parks: the centre may be a bit outside
            continue
        name = (tags.get("name") or "").strip() or f"unnamed {kind}"
        key = name.lower()
        place = NearbyPlace(name=name, kind=kind, distance_m=int(round(d / 10) * 10),
                            direction=compass(lat, lon, plat, plon) if d > 30 else "",
                            lat=round(plat, 5), lon=round(plon, 5))
        if key not in best or place.distance_m < best[key].distance_m:
            best[key] = place
    # Closest first, but at most 3 of a kind so one park-heavy area doesn't crowd out the rest.
    out, per_kind = [], {}
    paths = {"footpath", "trail", "bike path", "pedestrian street"}
    for p in sorted(best.values(), key=lambda p: (p.name.startswith("unnamed"), p.distance_m)):
        cap = 2 if p.kind in paths else 3
        if per_kind.get(p.kind, 0) >= cap:
            continue
        per_kind[p.kind] = per_kind.get(p.kind, 0) + 1
        out.append(p)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda p: p.distance_m)


def search_radius(max_travel_km: float) -> int:
    """Places within the user's travel distance (it's out *and back*, so half of a
    long walk), never smaller than a short stroll."""
    return max(MIN_RADIUS_M, min(MAX_RADIUS_M, int(max_travel_km * 1000)))


def fetch_nearby(lat: float, lon: float, radius_m: int) -> list[NearbyPlace]:
    def fetch() -> list[NearbyPlace]:
        r = requests.post(os.getenv("OVERPASS_URL") or OVERPASS_URL,
                          data={"data": build_overpass_query(lat, lon, radius_m)},
                          headers=_headers(), timeout=_timeout() + 4)
        r.raise_for_status()
        return parse_nearby(r.json(), lat, lon, radius_m)

    return _cached(("nearby", round(lat, 3), round(lon, 3), radius_m), PLACE_TTL, fetch)


# ---------------------------------------------------------------------------
# Everything together
# ---------------------------------------------------------------------------

_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="context")


def lookup(location: GeoPoint, max_travel_km: float = 1.0, place_hint: str = "") -> QuestContext:
    """Weather + place name + nearby spots, fetched in parallel. Never raises:
    parts that fail are left empty."""
    lat, lon = location.lat, location.lon
    ctx = QuestContext(place=place_hint, lat=round(lat, 3), lon=round(lon, 3))
    if not enabled():
        return ctx
    jobs = {
        "weather": _pool.submit(fetch_weather, lat, lon),
        "place": _pool.submit(fetch_place, lat, lon),
        "nearby": _pool.submit(fetch_nearby, lat, lon, search_radius(max_travel_km)),
    }
    deadline = time.monotonic() + _timeout() + 6
    for name, job in jobs.items():
        try:
            value = job.result(timeout=max(0.1, deadline - time.monotonic()))
        except Exception as exc:
            log.warning("%s lookup failed for (%.3f, %.3f): %s", name, lat, lon, exc)
            continue
        if name == "weather":
            ctx.weather = value
        elif name == "place" and value and not place_hint:
            ctx.place = value
        elif name == "nearby":
            ctx.nearby = value
    return ctx


def describe_for_search(ctx: QuestContext | None) -> str:
    """A sentence for the example-quest embedding search."""
    if ctx is None or ctx.is_empty:
        return ""
    bits = []
    w = ctx.weather
    if w is not None:
        bits.append(f"{w.condition or 'outside'}, {w.temp_c:.0f} degrees")
        if w.is_day is False:
            bits.append("after dark")
    kinds = list(dict.fromkeys(p.kind for p in ctx.nearby))[:5]
    if kinds:
        bits.append("near a " + ", ".join(kinds))
    return ("Right now: " + "; ".join(bits) + ".") if bits else ""
