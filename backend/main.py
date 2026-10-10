"""Sidequest backend API.

Run with:  uvicorn backend.main:app --reload
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, history, library, retrieval, taste as taste_mod
from .llm import GemmaClient, LLMClient, LLMError
from .quest_generator import generate_quest
from .schemas import (
    FeedbackEntry,
    FeedbackIn,
    PreferencesIn,
    PreferencesOut,
    QuestExample,
    QuestRecord,
    QuestSettings,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sidequest.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    auth.init_auth()
    if not os.getenv("GEMMA_API_KEY") and "googleapis" in os.getenv(
        "GEMMA_BASE_URL", "https://generativelanguage.googleapis.com"
    ):
        log.warning("GEMMA_API_KEY is not set - quest generation will fail. Add it to .env and restart.")
    try:
        library.init_library()  # create/migrate/seed data/quest_library.db
    except Exception as exc:  # the app still works without the library
        log.warning("Quest library unavailable: %s", exc)
    try:
        history.init_history()  # create data/user_history.db + copy logged quests from the library
    except Exception as exc:
        log.warning("User history unavailable: %s", exc)
    yield


app = FastAPI(title="Sidequest API", version="0.2.0", lifespan=lifespan)

# Flutter web runs on another origin (e.g. localhost:5xxxx). Native apps ignore CORS.
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=None if _origins else r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every /users/{user_id}/... route: you must be logged in as that user
# (or AUTH_REQUIRED=false for local dev without accounts).
UserId = Depends(auth.authorized_user_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@app.post("/auth/signup", response_model=auth.SessionOut, status_code=status.HTTP_201_CREATED)
def sign_up(data: auth.SignUpIn) -> auth.SessionOut:
    return auth.create_session(auth.create_user(data))


@app.post("/auth/login", response_model=auth.SessionOut)
def log_in(data: auth.LogInIn) -> auth.SessionOut:
    user = auth.authenticate(data.email, data.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    return auth.create_session(user)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def log_out(token: str = Depends(auth.current_token)) -> None:
    auth.delete_session(token)


@app.get("/auth/me", response_model=auth.UserOut)
def me(user: auth.UserOut = Depends(auth.current_user)) -> auth.UserOut:
    return user


@app.patch("/auth/me", response_model=auth.UserOut)
def update_me(changes: auth.AccountUpdate, user: auth.UserOut = Depends(auth.current_user)) -> auth.UserOut:
    return auth.update_user(user.id, changes)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

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


def get_retriever() -> retrieval.Retriever | None:
    """Where example quests come from: Tiger Data if TIGER_DATABASE_URL is set,
    otherwise the local SQLite library (data/quest_library.db) if it exists."""
    if retrieval.is_configured():
        return retrieval.TigerRetriever()
    if library.is_available():
        return library.LocalLibraryRetriever()
    return None


def find_examples(
    user_id: str,
    prefs: PreferencesIn,
    history: list[FeedbackEntry] | None,
    retriever: retrieval.Retriever | None,
    k: int = 3,
    taste: taste_mod.Taste | None = None,
) -> list[QuestExample]:
    """Top-k example quests from the vector library (Tiger or local), falling
    back to the user's own liked quests if no library is available. Pulls a
    few extra and re-ranks them by the user's learned taste, so kinds of
    quests they dislike aren't shown to Gemma as inspiration."""
    if retriever is not None:
        try:
            examples = retriever.retrieve(prefs, history, k=k * 3)
            if examples:
                return taste_mod.rerank_examples(examples, taste, k)
        except retrieval.RetrievalError as exc:
            log.warning("Library retrieval failed, using the user's past quests instead: %s", exc)
    return db.retrieve_examples(user_id, prefs, k=k)


@app.post("/users/{user_id}/quests", response_model=QuestRecord, status_code=status.HTTP_201_CREATED)
def create_quest(
    settings: QuestSettings | None = Body(None),
    user_id: str = UserId,
    llm: LLMClient = Depends(get_llm),
    retriever: retrieval.Retriever | None = Depends(get_retriever),
) -> QuestRecord:
    """Generate a new sidequest from the user's saved preferences and history.

    Optional body: this quest's minutes / difficulty / energy / distance
    (picked right before each quest in the app); missing ones come from the profile."""
    profile = db.get_preferences(user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Save preferences before generating a quest")

    prefs = PreferencesIn.model_validate(profile.model_dump(exclude={"user_id", "created_at", "updated_at"}))
    if settings is not None:
        prefs = settings.apply(prefs)
    # Feedback is empty on a user's first run; examples come from the Tiger
    # library (so even new users get them) or, failing that, past liked quests.
    feedback = db.feedback_history(user_id) or None
    # The feedback loop: patterns from everything this user has rated.
    taste = taste_mod.learn_taste(db.rated_quests(user_id))
    if not taste.is_empty:
        log.info("Feedback loop for %s: %d rated, likes %s, dislikes %s, time x%s",
                 user_id, taste.rated, taste.liked_tags, taste.disliked_tags, taste.time_ratio)
    examples = find_examples(user_id, prefs, feedback, retriever, taste=taste) or None
    try:  # the user's last 10 quests + how they went (data/user_history.db)
        recent = history.recent(user_id)
    except Exception as exc:
        log.warning("Couldn't read user history: %s", exc)
        recent = []

    try:
        quest = generate_quest(prefs, examples, feedback, recent_quests=recent, taste=taste, llm=llm)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    record = db.add_quest(user_id, quest, model=getattr(llm, "model", ""))
    try:  # also keep it in the quest library alongside the seeded quests
        library.add_generated(record.id, user_id, quest, model=record.model)
    except Exception as exc:
        log.warning("Couldn't add quest %s to the library: %s", record.id, exc)
    try:  # and to the user's history (keeps their last 10)
        history.add_quest(record.id, user_id, quest, model=record.model)
    except Exception as exc:
        log.warning("Couldn't add quest %s to the user history: %s", record.id, exc)
    return record


@app.get("/users/{user_id}/quests", response_model=list[QuestRecord])
def read_quests(user_id: str = UserId, limit: int = Query(20, ge=1, le=100)) -> list[QuestRecord]:
    return db.list_quests(user_id, limit)


@app.post("/users/{user_id}/quests/{quest_id}/feedback", response_model=QuestRecord)
def give_feedback(feedback: FeedbackIn, quest_id: int, user_id: str = UserId) -> QuestRecord:
    record = db.set_feedback(user_id, quest_id, feedback)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quest not found")
    try:
        library.record_feedback(quest_id, feedback)
    except Exception as exc:
        log.warning("Couldn't store feedback for quest %s in the library: %s", quest_id, exc)
    try:  # after the library, so a pruned quest with logged time can be copied back from it
        history.record_feedback(quest_id, feedback)
    except Exception as exc:
        log.warning("Couldn't store feedback for quest %s in the user history: %s", quest_id, exc)
    return record
