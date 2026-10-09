"""Sidequest - user preference interface (Streamlit frontend).

Run the backend first:   uvicorn backend.main:app --reload
Then this app:           streamlit run app.py
"""

from __future__ import annotations

import re
from enum import Enum

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from backend.schemas import (
    USER_ID_PATTERN,
    AccessibilityNeed,
    CrowdLevel,
    Difficulty,
    GroupSize,
    Interest,
    PreferencesIn,
    Setting,
    Surroundings,
    TimeOfDay,
    WeatherCondition,
)
from frontend import api_client
from frontend.api_client import BackendError

load_dotenv()

st.set_page_config(page_title="Sidequest · Preferences", page_icon="🧭", layout="centered")

ENERGY_LABELS = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high"}
DIFFICULTY_HELP = {
    Difficulty.EASY: "Relaxed, no prep needed",
    Difficulty.MODERATE: "Some effort or planning",
    Difficulty.CHALLENGING: "Physically or mentally demanding",
    Difficulty.EXTREME: "Push your limits",
}


LABEL_OVERRIDES = {"high_uv": "High UV", "small_group": "Small group (3-6)", "large_group": "Large group (7+)", "pair": "Pair (2)"}


def label(value: Enum | str) -> str:
    """'wheelchair_accessible' -> 'Wheelchair accessible'."""
    raw = value.value if isinstance(value, Enum) else str(value)
    return LABEL_OVERRIDES.get(raw, raw.replace("_", " ").capitalize())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

ss = st.session_state
ss.setdefault("prefs", None)  # last preferences loaded from / saved to the backend
ss.setdefault("form_version", 0)  # bump to re-seed widgets after loading
ss.setdefault("last_saved", None)


def current_defaults() -> dict:
    """Preferences used to pre-fill the form (loaded from backend, or defaults)."""
    if ss.prefs is not None:
        return ss.prefs
    return {
        "interests": [],
        "custom_interests": [],
        "availability": {"duration_minutes": 60, "preferred_times": []},
        "accessibility": {"needs": [], "notes": ""},
        "environment": {
            "setting": "either", "surroundings": [], "crowd_tolerance": "moderate",
            "group_size": "solo", "max_travel_km": 10,
        },
        "weather": {"avoid": [], "min_temp_c": 5, "max_temp_c": 30},
        "difficulty": "moderate",
        "energy_level": 3,
    }


# ---------------------------------------------------------------------------
# Sidebar: backend status + profile
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Profile")
    healthy = api_client.is_healthy()
    if healthy:
        st.success(f"Backend connected\n\n`{api_client.base_url()}`", icon="✅")
    else:
        st.error(
            f"Backend offline at `{api_client.base_url()}`.\n\n"
            "Start it with `uvicorn backend.main:app --reload`.",
            icon="⚠️",
        )

    user_id = st.text_input(
        "User ID",
        key="user_id",
        placeholder="e.g. gowtham",
        help="3-64 characters: letters, numbers, _ . @ -",
    ).strip()
    valid_id = bool(re.fullmatch(USER_ID_PATTERN, user_id))
    if user_id and not valid_id:
        st.warning("Use 3-64 letters, numbers, or _ . @ -")

    if st.button("Load saved preferences", disabled=not (healthy and valid_id), use_container_width=True):
        try:
            loaded = api_client.get_preferences(user_id)
        except BackendError as e:
            st.error(str(e))
        else:
            if loaded is None:
                st.info("No saved preferences yet. Fill in the form to create them.")
                ss.prefs = None
            else:
                ss.prefs = loaded
                st.toast("Preferences loaded", icon="📥")
            ss.form_version += 1
            st.rerun()

    if ss.last_saved:
        st.caption(f"Last saved: {ss.last_saved}")


# ---------------------------------------------------------------------------
# Main form
# ---------------------------------------------------------------------------

st.title("🧭 Sidequest")
st.write("Tell us what you're into and what fits your day. We'll use this to suggest sidequests that match.")

d = current_defaults()
v = ss.form_version
k = lambda name: f"{name}_{v}"  # noqa: E731 - versioned widget keys

with st.form("preferences"):
    # --- Interests -------------------------------------------------------
    st.subheader("Interests")
    interests = st.pills(
        "What are you into?",
        options=list(Interest),
        selection_mode="multi",
        default=[Interest(i) for i in d["interests"]],
        format_func=label,
        key=k("interests"),
    )
    custom = st.text_input(
        "Anything else? (comma-separated)",
        value=", ".join(d["custom_interests"]),
        placeholder="e.g. birdwatching, board games",
        key=k("custom"),
    )

    # --- Time ------------------------------------------------------------
    st.subheader("Available time")
    duration = st.slider(
        "How much time do you have?",
        min_value=15, max_value=720, step=15,
        value=d["availability"]["duration_minutes"],
        format="%d min",
        key=k("duration"),
    )
    preferred_times = st.pills(
        "Preferred time of day",
        options=list(TimeOfDay),
        selection_mode="multi",
        default=[TimeOfDay(t) for t in d["availability"]["preferred_times"]],
        format_func=label,
        key=k("times"),
    )

    # --- Difficulty & energy ---------------------------------------------
    st.subheader("Difficulty & energy")
    difficulty = st.radio(
        "Difficulty level",
        options=list(Difficulty),
        index=list(Difficulty).index(Difficulty(d["difficulty"])),
        format_func=lambda x: f"{label(x)} — {DIFFICULTY_HELP[x]}",
        key=k("difficulty"),
    )
    energy = st.select_slider(
        "Energy level right now",
        options=list(ENERGY_LABELS),
        value=d["energy_level"],
        format_func=ENERGY_LABELS.get,
        key=k("energy"),
    )

    # --- Accessibility ---------------------------------------------------
    st.subheader("Accessibility needs")
    access_needs = st.multiselect(
        "Select any that apply",
        options=list(AccessibilityNeed),
        default=[AccessibilityNeed(n) for n in d["accessibility"]["needs"]],
        format_func=label,
        placeholder="None",
        key=k("access"),
    )
    access_notes = st.text_area(
        "Anything else we should know?",
        value=d["accessibility"]["notes"],
        max_chars=500,
        placeholder="e.g. can't stand for more than 30 minutes",
        key=k("access_notes"),
    )

    # --- Environment -----------------------------------------------------
    st.subheader("Environment")
    env = d["environment"]
    c1, c2 = st.columns(2)
    with c1:
        setting = st.segmented_control(
            "Indoor or outdoor?",
            options=list(Setting),
            default=Setting(env["setting"]),
            format_func=label,
            key=k("setting"),
        )
        crowd = st.select_slider(
            "Crowd tolerance",
            options=list(CrowdLevel),
            value=CrowdLevel(env["crowd_tolerance"]),
            format_func=label,
            key=k("crowd"),
        )
    with c2:
        group = st.selectbox(
            "Who's coming?",
            options=list(GroupSize),
            index=list(GroupSize).index(GroupSize(env["group_size"])),
            format_func=label,
            key=k("group"),
        )
        travel = st.number_input(
            "Max travel distance (km)",
            min_value=0, max_value=500, step=1,
            value=env["max_travel_km"],
            key=k("travel"),
        )
    surroundings = st.pills(
        "Preferred surroundings",
        options=list(Surroundings),
        selection_mode="multi",
        default=[Surroundings(s) for s in env["surroundings"]],
        format_func=label,
        key=k("surroundings"),
    )

    # --- Weather ---------------------------------------------------------
    st.subheader("Weather constraints")
    w = d["weather"]
    avoid = st.pills(
        "Avoid activities in…",
        options=list(WeatherCondition),
        selection_mode="multi",
        default=[WeatherCondition(c) for c in w["avoid"]],
        format_func=label,
        key=k("avoid"),
    )
    temp_range = st.slider(
        "Comfortable temperature range (°C)",
        min_value=-40, max_value=50,
        value=(w["min_temp_c"], w["max_temp_c"]),
        key=k("temp"),
    )

    submitted = st.form_submit_button(
        "Save preferences", type="primary", use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

if submitted:
    if not valid_id:
        st.error("Enter a valid User ID in the sidebar before saving.")
        st.stop()

    try:
        prefs = PreferencesIn(
            interests=interests or [],
            custom_interests=[c for c in custom.split(",") if c.strip()],
            availability={"duration_minutes": duration, "preferred_times": preferred_times or []},
            difficulty=difficulty,
            energy_level=energy,
            accessibility={"needs": access_needs, "notes": access_notes.strip()},
            environment={
                "setting": setting or Setting.EITHER,
                "surroundings": surroundings or [],
                "crowd_tolerance": crowd,
                "group_size": group,
                "max_travel_km": int(travel),
            },
            weather={"avoid": avoid or [], "min_temp_c": temp_range[0], "max_temp_c": temp_range[1]},
        )
    except ValidationError as e:
        for err in e.errors():
            st.error(err["msg"].removeprefix("Value error, "))
        st.stop()

    try:
        saved = api_client.save_preferences(user_id, prefs)
    except BackendError as e:
        st.error(f"Couldn't save: {e}")
        st.stop()

    ss.prefs = saved
    ss.last_saved = saved["updated_at"]
    st.success(f"Preferences saved for **{user_id}**.", icon="💾")
    with st.expander("What was sent to the backend"):
        st.json(saved)
