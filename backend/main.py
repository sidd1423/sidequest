"""Sidequest backend API.

Run with:  uvicorn backend.main:app --reload
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, friends, history, journal, library, retrieval, rewards, streak, taste as taste_mod
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
    journal.init_journal()
    streak.init_streaks()
    friends.init_friends()
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


@app.delete("/auth/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(confirm: auth.DeleteAccountIn, user: auth.UserOut = Depends(auth.current_user)) -> None:
    """Delete the account and ALL its data (preferences, quests, feedback,
    journal, history, generated quests in the library). Needs the password."""
    if not auth.password_matches(user.id, confirm.password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Wrong password")
    db.delete_user_data(user.id)
    for cleanup in (library.delete_user, history.delete_user, friends.delete_user):
        try:
            cleanup(user.id)
        except Exception as exc:
            log.warning("Couldn't remove %s's data via %s: %s", user.id, cleanup.__module__, exc)
    auth.delete_user(user.id)
    log.info("Deleted account %s", user.id)


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


@app.get("/users/{user_id}/stats")
def read_stats(user_id: str = UserId) -> dict[str, int]:
    """{completed, generated, minutes_outside} - the counter on the app's Quest screen."""
    return db.quest_stats(user_id)


# ---------------------------------------------------------------------------
# Quest journal (notes + photos)
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/quests/{quest_id}/logs", response_model=list[journal.LogOut])
def read_logs(quest_id: int, user_id: str = UserId) -> list[journal.LogOut]:
    return journal.list_for_quest(user_id, quest_id)


@app.post("/users/{user_id}/quests/{quest_id}/logs", response_model=journal.LogOut,
          status_code=status.HTTP_201_CREATED)
def add_log(entry: journal.LogIn, quest_id: int, user_id: str = UserId) -> journal.LogOut:
    """Add a note or photo. Same client_id again = update (safe to retry)."""
    return journal.add(user_id, quest_id, entry)


@app.get("/users/{user_id}/logs/{log_id}/photo")
def read_photo(log_id: int, user_id: str = UserId) -> Response:
    data, mime = journal.photo(user_id, log_id)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@app.delete("/users/{user_id}/logs/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(client_id: str, user_id: str = UserId) -> None:
    journal.delete(user_id, client_id)  # already gone is fine (offline retries)


# The app sends its UTC offset (minutes east of UTC, e.g. -240 for Toronto in
# summer) so "today" and streak days follow the user's own midnight.
TzOffset = Query(0, ge=-streak.MAX_TZ_OFFSET, le=streak.MAX_TZ_OFFSET)


@app.get("/users/{user_id}/rewards", response_model=rewards.Rewards)
def read_rewards(user_id: str = UserId, tz_offset_minutes: int = TzOffset) -> rewards.Rewards:
    """Points, level, streaks and badges (see backend/rewards.py for the rules)."""
    return rewards.compute(user_id, tz_offset_minutes=tz_offset_minutes)


# ---------------------------------------------------------------------------
# Daily streak (see backend/streak.py for the rules)
# ---------------------------------------------------------------------------

def _streak(user_id: str, tz_offset_minutes: int) -> streak.Streak:
    points = rewards.compute(user_id, tz_offset_minutes=tz_offset_minutes).points
    return streak.compute(user_id, points, tz_offset_minutes)


@app.get("/users/{user_id}/streak", response_model=streak.Streak)
def read_streak(user_id: str = UserId, tz_offset_minutes: int = TzOffset) -> streak.Streak:
    """Current/best streak, freezes, today's status and calendar days."""
    return _streak(user_id, tz_offset_minutes)


@app.post("/users/{user_id}/streak/freeze", response_model=streak.Streak, status_code=status.HTTP_201_CREATED)
def buy_streak_freeze(user_id: str = UserId, tz_offset_minutes: int = TzOffset) -> streak.Streak:
    """Spend points on a streak freeze. 409 if you can't (not enough points / already holding the max)."""
    points = rewards.compute(user_id, tz_offset_minutes=tz_offset_minutes).points
    try:
        streak.buy_freeze(user_id, points, tz_offset_minutes)
    except streak.FreezeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return streak.compute(user_id, points, tz_offset_minutes)


# ---------------------------------------------------------------------------
# Friends (see backend/friends.py)
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/friends", response_model=friends.FriendsOut)
def read_friends(user_id: str = UserId) -> friends.FriendsOut:
    """Your friends (with a few stats), requests waiting for you, and requests you sent."""
    return friends.list_for(user_id)


@app.post("/users/{user_id}/friends/requests", response_model=friends.RequestResult,
          status_code=status.HTTP_201_CREATED)
def send_friend_request(body: friends.FriendRequestIn, user_id: str = UserId) -> friends.RequestResult:
    """Ask someone to be friends by the email on their account. 404 no such account,
    409 already friends / already asked. If they already asked you, you're friends now."""
    return friends.send_request(user_id, body.email)


@app.post("/users/{user_id}/friends/requests/{request_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_friend_request(request_id: int, user_id: str = UserId) -> None:
    friends.respond(user_id, request_id, accept=True)


@app.post("/users/{user_id}/friends/requests/{request_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_friend_request(request_id: int, user_id: str = UserId) -> None:
    friends.respond(user_id, request_id, accept=False)


@app.delete("/users/{user_id}/friends/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_friend_request(request_id: int, user_id: str = UserId) -> None:
    friends.cancel(user_id, request_id)


@app.delete("/users/{user_id}/friends/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(friend_id: str, user_id: str = UserId) -> None:
    friends.remove(user_id, friend_id)
