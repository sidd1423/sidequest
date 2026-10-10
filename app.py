"""Sidequest - quick outdoor quests to get you outside (Streamlit frontend).

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
    MAX_QUEST_MINUTES,
    MAX_TRAVEL_KM,
    MIN_QUEST_MINUTES,
    USER_ID_PATTERN,
    AccessibilityNeed,
    CrowdLevel,
    Difficulty,
    GroupSize,
    Interest,
    PreferencesIn,
    Surroundings,
    WeatherCondition,
)
from frontend import api_client
from frontend.api_client import BackendError

load_dotenv()

st.set_page_config(page_title="Sidequest · Preferences", page_icon="🧭", layout="centered")

ENERGY_LABELS = {1: "Very low", 2: "Low", 3: "Medium", 4: "High", 5: "Very high"}
DIFFICULTY_HELP = {
    Difficulty.EASY: "Relaxed, no prep needed",
    Difficulty.MODERATE: "A bit of effort",
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
        "availability": {"duration_minutes": 15},
        "accessibility": {"needs": [], "notes": ""},
        "environment": {
            "surroundings": [], "crowd_tolerance": "moderate",
            "group_size": "solo", "max_travel_km": 1.0,
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
st.write(
    "Quick 5-30 minute quests to do **outside, right now** - small nudges to get you out of the house. "
    "Tell us what you're into and how much time you've got."
)

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
    st.subheader("Time right now")
    duration = st.slider(
        "How many minutes can you spend outside?",
        min_value=MIN_QUEST_MINUTES, max_value=MAX_QUEST_MINUTES, step=5,
        value=d["availability"]["duration_minutes"],
        format="%d min",
        key=k("duration"),
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
        placeholder="e.g. need a bench every few minutes",
        key=k("access_notes"),
    )

    # --- Surroundings ----------------------------------------------------
    st.subheader("Where you are")
    env = d["environment"]
    surroundings = st.pills(
        "What's around you?",
        options=list(Surroundings),
        selection_mode="multi",
        default=[Surroundings(s) for s in env["surroundings"]],
        format_func=label,
        key=k("surroundings"),
    )
    travel = st.slider(
        "How far are you happy to go from where you are? (km)",
        min_value=0.0, max_value=MAX_TRAVEL_KM, step=0.5,
        value=float(env["max_travel_km"]),
        format="%.1f km",
        key=k("travel"),
    )
    c1, c2 = st.columns(2)
    with c1:
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

def save_form() -> None:
    if not valid_id:
        st.error("Enter a valid User ID in the sidebar before saving.")
        return
    try:
        prefs = PreferencesIn(
            interests=interests or [],
            custom_interests=[c for c in custom.split(",") if c.strip()],
            availability={"duration_minutes": duration},
            difficulty=difficulty,
            energy_level=energy,
            accessibility={"needs": access_needs, "notes": access_notes.strip()},
            environment={
                "surroundings": surroundings or [],
                "crowd_tolerance": crowd,
                "group_size": group,
                "max_travel_km": float(travel),
            },
            weather={"avoid": avoid or [], "min_temp_c": temp_range[0], "max_temp_c": temp_range[1]},
        )
    except ValidationError as e:
        for err in e.errors():
            st.error(err["msg"].removeprefix("Value error, "))
        return
    try:
        saved = api_client.save_preferences(user_id, prefs)
    except BackendError as e:
        st.error(f"Couldn't save: {e}")
        return

    ss.prefs = saved
    ss.last_saved = saved["updated_at"]
    st.success(f"Preferences saved for **{user_id}**.", icon="💾")
    with st.expander("What was sent to the backend"):
        st.json(saved)


if submitted:
    save_form()


# ---------------------------------------------------------------------------
# Sidequest generation
# ---------------------------------------------------------------------------

STARS = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}


def render_quest(record: dict) -> None:
    q = record["quest"]
    with st.container(border=True):
        st.subheader(q["title"])
        st.write(q["summary"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Time", f"{q['estimated_minutes']} min")
        c2.metric("Difficulty", label(q["difficulty"]))
        c3.metric("Energy", ENERGY_LABELS[q["energy_required"]])

        st.markdown("**Steps**")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(q["steps"], 1)))

        if q.get("accessibility_notes"):
            st.markdown(f"♿ **Accessibility:** {q['accessibility_notes']}")
        if q.get("weather_backup"):
            st.markdown(f"🌦️ **If the weather turns:** {q['weather_backup']}")
        if q.get("why_it_fits"):
            st.caption(f"Why this fits you: {q['why_it_fits']}")
        if q.get("tags"):
            st.caption(" · ".join(f"#{t}" for t in q["tags"]))


def feedback_form(record: dict) -> None:
    with st.form(f"feedback_{record['id']}"):
        st.markdown("**How did it go?**")
        outcome = st.radio(
            "Did you do this quest?",
            ["Completed it", "Skipped it"],
            horizontal=True,
            key=f"outcome_{record['id']}",
        )
        rating = st.select_slider(
            "Rating (only used if completed)",
            options=list(STARS),
            value=4,
            format_func=STARS.get,
            key=f"rating_{record['id']}",
        )
        time_spent = st.number_input(
            "Time spent (minutes, if completed)",
            min_value=0, max_value=1440, step=5,
            value=int(record["quest"]["estimated_minutes"]),
            key=f"time_{record['id']}",
        )
        comment = st.text_input(
            "Comment (optional)",
            placeholder="What did you like or dislike?",
            key=f"comment_{record['id']}",
        )
        if st.form_submit_button("Send feedback", use_container_width=True):
            completed = outcome == "Completed it"
            try:
                api_client.send_feedback(
                    user_id, record["id"], completed, rating if completed else None, comment.strip(),
                    int(time_spent) if completed else 0,
                )
            except BackendError as e:
                st.error(f"Couldn't send feedback: {e}")
            else:
                st.toast("Thanks! Your next quest will take this into account.", icon="🙏")
                st.rerun()


st.divider()
st.header("🗺️ Your sidequest")

if not (healthy and valid_id):
    st.info("Enter your User ID in the sidebar (and save your preferences) to generate a sidequest.")
else:
    try:
        quests = api_client.list_quests(user_id)
    except BackendError as e:
        st.error(str(e))
        quests = []

    st.caption("Uses your **saved** preferences - save the form first if you changed anything.")
    if st.button("✨ Generate sidequest", type="primary", use_container_width=True):
        with st.spinner("Asking Gemma for a sidequest…"):
            try:
                quests.insert(0, api_client.generate_quest(user_id))
            except BackendError as e:
                st.error(f"Couldn't generate a quest: {e}")
            else:
                st.toast("New sidequest ready", icon="✨")

    if quests:
        latest = quests[0]
        render_quest(latest)
        if latest["status"] == "suggested":
            feedback_form(latest)
        else:
            fb = latest.get("feedback") or {}
            done = "✅ Completed" + (f" · {STARS[fb['rating']]}" if fb.get("rating") else "")
            if fb.get("time_logged_minutes"):
                done += f" · {fb['time_logged_minutes']} min logged"
            st.caption(done if latest["status"] == "completed" else "⏭️ Skipped")

        if len(quests) > 1:
            with st.expander(f"Quest history ({len(quests) - 1} earlier)"):
                for rec in quests[1:]:
                    fb = rec.get("feedback") or {}
                    status_txt = {
                        "completed": f"✅ {STARS.get(fb.get('rating'), '')}"
                        + (f" · {fb['time_logged_minutes']} min" if fb.get("time_logged_minutes") else ""),
                        "skipped": "⏭️ skipped",
                        "suggested": "🕒 no feedback yet",
                    }[rec["status"]]
                    st.markdown(f"**{rec['quest']['title']}** - {status_txt}")
                    if fb.get("comment"):
                        st.caption(f"\u201c{fb['comment']}\u201d")
    else:
        st.write("No quests yet - hit **Generate sidequest** to get your first one.")
