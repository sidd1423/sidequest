"""Turn a user's preferences (plus optional history) into a sidequest using Gemma."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Sequence

from pydantic import ValidationError

from .llm import GemmaClient, LLMClient, LLMError
from .schemas import FeedbackEntry, PreferencesIn, Quest, QuestExample

MAX_ATTEMPTS = 3

log = logging.getLogger("sidequest.quests")

QUEST_JSON_SHAPE = """{
  "title": "short, catchy quest name",
  "summary": "2-3 sentences describing the quest",
  "steps": ["step 1", "step 2", "..."],
  "estimated_minutes": 90,
  "difficulty": "easy | moderate | challenging | extreme",
  "energy_required": 3,
  "setting": "indoor | outdoor | either",
  "tags": ["nature", "photography"],
  "accessibility_notes": "how this quest accommodates the user's needs (or empty)",
  "weather_backup": "what to do instead if the weather turns bad",
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
            status = "skipped / not completed"
        comment = f' - "{f.comment}"' if f.comment else ""
        lines.append(f"- {f.quest_title} [{status}]{comment}")
    return "\n".join(lines)


def build_prompt(
    profile: PreferencesIn,
    retrieved_examples: Sequence[QuestExample] | None = None,
    feedback_history: Sequence[FeedbackEntry] | None = None,
) -> str:
    parts = [
        "You are Sidequest, an assistant that designs one small, real-world adventure "
        "(a 'sidequest') tailored to a specific person.",
        "",
        "## User profile",
        _profile_block(profile),
        "",
        "## Hard constraints - the quest MUST respect all of these",
        f"- Takes at most {profile.availability.duration_minutes} minutes in total, including travel.",
        f"- Travel no more than {profile.environment.max_travel_km} km.",
        f"- Difficulty around '{profile.difficulty.value}' and energy demand about {profile.energy_level}/5.",
        "- Fully compatible with every listed accessibility need.",
        f"- Works between {profile.weather.min_temp_c} and {profile.weather.max_temp_c} °C, "
        "and include a weather backup plan for the conditions the user wants to avoid.",
        "- Specific and doable today: concrete actions, not vague advice. No purchases over a small amount.",
    ]

    if retrieved_examples:
        parts += [
            "",
            "## Example quests matched to this user (use them as inspiration for tone, scale and "
            "specificity - create something NEW, do not copy them)",
            _examples_block(retrieved_examples),
        ]

    if feedback_history:
        parts += [
            "",
            "## Feedback on previous quests (lean toward what they liked, away from what they skipped or rated low)",
            _feedback_block(feedback_history),
        ]

    if not feedback_history:
        parts += ["", "This is the user's first quest - pick something welcoming that clearly matches their interests."]

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


def _violations(quest: Quest, profile: PreferencesIn) -> list[str]:
    problems = []
    if quest.estimated_minutes > profile.availability.duration_minutes:
        problems.append(
            f"estimated_minutes ({quest.estimated_minutes}) exceeds the user's "
            f"{profile.availability.duration_minutes} available minutes"
        )
    if profile.environment.setting.value != "either" and quest.setting.value not in (
        profile.environment.setting.value,
        "either",
    ):
        problems.append(f"setting must be '{profile.environment.setting.value}'")
    return problems


def generate_quest(
    profile: PreferencesIn,
    retrieved_examples: Sequence[QuestExample] | None = None,
    feedback_history: Sequence[FeedbackEntry] | None = None,
    *,
    llm: LLMClient | None = None,
) -> Quest:
    """Generate one sidequest tailored to `profile`.

    `retrieved_examples` and `feedback_history` come from quests the user has
    completed, so both are optional (and empty) on a user's first run.
    """
    llm = llm or GemmaClient()
    prompt = build_prompt(profile, retrieved_examples, feedback_history)

    last_error = ""
    for _ in range(MAX_ATTEMPTS):
        attempt_prompt = prompt
        if last_error:
            attempt_prompt += (
                f"\n\nYour previous answer was rejected: {last_error}. "
                "Return a corrected JSON object only."
            )
        raw = llm.complete(attempt_prompt)
        try:
            quest = parse_quest(raw)
        except (ValueError, ValidationError) as exc:
            last_error = str(exc).splitlines()[0][:300]
            log.warning("Unusable model output (%s). Start of output: %r", last_error, raw[:500])
            continue
        problems = _violations(quest, profile)
        if problems:
            last_error = "; ".join(problems)
            continue
        return quest

    raise LLMError(
        f"Model didn't return a valid quest after {MAX_ATTEMPTS} attempts ({last_error}). "
        "The backend terminal shows what the model sent."
    )
