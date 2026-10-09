"""Sidequest backend API.

Run with:  uvicorn backend.main:app --reload
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Path, Query, status

from . import db
from .llm import GemmaClient, LLMClient, LLMError
from .quest_generator import generate_quest
from .schemas import USER_ID_PATTERN, FeedbackIn, PreferencesIn, PreferencesOut, QuestRecord

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Sidequest API", version="0.1.0", lifespan=lifespan)

UserId = Path(..., pattern=USER_ID_PATTERN, description="3-64 chars: letters, digits, _ . @ -")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/users/{user_id}/preferences", response_model=PreferencesOut)
def read_preferences(user_id: str = UserId) -> PreferencesOut:
    prefs = db.get_preferences(user_id)
    if prefs is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No preferences saved for this user")
    return prefs


@app.put("/users/{user_id}/preferences", response_model=PreferencesOut)
def save_preferences(prefs: PreferencesIn, user_id: str = UserId) -> PreferencesOut:
    return db.upsert_preferences(user_id, prefs)


@app.delete("/users/{user_id}/preferences", status_code=status.HTTP_204_NO_CONTENT)
def remove_preferences(user_id: str = UserId) -> None:
    if not db.delete_preferences(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No preferences saved for this user")


# ---------------------------------------------------------------------------
# Quests
# ---------------------------------------------------------------------------

def get_llm() -> LLMClient:
    """Dependency so tests can swap in a fake model."""
    return GemmaClient()


@app.post("/users/{user_id}/quests", response_model=QuestRecord, status_code=status.HTTP_201_CREATED)
def create_quest(user_id: str = UserId, llm: LLMClient = Depends(get_llm)) -> QuestRecord:
    """Generate a new sidequest from the user's saved preferences and history."""
    profile = db.get_preferences(user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Save preferences before generating a quest")

    prefs = PreferencesIn.model_validate(profile.model_dump(exclude={"user_id", "created_at", "updated_at"}))
    # Both are empty on a user's first run - generate_quest handles that.
    examples = db.retrieve_examples(user_id, prefs) or None
    history = db.feedback_history(user_id) or None

    try:
        quest = generate_quest(prefs, examples, history, llm=llm)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return db.add_quest(user_id, quest, model=getattr(llm, "model", ""))


@app.get("/users/{user_id}/quests", response_model=list[QuestRecord])
def read_quests(user_id: str = UserId, limit: int = Query(20, ge=1, le=100)) -> list[QuestRecord]:
    return db.list_quests(user_id, limit)


@app.post("/users/{user_id}/quests/{quest_id}/feedback", response_model=QuestRecord)
def give_feedback(feedback: FeedbackIn, quest_id: int, user_id: str = UserId) -> QuestRecord:
    record = db.set_feedback(user_id, quest_id, feedback)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quest not found")
    return record
