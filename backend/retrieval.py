"""Semantic retrieval of example quests from the Tiger Data (Postgres + pgvector) library.

The user's profile (and what they've liked before) is turned into a search
query, embedded, and matched against the `quests` table by cosine similarity.
The top matches are passed to Gemma as style/inspiration examples.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Protocol, Sequence

from .embeddings import Embedder, EmbeddingError, GeminiEmbedder
from .local_context import describe_for_search
from .schemas import FeedbackEntry, PreferencesIn, QuestContext, QuestExample

log = logging.getLogger("sidequest.retrieval")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


class RetrievalError(RuntimeError):
    pass


class Retriever(Protocol):
    """Anything that can return the top-k example quests for a user."""

    def retrieve(
        self, profile: PreferencesIn, feedback: Sequence[FeedbackEntry] | None = None, k: int = 3,
        context: QuestContext | None = None,
    ) -> list[QuestExample]: ...


def embedding_text(q: dict) -> str:
    """What we embed for each library quest - its text plus metadata."""
    return (
        f"{q['quest_text']} Category: {q['category']}. "
        f"Takes about {q['duration_minutes']} minutes. Difficulty: {q['difficulty']}. "
        f"Tags: {', '.join(q['tags'])}."
    )


def tiger_url() -> str:
    return os.getenv("TIGER_DATABASE_URL", "").strip()


def table_name() -> str:
    name = os.getenv("TIGER_QUESTS_TABLE", "quests").strip()
    if not _IDENT.match(name):
        raise RetrievalError(f"Invalid TIGER_QUESTS_TABLE: {name!r}")
    return name


def is_configured() -> bool:
    return bool(tiger_url())


def build_query_text(
    profile: PreferencesIn, feedback: Sequence[FeedbackEntry] | None = None, context: QuestContext | None = None
) -> str:
    """Describe what this user wants, in words, for the embedding model.

    Interests lead (and are repeated) because they matter most for relevance;
    hard limits like time and weather are enforced elsewhere, not by similarity.
    """
    interests = [i.value for i in profile.interests] + profile.custom_interests
    env = profile.environment
    parts = [
        f"{', '.join(interests)} sidequest.",
        f"A quick outdoor activity about {' and '.join(interests)}, right now.",
        f"Difficulty {profile.difficulty.value}, energy {profile.energy_level} of 5.",
    ]
    where = describe_for_search(context)
    if where:  # live weather + kinds of places nearby
        parts.append(where)
    if env.group_size.value != "solo":
        parts.append(f"With {env.group_size.value.replace('_', ' ')}, social.")
    if env.crowd_tolerance.value == "quiet":
        parts.append("Quiet, calm.")
    if profile.accessibility.needs:
        parts.append(f"Accessible: {', '.join(n.value.replace('_', ' ') for n in profile.accessibility.needs)}.")
    if feedback:
        liked = [f.quest_title for f in feedback if f.completed and (f.rating or 0) >= 4]
        if liked:
            parts.append(f"Similar to quests they loved: {'; '.join(liked[:3])}.")
    return " ".join(parts)


def interest_terms(profile: PreferencesIn) -> set[str]:
    return {i.value for i in profile.interests} | {c.lower() for c in profile.custom_interests}


SEARCH_SQL = """
SELECT quest_text, category, duration_minutes, difficulty, tags,
       1 - (embedding <=> %(q)s::vector) AS similarity
FROM {table}
WHERE embedding IS NOT NULL
ORDER BY (duration_minutes > %(max_minutes)s),   -- prefer quests that fit the time budget
         embedding <=> %(q)s::vector
LIMIT %(k)s
"""


class TigerRetriever:
    def __init__(self, url: str | None = None, embedder: Embedder | None = None, table: str | None = None):
        self.url = url or tiger_url()
        if not self.url:
            raise RetrievalError("TIGER_DATABASE_URL is not set")
        self.table = table or table_name()
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = GeminiEmbedder()
        return self._embedder

    def search(self, query_text: str, k: int = 3, max_minutes: int = 720) -> list[QuestExample]:
        import psycopg  # imported lazily so the app runs without Tiger configured

        try:
            [vector] = self.embedder.embed([query_text], task="RETRIEVAL_QUERY")
        except EmbeddingError as exc:
            raise RetrievalError(str(exc)) from exc

        literal = "[" + ",".join(f"{x:.7f}" for x in vector) + "]"
        sql = SEARCH_SQL.format(table=self.table)
        try:
            with psycopg.connect(self.url, connect_timeout=10) as conn:
                rows = conn.execute(sql, {"q": literal, "k": k, "max_minutes": max_minutes}).fetchall()
        except psycopg.Error as exc:
            raise RetrievalError(f"Tiger Data query failed: {exc}") from exc

        return [
            QuestExample(
                quest_text=r[0], category=r[1], duration_minutes=r[2],
                difficulty=r[3], tags=list(r[4] or []), similarity=round(float(r[5]), 4),
            )
            for r in rows
        ]

    def retrieve(
        self, profile: PreferencesIn, feedback: Sequence[FeedbackEntry] | None = None, k: int = 3,
        context: QuestContext | None = None,
    ) -> list[QuestExample]:
        query = build_query_text(profile, feedback, context)
        results = self.search(query, k=k, max_minutes=profile.availability.duration_minutes)
        log.info("Tiger retrieval: %d examples (%s)", len(results),
                 ", ".join(f"{r.category}:{r.similarity}" for r in results))
        return results
