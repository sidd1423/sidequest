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
from .schemas import MIN_QUEST_MINUTES, FeedbackEntry, PastQuest, PreferencesIn, Quest, QuestExample

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
  "weather_backup": "a quick OUTDOOR alternative if the weather turns (e.g. under a covered spot)",
  "why_it_fits": "one sentence on why this matches the user"
}"""


def _profile_block(profile: PreferencesIn) -> str:
    p = profile.model_dump(mode="json")
    return json.dumps(p, indent=2)


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
) -> str:
    minutes = profile.availability.duration_minutes
    parts = [
        "You are Sidequest. You design ONE small, real-world adventure (a 'sidequest') that gets this "
        "person outside right now. Sidequests are quick, outdoor, start-immediately tasks - the point is "
        "to get people out of the house more often in a fun, low-friction way.",
        "",
        "## User profile",
        _profile_block(profile),
        "",
        "## Hard constraints - the quest MUST respect all of these",
        "- Happens OUTSIDE (streets, parks, yards, waterfronts, trails, plazas) - never indoors.",
        "- Can start RIGHT NOW from wherever the user is: no booking, tickets, opening hours, special "
        "gear or planning ahead.",
        f"- Takes between {MIN_QUEST_MINUTES} and {minutes} minutes in total, including getting there "
        "and back.",
        f"- Stays within {profile.environment.max_travel_km:g} km of where they are now (walking or "
        "rolling distance).",
        f"- Difficulty around '{profile.difficulty.value}' and energy demand about {profile.energy_level}/5.",
        "- Fully compatible with every listed accessibility need.",
        f"- Comfortable between {profile.weather.min_temp_c} and {profile.weather.max_temp_c} °C; include a "
        "quick outdoor plan B for the weather conditions the user wants to avoid.",
        "- Free or nearly free. Concrete, specific actions - not vague advice.",
        "- Suit their surroundings, crowd tolerance and group size.",
    ]

    if retrieved_examples:
        parts += [
            "",
            "## Example quests matched to this user (use them as inspiration for tone, scale and "
            "specificity - create something NEW, do not copy them)",
            _examples_block(retrieved_examples),
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

    if not recent_quests and not feedback_history:
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


def _violations(quest: Quest, profile: PreferencesIn, recent: Sequence[PastQuest] = ()) -> list[str]:
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
    return problems


def generate_quest(
    profile: PreferencesIn,
    retrieved_examples: Sequence[QuestExample] | None = None,
    feedback_history: Sequence[FeedbackEntry] | None = None,
    *,
    recent_quests: Sequence[PastQuest] | None = None,
    llm: LLMClient | None = None,
) -> Quest:
    """Generate one sidequest tailored to `profile`.

    Everything after `profile` is optional - a brand-new user has no history:
      retrieved_examples  similar quests from the quest library
      feedback_history    feedback on past quests (used if recent_quests isn't given)
      recent_quests       the user's last 10 quests from the user history database;
                          the new quest must not repeat them or resemble disliked ones
    """
    llm = llm or GemmaClient()
    recent_quests = list(recent_quests or [])
    prompt = build_prompt(profile, retrieved_examples, feedback_history, recent_quests)

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
        problems = _violations(quest, profile, recent_quests)
        if problems:
            last_error = "; ".join(problems)
            continue
        return quest

    raise LLMError(
        f"Model didn't return a valid quest after {attempts} attempt(s) ({last_error}). "
        "The backend terminal shows what the model sent."
    )
