"""Shared data model for user preferences.

Used by both the FastAPI backend (request/response validation) and the
Streamlit frontend (option lists + client-side validation), so the two can
never drift apart.
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


class TimeOfDay(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


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

class Availability(BaseModel):
    duration_minutes: int = Field(60, ge=15, le=720, description="How long the user has")
    preferred_times: list[TimeOfDay] = Field(default_factory=list)


class Accessibility(BaseModel):
    needs: list[AccessibilityNeed] = Field(default_factory=list)
    notes: str = Field("", max_length=500)


class Environment(BaseModel):
    setting: Setting = Setting.EITHER
    surroundings: list[Surroundings] = Field(default_factory=list)
    crowd_tolerance: CrowdLevel = CrowdLevel.MODERATE
    group_size: GroupSize = GroupSize.SOLO
    max_travel_km: int = Field(10, ge=0, le=500)


class WeatherConstraints(BaseModel):
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


class PreferencesOut(PreferencesIn):
    """What the backend returns: the stored preferences plus metadata."""

    user_id: str
    created_at: datetime
    updated_at: datetime


USER_ID_PATTERN = r"^[A-Za-z0-9_.@-]{3,64}$"
