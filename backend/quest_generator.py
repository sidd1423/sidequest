"""Turn a user's preferences (plus optional history) into a quick outdoor sidequest using Gemma.

A sidequest is a 5-30 minute thing to do outside, starting right now from
wherever the user is - small nudges to get people outdoors more often.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Sequence

from pydantic import ValidationError

from .llm import GemmaClient, LLMClient, LLMError, LLMTimeout
from .schemas import MIN_QUEST_MINUTES, FeedbackEntry, PastQuest, PreferencesIn, Quest, QuestContext, QuestExample
from .taste import Taste, conflicts_with_taste, taste_block

MAX_ATTEMPTS = 3
MAX_TIMEOUT_RETRIES = 1     # a timeout is usually a busy server - retry once
DEFAULT_TIME_BUDGET = 300   # seconds for the whole generation, all attempts included

log = logging.getLogger("sidequest.quests")

QUEST_JSON_SHAPE = """{
  "title": "short, catchy quest name",
  "summary": "2-3 sentences describing the quest",
  "steps": ["step 1", "step 2", "..."],
  "estimated_minutes": 15,
  "difficulty": "easy | moderate | challenging | extreme",
  "energy_required": 3,
  "tags": ["nature", "photography"],
  "accessibility_notes": "how this quest accommodates the user's needs (or empty)",
  "weather_backup": "a quick OUTDOOR alternative if the weather turns (e.g. under a covered spot)"
}"""


def _profile_block(profile: PreferencesIn) -> str:
    p = profile.model_dump(mode="json")
    return json.dumps(p, indent=2)


def _minutes_until(now: str | None, later: str | None) -> int | None:
    try:
        h1, m1 = map(int, now.split(":"))  # type: ignore[union-attr]
        h2, m2 = map(int, later.split(":"))  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        return None
    return (h2 * 60 + m2) - (h1 * 60 + m1)


def _context_block(ctx: QuestContext, max_travel_km: float) -> str:
    """Where the user is right now: place, time of day, weather, real places nearby."""
    lines = []
    if ctx.place:
        lines.append(f"- Place: {ctx.place}")
    w = ctx.weather
    if w is not None:
        if w.local_time:
            light = ""
            if w.is_day is False:
                light = " - it's DARK out"
            else:
                left = _minutes_until(w.local_time, w.sunset)
                if left is not None and 0 <= left <= 90:
                    light = f" - sunset at {w.sunset}, only about {left} min of daylight left"
                elif w.sunset:
                    light = f" (daylight; sunset {w.sunset})"
            lines.append(f"- Local time: {w.local_time}{light}")
        weather = f"{w.temp_c:.0f}°C"
        if w.feels_like_c is not None and abs(w.feels_like_c - w.temp_c) >= 2:
            weather += f" (feels like {w.feels_like_c:.0f}°C)"
        if w.condition:
            weather += f", {w.condition}"
        if w.wind_kmh is not None:
            weather += f", wind {w.wind_kmh:.0f} km/h"
            if w.gusts_kmh is not None and w.gusts_kmh >= w.wind_kmh + 15:
                weather += f" (gusts {w.gusts_kmh:.0f})"
        if w.uv_index is not None and w.is_day is not False:
            weather += f", UV {w.uv_index:.0f}"
        lines.append(f"- Weather now: {weather}")
        if w.rain_chance_pct is not None:
            lines.append(f"- Chance of rain/snow in the next 2 hours: {w.rain_chance_pct}%")
        if w.air_quality_index is not None:
            lines.append(f"- Air quality: US AQI {w.air_quality_index}")
    if ctx.nearby:
        lines.append(f"- Real places within about {max_travel_km:g} km (straight-line distance, closest first):")
        for p in ctx.nearby:
            where = f"{p.distance_m} m" + (f" {p.direction}" if p.direction else "")
            lines.append(f"  - {p.name} ({p.kind}, {where})")
    return "\n".join(lines)


def weather_rules(ctx: QuestContext | None) -> list[str]:
    """Extra hard constraints for the conditions right now."""
    w = ctx.weather if ctx else None
    if w is None:
        return ["- We don't know the weather where they are: include a quick outdoor plan B in case it's bad."]
    rules = [
        "- Fits the weather RIGHT NOW (see 'Right now, where they are'). Design for the actual conditions - e.g. "
        "puddle reflections or a covered route in rain, shade and water in heat, brisk short loops in cold - "
        "instead of ignoring them. weather_backup = what to do if it changes during the quest.",
    ]
    code = w.weather_code or 0
    feels = w.feels_like_c if w.feels_like_c is not None else w.temp_c
    if code >= 95:
        rules.append("- THUNDERSTORM: stay close to shelter and buildings; no open fields, hilltops, water or "
                     "standing under trees. Keep it short.")
    if code in (56, 57, 66, 67) or (feels <= 0 and code in (51, 53, 55, 61, 63, 65, 80, 81, 82)):
        rules.append("- Icy/freezing conditions: cleared, flat surfaces only - no slopes, trails or stairs.")
    if feels <= -15:
        rules.append(f"- Feels like {feels:.0f}°C: dangerously cold - keep time outside short and moving, "
                     "close to warm places.")
    elif feels <= 0:
        rules.append("- It's below freezing: keep them moving; nothing that means sitting still for long.")
    if feels >= 32:
        rules.append(f"- Feels like {feels:.0f}°C: very hot - shade, low exertion, near drinking water.")
    if (w.wind_kmh or 0) >= 40 or (w.gusts_kmh or 0) >= 60:
        rules.append("- Very windy: avoid tall trees, open water edges and anything that can blow away.")
    if w.uv_index is not None and w.uv_index >= 8 and w.is_day is not False:
        rules.append("- Very high UV: favour shade.")
    if w.air_quality_index is not None and w.air_quality_index > 150:
        rules.append(f"- Unhealthy air (AQI {w.air_quality_index}): low exertion only - no running or hard climbs.")
    if w.is_day is False:
        rules.append("- It's dark: well-lit, populated streets and paths only - no unlit parks, trails or "
                     "water edges. Night-friendly ideas (lights, stars, reflections, sounds) are great.")
    else:
        left = _minutes_until(w.local_time, w.sunset)
        if left is not None and 0 <= left <= 45:
            rules.append("- The sun sets very soon: plan for fading light and finish on lit streets.")
    return rules


def _examples_block(examples: Sequence[QuestExample]) -> str:
    lines = []
    for q in examples:
        meta = f"{q.category}, {q.duration_minutes} min, {q.difficulty.value}"
        if q.tags:
            meta += f"; tags: {', '.join(q.tags)}"
        lines.append(f"- {q.quest_text} ({meta})")
    return "\n".join(lines)


def _feedback_block(feedback: Sequence[FeedbackEntry]) -> str:
    lines = []
    for f in feedback:
        if f.completed:
            status = f"completed, rated {f.rating}/5"
        else:
            status = "didn't finish" + (f", rated {f.rating}/5" if f.rating else "")
        comment = f' - "{f.comment}"' if f.comment else ""
        lines.append(f"- {f.quest_title} [{status}]{comment}")
    return "\n".join(lines)


def _recent_block(recent: Sequence[PastQuest]) -> str:
    """The user's recent sidequests grouped by how they went."""
    def line(q: PastQuest) -> str:
        bits = [f"{q.category}", f"{q.duration_minutes} min"]
        if q.tags:
            bits.append("tags: " + ", ".join(q.tags))
        extra = []
        if q.status.value == "skipped":
            extra.append("didn't finish")
        if q.rating:
            extra.append(f"rated {q.rating}/5")
        if q.time_logged_minutes:
            extra.append(f"took {q.time_logged_minutes} min")
        if q.comment:
            extra.append(f'said: "{q.comment}"')
        tail = f" - {'; '.join(extra)}" if extra else ""
        return f"- {q.title} ({'; '.join(bits)}){tail}"

    groups = [
        ("Loved (rated 4-5) - lean toward this kind of thing, but make something NEW",
         [q for q in recent if q.loved]),
        ("DISLIKED (rated 1-2) - make the new quest clearly DIFFERENT from these: a different kind of "
         "activity, not just a new name", [q for q in recent if q.disliked]),
        ("Rated OK (3)", [q for q in recent if q.rating == 3]),
        ("Didn't finish, no rating - probably not appealing; try a different angle",
         [q for q in recent if q.status.value == "skipped" and q.rating is None]),
        ("Suggested but not done yet - do not repeat", [q for q in recent if q.status.value == "suggested"]),
    ]
    out = []
    for heading, items in groups:
        if items:
            out.append(f"{heading}:")
            out.extend(line(q) for q in items)
    return "\n".join(out)


def build_prompt(
    profile: PreferencesIn,
    retrieved_examples: Sequence[QuestExample] | None = None,
    feedback_history: Sequence[FeedbackEntry] | None = None,
    recent_quests: Sequence[PastQuest] | None = None,
    taste: Taste | None = None,
    party_size: int | None = None,
    context: QuestContext | None = None,
) -> str:
    minutes = profile.availability.duration_minutes
    travel_km = profile.environment.max_travel_km
    has_context = context is not None and not context.is_empty
    parts = [
        "You are Sidequest. You design ONE small, real-world adventure (a 'sidequest') that gets this "
        "person outside right now. Sidequests are quick, outdoor, start-immediately tasks - the point is "
        "to get people out of the house more often in a fun, low-friction way.",
        "",
        "## User profile",
        _profile_block(profile),
        "",
    ]
    if has_context:
        parts += ["## Right now, where they are (live)", _context_block(context, travel_km), ""]  # type: ignore[arg-type]
    parts += [
        "## Hard constraints - the quest MUST respect all of these",
        "- Happens OUTSIDE (streets, parks, yards, waterfronts, trails, plazas) - never indoors.",
        "- Can start RIGHT NOW from wherever the user is: no booking, tickets, opening hours, special "
        "gear or planning ahead.",
        f"- Takes between {MIN_QUEST_MINUTES} and {minutes} minutes in total, including getting there "
        "and back.",
        f"- Works for this group right now: {profile.environment.group_size.value.replace('_', ' ')}.",
        f"- Stays within {profile.environment.max_travel_km:g} km of where they are now (walking or "
        "rolling distance).",
        f"- Difficulty around '{profile.difficulty.value}' and energy demand about {profile.energy_level}/5.",
        "- Fully compatible with every listed accessibility need.",
        *weather_rules(context),
        "- Free or nearly free. Concrete, specific actions - not vague advice.",
        "- Suit their crowd tolerance and group size.",
    ]
    if context is not None and context.nearby:
        parts += [
            "- Where it fits, build the quest around one or two of the REAL places listed above and name them "
            "exactly (with the direction to head). Only use places from that list - never invent place names, "
            "streets or addresses.",
        ]
    elif context is not None and context.place:
        parts += [f"- Fit it to {context.place}, but don't invent specific place names or addresses."]
    else:
        parts += ["- We don't know where they are: don't name specific places - describe kinds of spots "
                  "('the nearest park', 'a quiet side street')."]
    if party_size and party_size >= 2:
        parts += [
            f"- GROUP QUEST: exactly {party_size} friends will do this quest TOGETHER, at the same time and "
            f"place. Design it for {party_size} people - everyone takes part (shared goal, turns, or "
            "complementary roles), and the steps say how the group works together.",
        ]

    if retrieved_examples:
        parts += [
            "",
            "## Example quests matched to this user (use them as inspiration for tone, scale and "
            "specificity - create something NEW, do not copy them)",
            _examples_block(retrieved_examples),
        ]

    if taste is not None and not taste.is_empty:
        parts += [
            "",
            "## What their feedback shows overall (learned from every quest they've rated - follow it)",
            taste_block(taste),
        ]

    if recent_quests:
        parts += [
            "",
            f"## This user's last {len(recent_quests)} sidequests (newest first) - never repeat any of them",
            _recent_block(recent_quests),
        ]
    elif feedback_history:
        parts += [
            "",
            "## Feedback on previous quests (lean toward what they liked, away from what they skipped or rated low)",
            _feedback_block(feedback_history),
        ]

    if not recent_quests and not feedback_history and (taste is None or taste.is_empty):
        parts += ["", "This is the user's first quest - pick something easy to say yes to that clearly matches "
                  "their interests."]

    parts += [
        "",
        "## Output",
        "Respond with ONLY a single JSON object (no markdown, no commentary) with exactly this shape:",
        QUEST_JSON_SHAPE,
    ]
    return "\n".join(parts)


_THINKING = re.compile(r"<(think|thinking|thought)>.*?</\1>", re.DOTALL | re.IGNORECASE)
_DECODER = json.JSONDecoder()


def _json_objects(text: str) -> list[Any]:
    """Every top-level JSON object embedded anywhere in `text`."""
    found, i = [], text.find("{")
    while i != -1:
        try:
            obj, end = _DECODER.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        i = text.find("{", end)
    return found


def parse_quest(raw: str) -> Quest:
    """Extract and validate the quest JSON from a model response.

    Tolerates markdown fences, chatty preambles, and visible reasoning blocks;
    if several JSON objects appear, the last valid one wins (the final answer).
    """
    text = _THINKING.sub("", raw)
    candidates = _json_objects(text)
    if not candidates:
        raise ValueError("No JSON object found in model response")
    last_error: Exception | None = None
    for obj in reversed(candidates):
        if "quest" in obj and isinstance(obj["quest"], dict):  # {"quest": {...}} wrapper
            obj = obj["quest"]
        try:
            return Quest.model_validate(obj)
        except ValidationError as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def too_similar_to_disliked(quest: Quest, disliked: PastQuest) -> bool:
    """Same kind of activity as a quest the user disliked: same category and
    at least two shared tags, or the same title."""
    if _norm_title(quest.title) == _norm_title(disliked.title):
        return True
    tags = set(quest.tags)
    category = next((t for t in quest.tags if t == disliked.category), None)
    return category is not None and len(tags & set(disliked.tags)) >= 2


def _violations(
    quest: Quest, profile: PreferencesIn, recent: Sequence[PastQuest] = (), taste: Taste | None = None
) -> list[str]:
    problems = []
    available = profile.availability.duration_minutes
    if quest.estimated_minutes > available:
        problems.append(f"estimated_minutes ({quest.estimated_minutes}) exceeds the user's {available} available minutes")
    if quest.estimated_minutes < MIN_QUEST_MINUTES:
        problems.append(f"estimated_minutes must be at least {MIN_QUEST_MINUTES}")
    if quest.setting.value == "indoor":
        problems.append("the quest must take place outdoors")
    for past in recent:
        if _norm_title(quest.title) == _norm_title(past.title):
            problems.append(f"'{quest.title}' repeats one of the user's recent quests - create a new one")
            break
    for past in recent:
        if past.disliked and too_similar_to_disliked(quest, past):
            problems.append(
                f"too similar to '{past.title}', which the user rated {past.rating}/5 - "
                "pick a clearly different kind of activity"
            )
            break
    disliked = conflicts_with_taste(quest, taste)
    if disliked:
        problems.append(
            f"built around {', '.join(disliked)}, which this user consistently rates low or abandons - "
            "pick a different kind of activity"
        )
    return problems


def generate_quest(
    profile: PreferencesIn,
    retrieved_examples: Sequence[QuestExample] | None = None,
    feedback_history: Sequence[FeedbackEntry] | None = None,
    *,
    recent_quests: Sequence[PastQuest] | None = None,
    taste: Taste | None = None,
    llm: LLMClient | None = None,
    party_size: int | None = None,
    context: QuestContext | None = None,
) -> Quest:
    """Generate one sidequest tailored to `profile`.

    Everything after `profile` is optional - a brand-new user has no history:
      retrieved_examples  similar quests from the quest library
      feedback_history    feedback on past quests (used if recent_quests isn't given)
      recent_quests       the user's last 10 quests from the user history database;
                          the new quest must not repeat them or resemble disliked ones
      taste               patterns learned from ALL the user's feedback (taste.learn_taste)
      party_size          a group quest for this many friends together (parties.py)
      context             weather + place + real nearby spots right now (local_context.lookup)
    """
    llm = llm or GemmaClient()
    recent_quests = list(recent_quests or [])
    prompt = build_prompt(profile, retrieved_examples, feedback_history, recent_quests, taste, party_size, context)

    budget = float(os.getenv("GEMMA_TIME_BUDGET") or DEFAULT_TIME_BUDGET)
    started = time.monotonic()
    last_error = ""
    timeouts = 0
    attempts = 0
    while attempts < MAX_ATTEMPTS:
        if attempts and time.monotonic() - started > budget:
            log.warning("Stopping after %.0fs (GEMMA_TIME_BUDGET=%.0f)", time.monotonic() - started, budget)
            break
        attempt_prompt = prompt
        if last_error:
            attempt_prompt += (
                f"\n\nYour previous answer was rejected: {last_error}. "
                "Return a corrected JSON object only."
            )
        try:
            raw = llm.complete(attempt_prompt)
        except LLMTimeout:
            timeouts += 1
            if timeouts > MAX_TIMEOUT_RETRIES or time.monotonic() - started > budget:
                raise
            log.warning("Inference API timed out - retrying once")
            continue  # a timeout doesn't use up one of the answer attempts
        attempts += 1
        try:
            quest = parse_quest(raw)
        except (ValueError, ValidationError) as exc:
            last_error = str(exc).splitlines()[0][:300]
            log.warning("Unusable model output (%s). Start of output: %r", last_error, raw[:500])
            continue
        problems = _violations(quest, profile, recent_quests, taste)
        if problems:
            last_error = "; ".join(problems)
            continue
        return quest

    raise LLMError(
        f"Model didn't return a valid quest after {attempts} attempt(s) ({last_error}). "
        "The backend terminal shows what the model sent."
    )
