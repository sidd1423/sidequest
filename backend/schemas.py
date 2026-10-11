"""Shared data model for user preferences and quests.

Used by both the FastAPI backend (request/response validation) and the
Streamlit frontend (option lists + client-side validation), so the two can
never drift apart.

Sidequests are short (5-30 minute) things to do OUTSIDE, RIGHT NOW - the
point is to get people out of the house more often. So preferences describe
how much time the user has right now, not when or whether to go outside.
Where they are, the weather and what's nearby are looked up live from the
device's location for every quest (backend/local_context.py) instead of
being asked once in the profile.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Interest(str, Enum):
    OUTDOORS = "outdoors"
    NATURE = "nature"
    ART = "art"
    MUSIC = "music"
    FOOD = "food"
    HISTORY = "history"
    FITNESS = "fitness"
    PHOTOGRAPHY = "photography"
    GAMING = "gaming"
    LEARNING = "learning"
    SOCIAL = "social"
    VOLUNTEERING = "volunteering"
    SHOPPING = "shopping"
    NIGHTLIFE = "nightlife"
    WELLNESS = "wellness"


class Difficulty(str, Enum):
    EASY = "easy"
    MODERATE = "moderate"
    CHALLENGING = "challenging"
    EXTREME = "extreme"


class AccessibilityNeed(str, Enum):
    WHEELCHAIR = "wheelchair_accessible"
    STEP_FREE = "step_free"
    LIMITED_MOBILITY = "limited_mobility"
    FREQUENT_REST = "frequent_rest_stops"
    VISUAL = "visual_impairment"
    HEARING = "hearing_impairment"
    SENSORY_FRIENDLY = "sensory_friendly"
    SERVICE_ANIMAL = "service_animal"
    ACCESSIBLE_RESTROOMS = "accessible_restrooms"


class Setting(str, Enum):
    """Kept only so older stored quests still load - every new quest is outdoors."""

    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    EITHER = "either"


class CrowdLevel(str, Enum):
    QUIET = "quiet"
    MODERATE = "moderate"
    BUSY = "busy"


class GroupSize(str, Enum):
    SOLO = "solo"
    PAIR = "pair"
    SMALL_GROUP = "small_group"
    LARGE_GROUP = "large_group"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

MIN_QUEST_MINUTES = 5
MAX_QUEST_MINUTES = 30
MAX_TRAVEL_KM = 5.0


class Availability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_minutes: int = Field(
        15, ge=MIN_QUEST_MINUTES, le=MAX_QUEST_MINUTES, description="Minutes the user has right now"
    )


class Accessibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs: list[AccessibilityNeed] = Field(default_factory=list)
    notes: str = Field("", max_length=500)


class Environment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crowd_tolerance: CrowdLevel = CrowdLevel.MODERATE
    group_size: GroupSize = GroupSize.SOLO
    max_travel_km: float = Field(1.0, ge=0, le=MAX_TRAVEL_KM, description="How far from where they are now")


# ---------------------------------------------------------------------------
# Top-level models
# ---------------------------------------------------------------------------

class PreferencesIn(BaseModel):
    """Payload the frontend sends to the backend."""

    model_config = ConfigDict(extra="forbid")

    interests: list[Interest] = Field(default_factory=list)
    custom_interests: list[str] = Field(default_factory=list, max_length=20)
    availability: Availability = Field(default_factory=Availability)
    difficulty: Difficulty = Difficulty.MODERATE
    energy_level: int = Field(3, ge=1, le=5, description="1 = very low, 5 = very high")
    accessibility: Accessibility = Field(default_factory=Accessibility)
    environment: Environment = Field(default_factory=Environment)

    @model_validator(mode="before")
    @classmethod
    def drop_legacy_fields(cls, data):
        """Older apps (and queued offline edits) still send weather limits and
        surroundings - accept and ignore them; they're looked up live now."""
        if isinstance(data, dict) and ("weather" in data or "surroundings" in (data.get("environment") or {})):
            data = dict(data)
            data.pop("weather", None)
            if isinstance(data.get("environment"), dict):
                data["environment"] = {k: v for k, v in data["environment"].items() if k != "surroundings"}
        return data

    @field_validator("custom_interests")
    @classmethod
    def clean_custom(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for item in v:
            item = item.strip().lower()[:40]
            if item and item not in seen:
                seen.append(item)
        return seen

    @model_validator(mode="after")
    def require_interest(self) -> "PreferencesIn":
        if not self.interests and not self.custom_interests:
            raise ValueError("Pick at least one interest")
        return self

    @staticmethod
    def upgrade_stored(data: dict) -> dict:
        """Adapt preferences saved by older versions of the app (which had
        indoor/outdoor, time-of-day, hours-long durations, surroundings and
        weather limits) to the current quick-outdoor-quest model, so they still load."""
        data = dict(data)
        data.pop("weather", None)  # now looked up live from the user's location
        avail = dict(data.get("availability") or {})
        avail.pop("preferred_times", None)
        if "duration_minutes" in avail:
            avail["duration_minutes"] = max(MIN_QUEST_MINUTES, min(MAX_QUEST_MINUTES, int(avail["duration_minutes"])))
        data["availability"] = avail
        env = dict(data.get("environment") or {})
        env.pop("setting", None)
        env.pop("surroundings", None)  # now looked up live from the user's location
        if "max_travel_km" in env:
            env["max_travel_km"] = max(0.0, min(MAX_TRAVEL_KM, float(env["max_travel_km"])))
        data["environment"] = env
        return data


class PreferencesOut(PreferencesIn):
    """What the backend returns: the stored preferences plus metadata."""

    user_id: str
    created_at: datetime
    updated_at: datetime


USER_ID_PATTERN = r"^[A-Za-z0-9_.@-]{3,64}$"


# ---------------------------------------------------------------------------
# Quests & feedback
# ---------------------------------------------------------------------------

class QuestStatus(str, Enum):
    SUGGESTED = "suggested"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class GeoPoint(BaseModel):
    """A position from the device (WGS84)."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0, le=100_000)


class QuestSettings(BaseModel):
    """Per-quest choices the mobile app asks for right before each quest.

    Any field left out falls back to the saved profile. `location` (from the
    device) or `place` (typed, e.g. "Riverdale, Toronto") lets the backend look
    up the weather and real places nearby; they aren't part of the profile."""

    model_config = ConfigDict(extra="forbid")

    location: GeoPoint | None = None
    place: str | None = Field(None, max_length=120, description="Where the user is, if location is off")

    duration_minutes: int | None = Field(None, ge=MIN_QUEST_MINUTES, le=MAX_QUEST_MINUTES)
    difficulty: Difficulty | None = None
    energy_level: int | None = Field(None, ge=1, le=5)
    max_travel_km: float | None = Field(None, ge=0, le=MAX_TRAVEL_KM)
    group_size: GroupSize | None = None

    def apply(self, prefs: "PreferencesIn") -> "PreferencesIn":
        data = prefs.model_dump()
        if self.duration_minutes is not None:
            data["availability"]["duration_minutes"] = self.duration_minutes
        if self.difficulty is not None:
            data["difficulty"] = self.difficulty
        if self.energy_level is not None:
            data["energy_level"] = self.energy_level
        if self.max_travel_km is not None:
            data["environment"]["max_travel_km"] = self.max_travel_km
        if self.group_size is not None:
            data["environment"]["group_size"] = self.group_size
        return PreferencesIn.model_validate(data)


class Quest(BaseModel):
    """A single sidequest, as produced by the LLM (validated)."""

    title: str = Field(..., min_length=3, max_length=120)
    summary: str = Field(..., min_length=10, max_length=600)
    steps: list[str] = Field(..., min_length=1, max_length=10)
    # Wide bounds so older stored quests still load; generate_quest enforces
    # MIN_QUEST_MINUTES..the user's available minutes for new quests.
    estimated_minutes: int = Field(..., ge=1, le=720)
    difficulty: Difficulty
    energy_required: int = Field(..., ge=1, le=5)
    setting: Setting = Setting.OUTDOOR
    tags: list[str] = Field(default_factory=list, max_length=8)
    accessibility_notes: str = Field("", max_length=400)
    weather_backup: str = Field("", max_length=400, description="Outdoor plan B if the weather turns")
    why_it_fits: str = Field("", max_length=400)  # no longer requested from Gemma; kept for old quests

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(t.strip().lower() for t in v if t.strip()))


class QuestExample(BaseModel):
    """An example quest used to steer generation - from the Tiger Data library
    or from the user's own highly-rated quests."""

    quest_text: str
    category: str = "general"
    duration_minutes: int
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)
    similarity: float | None = None
    source: str = "library"

    @classmethod
    def from_quest(cls, quest: "Quest") -> "QuestExample":
        return cls(
            quest_text=f"{quest.title}: {quest.summary}",
            category=quest.tags[0] if quest.tags else "general",
            duration_minutes=quest.estimated_minutes,
            difficulty=quest.difficulty,
            tags=quest.tags,
            source="user_history",
        )


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: bool
    rating: int | None = Field(
        None, ge=1, le=5,
        description="1 = hated it, 5 = loved it. Required if completed, optional if not finished",
    )
    comment: str = Field("", max_length=500)
    time_logged_minutes: int | None = Field(
        None, ge=0, le=1440, description="How long the user actually spent on the quest"
    )
    completed_at: datetime | None = Field(
        None,
        description="When the quest was completed (the app may sync it later). Counts for the "
        "daily streak; not stored in the feedback itself. Defaults to when the feedback arrives.",
    )

    @model_validator(mode="after")
    def rating_if_completed(self) -> "FeedbackIn":
        if self.completed and self.rating is None:
            raise ValueError("Please rate a quest you completed")
        return self


class FeedbackEntry(FeedbackIn):
    """Feedback joined with the quest it refers to - what generate_quest() consumes."""

    quest_title: str
    quest_tags: list[str] = Field(default_factory=list)
    created_at: datetime


class PartyMemberTag(BaseModel):
    user_id: str
    name: str
    status: str  # invited | joined | declined


class PartyTag(BaseModel):
    """Set on quests that are part of a group quest (backend/parties.py)."""

    party_id: int
    host_id: str
    size: int  # people the quest was made for (joined when it started)
    members: list[PartyMemberTag]


class WeatherNow(BaseModel):
    """Weather where the user is when the quest was made (Open-Meteo)."""

    temp_c: float
    feels_like_c: float | None = None
    condition: str = ""  # e.g. "light rain"
    weather_code: int | None = None  # WMO code
    precipitation_mm: float | None = None
    rain_chance_pct: int | None = None  # highest chance of rain/snow over the next 2 hours
    wind_kmh: float | None = None
    gusts_kmh: float | None = None
    uv_index: float | None = None
    is_day: bool | None = None
    air_quality_index: int | None = None  # US AQI
    local_time: str | None = None  # "17:40" in the user's time zone
    sunrise: str | None = None  # "07:21"
    sunset: str | None = None  # "18:52"


class NearbyPlace(BaseModel):
    """A real outdoor spot near the user (OpenStreetMap)."""

    name: str
    kind: str  # park, playground, viewpoint, river, beach, artwork, ...
    distance_m: int
    direction: str = ""  # N, NE, E, ...
    lat: float | None = None
    lon: float | None = None


class QuestContext(BaseModel):
    """Where/when a quest was generated - shown on the quest card and used in the prompt."""

    place: str = ""  # "Riverdale, Toronto"
    lat: float | None = None  # rounded to ~100 m
    lon: float | None = None
    weather: WeatherNow | None = None
    nearby: list[NearbyPlace] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.place and self.weather is None and not self.nearby


class RouteSummary(BaseModel):
    """The recorded path for a quest (full points: GET .../route)."""

    distance_m: int
    duration_seconds: int
    points: int


class QuestRecord(BaseModel):
    """A stored quest plus its lifecycle metadata."""

    id: int
    user_id: str
    status: QuestStatus
    quest: Quest
    feedback: FeedbackIn | None = None
    created_at: datetime
    model: str = ""
    party: PartyTag | None = None  # group quest with friends
    context: QuestContext | None = None  # weather + place when it was generated
    route: RouteSummary | None = None  # the path the user recorded while doing it


class PastQuest(BaseModel):
    """One of the user's previous sidequests (from the user history database),
    used to steer the next one - more like the loved ones, away from the
    disliked ones, and never a repeat."""

    app_quest_id: int | None = None
    title: str
    quest_text: str
    category: str = "general"
    duration_minutes: int
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)
    status: QuestStatus = QuestStatus.SUGGESTED
    completed: bool | None = None
    rating: int | None = Field(None, ge=1, le=5)
    comment: str = ""
    time_logged_minutes: int = 0
    created_at: datetime | None = None

    # Ratings count whether or not the user finished the quest.
    @property
    def loved(self) -> bool:
        return (self.rating or 0) >= 4

    @property
    def disliked(self) -> bool:
        return self.rating is not None and self.rating <= 2
