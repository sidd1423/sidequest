"""Shared data model for user preferences and quests.

Used by both the FastAPI backend (request/response validation) and the
Streamlit frontend (option lists + client-side validation), so the two can
never drift apart.

Sidequests are short (5-30 minute) things to do OUTSIDE, RIGHT NOW - the
point is to get people out of the house more often. So preferences describe
how much time the user has right now and what's around them, not when or
whether to go outside.
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


class Surroundings(str, Enum):
    URBAN = "urban"
    SUBURBAN = "suburban"
    RURAL = "rural"
    WILDERNESS = "wilderness"
    WATERFRONT = "waterfront"


class CrowdLevel(str, Enum):
    QUIET = "quiet"
    MODERATE = "moderate"
    BUSY = "busy"


class GroupSize(str, Enum):
    SOLO = "solo"
    PAIR = "pair"
    SMALL_GROUP = "small_group"
    LARGE_GROUP = "large_group"


class WeatherCondition(str, Enum):
    RAIN = "rain"
    SNOW = "snow"
    WIND = "wind"
    EXTREME_HEAT = "extreme_heat"
    EXTREME_COLD = "extreme_cold"
    HIGH_UV = "high_uv"
    POOR_AIR_QUALITY = "poor_air_quality"


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

    surroundings: list[Surroundings] = Field(default_factory=list, description="What's around the user now")
    crowd_tolerance: CrowdLevel = CrowdLevel.MODERATE
    group_size: GroupSize = GroupSize.SOLO
    max_travel_km: float = Field(1.0, ge=0, le=MAX_TRAVEL_KM, description="How far from where they are now")


class WeatherConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    avoid: list[WeatherCondition] = Field(default_factory=list)
    min_temp_c: int = Field(5, ge=-40, le=50)
    max_temp_c: int = Field(30, ge=-40, le=50)

    @model_validator(mode="after")
    def check_range(self) -> "WeatherConstraints":
        if self.min_temp_c > self.max_temp_c:
            raise ValueError("min_temp_c must be less than or equal to max_temp_c")
        return self


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
    weather: WeatherConstraints = Field(default_factory=WeatherConstraints)

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
        indoor/outdoor, time-of-day and hours-long durations) to the current
        quick-outdoor-quest model, so they still load."""
        data = dict(data)
        avail = dict(data.get("availability") or {})
        avail.pop("preferred_times", None)
        if "duration_minutes" in avail:
            avail["duration_minutes"] = max(MIN_QUEST_MINUTES, min(MAX_QUEST_MINUTES, int(avail["duration_minutes"])))
        data["availability"] = avail
        env = dict(data.get("environment") or {})
        env.pop("setting", None)
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


class QuestSettings(BaseModel):
    """Per-quest choices the mobile app asks for right before each quest.

    Any field left out falls back to the saved profile."""

    model_config = ConfigDict(extra="forbid")

    duration_minutes: int | None = Field(None, ge=MIN_QUEST_MINUTES, le=MAX_QUEST_MINUTES)
    difficulty: Difficulty | None = None
    energy_level: int | None = Field(None, ge=1, le=5)
    max_travel_km: float | None = Field(None, ge=0, le=MAX_TRAVEL_KM)

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
    why_it_fits: str = Field("", max_length=400)

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


class QuestRecord(BaseModel):
    """A stored quest plus its lifecycle metadata."""

    id: int
    user_id: str
    status: QuestStatus
    quest: Quest
    feedback: FeedbackIn | None = None
    created_at: datetime
    model: str = ""


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
