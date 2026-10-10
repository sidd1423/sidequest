"""The feedback loop: learn what a user likes from ALL their rated quests.

The user-history database gives Gemma the last 10 quests one by one. This
module looks at everything the user has ever rated and boils it down to
patterns that steer every new quest:

- tags they consistently rate high / low (or never finish)
- difficulty levels that work or don't
- whether they tend to take longer or shorter than the estimate
- how often they finish quests at all
- their most recent comments

The result (`Taste`) is used three ways:
1. a "What their feedback shows" block in the Gemma prompt (`taste_block`),
2. re-ranking example quests so disliked kinds of quests aren't offered to
   Gemma as inspiration (`rerank_examples`),
3. rejecting a generated quest that's built around tags they dislike
   (`conflicts_with_taste`, checked in quest_generator._violations).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

from pydantic import BaseModel, Field

from .schemas import FeedbackIn, Quest, QuestExample

UNRATED_SKIP_SCORE = 2.0   # didn't finish and didn't rate: treat as a mild dislike
LIKE_THRESHOLD = 4.0
DISLIKE_THRESHOLD = 2.0
MAX_TAGS = 6
MAX_COMMENTS = 4


class Taste(BaseModel):
    rated: int = 0
    completed: int = 0
    not_finished: int = 0
    liked_tags: list[str] = Field(default_factory=list)
    disliked_tags: list[str] = Field(default_factory=list)
    liked_difficulty: list[str] = Field(default_factory=list)
    disliked_difficulty: list[str] = Field(default_factory=list)
    time_ratio: float | None = None  # actual / estimated minutes on completed quests
    recent_comments: list[str] = Field(default_factory=list)

    @property
    def finish_rate(self) -> float:
        return self.completed / self.rated if self.rated else 0.0

    @property
    def is_empty(self) -> bool:
        return self.rated == 0


def _score(fb: FeedbackIn) -> float | None:
    if fb.rating is not None:
        return float(fb.rating)
    return None if fb.completed else UNRATED_SKIP_SCORE


def _confident(scores: list[float], threshold: float, above: bool) -> bool:
    """One strong signal (a 5 or a 1) counts; otherwise need two ratings on average past the threshold."""
    avg = sum(scores) / len(scores)
    if len(scores) == 1:
        return scores[0] >= 5 if above else scores[0] <= 1
    return avg >= threshold if above else avg <= threshold


def _rank(groups: dict[str, list[float]], above: bool) -> list[str]:
    threshold = LIKE_THRESHOLD if above else DISLIKE_THRESHOLD
    picked = [(k, sum(v) / len(v), len(v)) for k, v in groups.items() if _confident(v, threshold, above)]
    picked.sort(key=lambda t: (-t[1] if above else t[1], -t[2], t[0]))
    return [k for k, _, _ in picked[:MAX_TAGS]]


def learn_taste(rated: Iterable[tuple[Quest, FeedbackIn]]) -> Taste:
    """`rated` = (quest, feedback) pairs, newest first (db.rated_quests)."""
    rated = list(rated)
    by_tag: dict[str, list[float]] = defaultdict(list)
    by_difficulty: dict[str, list[float]] = defaultdict(list)
    ratios: list[float] = []
    comments: list[str] = []
    completed = 0
    for quest, fb in rated:
        completed += fb.completed
        score = _score(fb)
        if score is not None:
            for tag in {t.strip().lower() for t in quest.tags if t.strip()}:
                by_tag[tag].append(score)
            by_difficulty[quest.difficulty.value].append(score)
        if fb.completed and fb.time_logged_minutes and quest.estimated_minutes:
            ratios.append(fb.time_logged_minutes / quest.estimated_minutes)
        if fb.comment.strip() and len(comments) < MAX_COMMENTS:
            verdict = f"rated {fb.rating}/5" if fb.rating else ("finished" if fb.completed else "didn't finish")
            comments.append(f'"{fb.comment.strip()}" ({quest.title}, {verdict})')

    liked = _rank(by_tag, above=True)
    disliked = [t for t in _rank(by_tag, above=False) if t not in liked]
    return Taste(
        rated=len(rated),
        completed=completed,
        not_finished=len(rated) - completed,
        liked_tags=liked,
        disliked_tags=disliked,
        liked_difficulty=_rank(by_difficulty, above=True),
        disliked_difficulty=_rank(by_difficulty, above=False),
        time_ratio=round(sum(ratios) / len(ratios), 2) if ratios else None,
        recent_comments=comments,
    )


def taste_block(taste: Taste) -> str:
    """Prompt text: what the feedback says, as instructions Gemma can act on."""
    lines = [f"- They've given feedback on {taste.rated} quest(s): finished {taste.completed}, "
             f"didn't finish {taste.not_finished}."]
    if taste.liked_tags:
        lines.append(f"- Kinds of quests they rate highly: {', '.join(taste.liked_tags)} - lean toward these.")
    if taste.disliked_tags:
        lines.append(f"- Kinds of quests they rate low or abandon: {', '.join(taste.disliked_tags)} - "
                     "avoid building the quest around these.")
    if taste.liked_difficulty:
        lines.append(f"- Difficulty that works for them: {', '.join(taste.liked_difficulty)}.")
    if taste.disliked_difficulty:
        lines.append(f"- Difficulty that hasn't worked: {', '.join(taste.disliked_difficulty)}.")
    if taste.time_ratio is not None:
        if taste.time_ratio >= 1.25:
            lines.append(f"- They usually take longer than estimated (about {taste.time_ratio:g}x) - keep the "
                         "quest tighter than the time limit.")
        elif taste.time_ratio <= 0.75:
            lines.append(f"- They usually finish faster than estimated (about {taste.time_ratio:g}x) - a bit "
                         "more depth is fine.")
    if taste.rated >= 4 and taste.finish_rate < 0.5:
        lines.append("- They often don't finish quests - make this one easy to start and quick to wrap up.")
    if taste.recent_comments:
        lines.append("- Their recent comments: " + "; ".join(taste.recent_comments))
    return "\n".join(lines)


def _tags(tags: Iterable[str]) -> set[str]:
    return {t.strip().lower() for t in tags}


def conflicts_with_taste(quest: Quest, taste: Taste | None) -> list[str]:
    """Disliked tags this quest is built around (>=2 of them and no liked tag), else []."""
    if taste is None or not taste.disliked_tags:
        return []
    tags = _tags(quest.tags)
    hits = sorted(tags & set(taste.disliked_tags))
    if len(hits) >= 2 and not (tags & set(taste.liked_tags)):
        return hits
    return []


def rerank_examples(examples: Sequence[QuestExample], taste: Taste | None, k: int) -> list[QuestExample]:
    """Keep retrieval order but move examples that look like disliked quests
    to the back and those matching liked tags to the front (stable)."""
    if taste is None or taste.is_empty:
        return list(examples)[:k]
    liked, disliked = set(taste.liked_tags), set(taste.disliked_tags)

    def key(item: tuple[int, QuestExample]) -> tuple[int, int, int]:
        i, ex = item
        tags = _tags(ex.tags) | {ex.category.lower()}
        bad = len(tags & disliked)
        good = len(tags & liked)
        return (1 if bad >= 1 and not good else 0, -good, i)

    return [ex for _, ex in sorted(enumerate(examples), key=key)][:k]
