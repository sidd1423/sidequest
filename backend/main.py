"""Sidequest backend API.

Run with:  uvicorn backend.main:app --reload
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Callable

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware

from . import auth, db, friends, history, journal, parties, library, local_context, retrieval, rewards, routes, streak
from . import personal_model
from . import observability
from . import taste as taste_mod
from .llm import GemmaClient, LLMClient, LLMError
from .quest_generator import generate_quest
from .schemas import (
    FeedbackEntry,
    FeedbackIn,
    GeoPoint,
    GroupSize,
    PreferencesIn,
    Quest,
    PreferencesOut,
    QuestContext,
    QuestExample,
    QuestRecord,
    QuestSettings,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sidequest.api")
observability.init()  # Sentry, if SENTRY_DSN is set - before the app so FastAPI gets instrumented


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    auth.init_auth()
    journal.init_journal()
    streak.init_streaks()
    friends.init_friends()
    parties.init_parties()
    routes.init_routes()
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
    try:
        personal_model.init()  # data/personal_models.db (per-user Tinker models, if TINKER_API_KEY is set)
    except Exception as exc:
        log.warning("Personal models unavailable: %s", exc)
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
    for cleanup in (library.delete_user, history.delete_user, friends.delete_user, parties.delete_user,
                    personal_model.delete_user):
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


ContextLookup = Callable[..., QuestContext]  # (location, max_travel_km, place_hint, interests)


def get_context_lookup() -> ContextLookup:
    """Dependency so tests can swap in fake weather/places (backend/local_context.py)."""
    return local_context.lookup


def _interests(prefs: PreferencesIn | None) -> list[str]:
    if prefs is None:
        return []
    return [i.value for i in prefs.interests] + list(prefs.custom_interests)


def local_conditions(
    settings: QuestSettings | None, max_travel_km: float, lookup: ContextLookup | None,
    interests: list[str] | None = None,
) -> QuestContext | None:
    """Weather, place name and real spots nearby for this quest - from the device's
    location, or a place the user typed. None if we don't know where they are."""
    if settings is None or lookup is None:
        return None
    location, hint = settings.location, ""
    if location is None and settings.place and settings.place.strip():
        hint = settings.place.strip()
        location = local_context.geocode(hint)
        if location is None:  # couldn't find it - still tell the model the place name
            return QuestContext(place=hint)
    if location is None:
        return None
    try:
        return lookup(location, max_travel_km, hint, interests or [])
    except Exception as exc:  # never block a quest on the weather
        log.warning("Local conditions lookup failed: %s", exc)
        return None


def find_examples(
    user_id: str,
    prefs: PreferencesIn,
    history: list[FeedbackEntry] | None,
    retriever: retrieval.Retriever | None,
    k: int = 3,
    taste: taste_mod.Taste | None = None,
    context: QuestContext | None = None,
) -> list[QuestExample]:
    """Top-k example quests from the vector library (Tiger or local), falling
    back to the user's own liked quests if no library is available. Pulls a
    few extra and re-ranks them by the user's learned taste, so kinds of
    quests they dislike aren't shown to Gemma as inspiration."""
    if retriever is not None:
        try:
            if context is not None and not context.is_empty:
                examples = retriever.retrieve(prefs, history, k=k * 3, context=context)
            else:
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
    lookup: ContextLookup = Depends(get_context_lookup),
) -> QuestRecord:
    """Generate a new sidequest from the user's saved preferences and history.

    Optional body: this quest's minutes / difficulty / energy / distance
    (picked right before each quest in the app) and where the user is
    (`location` from the device, or a typed `place`) - used to look up the
    weather and real places nearby. Missing settings come from the profile."""
    llm = personal_model.llm_for(user_id, llm)  # their own fine-tuned model, if they have one
    prompts: list[str] = []
    quest, context = generate_for(user_id, settings, llm, retriever, lookup=lookup, prompt_out=prompts)
    record = save_generated(user_id, quest, getattr(llm, "model", ""), context, prompt=prompts[0] if prompts else None)
    return routes.attach([record])[0]


def generate_for(
    user_id: str,
    settings: QuestSettings | None,
    llm: LLMClient,
    retriever: retrieval.Retriever | None,
    party_size: int | None = None,
    lookup: ContextLookup | None = None,
    prompt_out: list[str] | None = None,
) -> tuple[Quest, QuestContext | None]:
    """One quest for this user's preferences + history (+ this quest's settings
    and live local conditions). party_size: a group quest for that many friends
    (see backend/parties.py)."""
    observability.set_user(user_id)
    profile = db.get_preferences(user_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Save preferences before generating a quest")

    prefs = PreferencesIn.model_validate(profile.model_dump(exclude={"user_id", "created_at", "updated_at"}))
    if settings is not None:
        prefs = settings.apply(prefs)
    if party_size and party_size >= 2:
        group = GroupSize.PAIR if party_size == 2 else GroupSize.SMALL_GROUP if party_size <= 5 else GroupSize.LARGE_GROUP
        prefs = QuestSettings(group_size=group).apply(prefs)
    # Feedback is empty on a user's first run; examples come from the Tiger
    # library (so even new users get them) or, failing that, past liked quests.
    feedback = db.feedback_history(user_id) or None
    # The feedback loop: patterns from everything this user has rated.
    taste = taste_mod.learn_taste(db.rated_quests(user_id))
    if not taste.is_empty:
        log.info("Feedback loop for %s: %d rated, likes %s, dislikes %s, time x%s",
                 user_id, taste.rated, taste.liked_tags, taste.disliked_tags, taste.time_ratio)
    context = local_conditions(settings, prefs.environment.max_travel_km, lookup, _interests(prefs))
    if context is not None:
        w = context.weather
        log.info("Local conditions for %s: %s; %s; %d places nearby", user_id, context.place or "?",
                 f"{w.temp_c:.0f}C {w.condition}" if w else "no weather", len(context.nearby))
    examples = find_examples(user_id, prefs, feedback, retriever, taste=taste, context=context) or None
    try:  # the user's last 10 quests + how they went (data/user_history.db)
        recent = history.recent(user_id)
    except Exception as exc:
        log.warning("Couldn't read user history: %s", exc)
        recent = []

    try:
        quest = generate_quest(prefs, examples, feedback, recent_quests=recent, taste=taste, llm=llm,
                               party_size=party_size, context=context, prompt_out=prompt_out)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return quest, context


def save_generated(user_id: str, quest: Quest, model: str, context: QuestContext | None = None,
                   prompt: str | None = None) -> QuestRecord:
    """Store a generated quest for this user (+ the quest library and their history).
    `prompt` (what the model was asked) becomes training input for their personal model."""
    record = db.add_quest(user_id, quest, model=model, context=context)
    if prompt:
        try:
            personal_model.save_prompt(record.id, user_id, prompt)
        except Exception as exc:
            log.warning("Couldn't store the prompt for quest %s: %s", record.id, exc)
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
    return routes.attach(parties.attach(db.list_quests(user_id, limit)))


@app.post("/users/{user_id}/quests/{quest_id}/feedback", response_model=QuestRecord)
def give_feedback(feedback: FeedbackIn, quest_id: int, user_id: str = UserId) -> QuestRecord:
    record = db.set_feedback(user_id, quest_id, feedback)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quest not found")
    parties.attach([record])
    routes.attach([record])
    try:
        library.record_feedback(quest_id, feedback)
    except Exception as exc:
        log.warning("Couldn't store feedback for quest %s in the library: %s", quest_id, exc)
    try:  # after the library, so a pruned quest with logged time can be copied back from it
        history.record_feedback(quest_id, feedback)
    except Exception as exc:
        log.warning("Couldn't store feedback for quest %s in the user history: %s", quest_id, exc)
    try:  # every few feedbacks, retrain their personal model in the background
        personal_model.note_feedback(user_id)
    except Exception as exc:
        log.warning("Couldn't schedule personal model training for %s: %s", user_id, exc)
    return record


@app.delete("/users/{user_id}/quests/{quest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unstarted_quest(quest_id: int, user_id: str = UserId) -> None:
    """A quest the user never started, replaced by a new one: removed everywhere
    (quests, the quest library and the user history), as if it was never made.
    Finished / given-up quests and group quest copies are kept (409).
    Already gone is fine (the app's offline outbox may retry)."""
    result = db.delete_unstarted_quest(user_id, quest_id)
    if result == "rated":
        raise HTTPException(status.HTTP_409_CONFLICT, "This quest was started - it's kept in your history")
    if result == "group":
        raise HTTPException(status.HTTP_409_CONFLICT, "Group quests are kept")
    if result != "deleted":
        return
    for forget, where in ((library.delete_generated, "library"), (history.delete_quest, "user history"),
                          (personal_model.delete_quest, "personal model prompts")):
        try:
            forget(quest_id)
        except Exception as exc:
            log.warning("Couldn't delete quest %s from the %s: %s", quest_id, where, exc)


@app.get("/users/{user_id}/model", response_model=personal_model.PersonalModelStatus)
def read_personal_model(user_id: str = UserId) -> personal_model.PersonalModelStatus:
    """The user's own fine-tuned quest model: off / collecting feedback / training / ready."""
    return personal_model.status(user_id)


@app.post("/users/{user_id}/model/train", response_model=personal_model.PersonalModelStatus,
          status_code=status.HTTP_202_ACCEPTED)
def train_personal_model(user_id: str = UserId) -> personal_model.PersonalModelStatus:
    """Retrain the user's personal model now (in the background)."""
    if not personal_model.is_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Personal models are off - set TINKER_API_KEY in .env and restart")
    current = personal_model.status(user_id)
    if current.rated_quests < personal_model.min_feedback():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Rate at least {personal_model.min_feedback()} quests first "
                            f"(you've rated {current.rated_quests})")
    personal_model.schedule(user_id)
    return personal_model.status(user_id)


@app.get("/users/{user_id}/stats")
def read_stats(user_id: str = UserId) -> dict[str, int]:
    """{completed, generated, minutes_outside} - the counter on the app's Quest screen."""
    return db.quest_stats(user_id)


# ---------------------------------------------------------------------------
# Recorded route (the path walked during a quest; see backend/routes.py)
# ---------------------------------------------------------------------------

@app.put("/users/{user_id}/quests/{quest_id}/route", response_model=routes.RouteOut)
def save_route(route: routes.RouteIn, quest_id: int, user_id: str = UserId) -> routes.RouteOut:
    """Store the whole recorded path (replaces any earlier copy - safe to re-send)."""
    return routes.save(user_id, quest_id, route)


@app.get("/users/{user_id}/quests/{quest_id}/route", response_model=routes.RouteOut)
def read_route(quest_id: int, user_id: str = UserId) -> routes.RouteOut:
    route = routes.get(user_id, quest_id)
    if route is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No route recorded for this quest")
    return route


@app.delete("/users/{user_id}/quests/{quest_id}/route", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(quest_id: int, user_id: str = UserId) -> None:
    routes.delete(user_id, quest_id)  # already gone is fine


@app.get("/users/{user_id}/conditions", response_model=QuestContext)
def read_conditions(
    user_id: str = UserId,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    max_travel_km: float = Query(1.0, ge=0, le=5),
    lookup: ContextLookup = Depends(get_context_lookup),
) -> QuestContext:
    """Weather + place + nearby spots at a position (the app shows it before you generate)."""
    return lookup(GeoPoint(lat=lat, lon=lon), max_travel_km, "", _interests(db.get_preferences(user_id)))


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
def read_friends(user_id: str = UserId, tz_offset_minutes: int = TzOffset) -> friends.FriendsOut:
    """Your friends (with stats: quests this week, minutes today, streak - in your
    time zone), requests waiting for you, and requests you sent."""
    return friends.list_for(user_id, tz_offset_minutes)


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



# ---------------------------------------------------------------------------
# Group quests with friends (see backend/parties.py)
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/parties", response_model=list[parties.PartyOut])
def read_parties(user_id: str = UserId) -> list[parties.PartyOut]:
    """Group quests you host, joined or are invited to (open, or started in the last day)."""
    return parties.list_for(user_id)


@app.post("/users/{user_id}/parties", response_model=parties.PartyOut, status_code=status.HTTP_201_CREATED)
def create_party(body: parties.PartyIn, user_id: str = UserId) -> parties.PartyOut:
    """Invite friends to a group quest. The quest is generated when you start it."""
    if db.get_preferences(user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Save preferences before starting a group quest")
    return parties.create(user_id, body)


@app.post("/users/{user_id}/parties/{party_id}/join", response_model=parties.PartyOut)
def join_party(party_id: int, user_id: str = UserId) -> parties.PartyOut:
    """Join. If it already started, you get your copy of the quest straight away."""
    party, quest_json, _ = parties.respond(user_id, party_id, join=True)
    if quest_json:
        record = save_generated(user_id, Quest.model_validate_json(quest_json), "group")
        parties.set_quest_id(party_id, user_id, record.id)
        party = parties.get(party_id, user_id)
    return party


@app.post("/users/{user_id}/parties/{party_id}/decline", response_model=parties.PartyOut)
def decline_party(party_id: int, user_id: str = UserId) -> parties.PartyOut:
    return parties.respond(user_id, party_id, join=False)[0]


@app.post("/users/{user_id}/parties/{party_id}/start", response_model=parties.PartyOut)
def start_party(
    party_id: int,
    where: parties.StartIn | None = Body(None),
    user_id: str = UserId,
    llm: LLMClient = Depends(get_llm),
    retriever: retrieval.Retriever | None = Depends(get_retriever),
    lookup: ContextLookup = Depends(get_context_lookup),
) -> parties.PartyOut:
    """Host only: generate ONE quest for everyone who joined and give each of them a copy.
    Optional body {location | place}: where the group is now (weather + nearby spots)."""
    joined, settings = parties.check_can_start(user_id, party_id)
    if where is not None and (where.location is not None or where.place):
        settings = (settings or QuestSettings()).model_copy(update={"location": where.location, "place": where.place})
    llm = personal_model.llm_for(user_id, llm)  # the host's personal model plans the group quest
    prompts: list[str] = []
    quest, context = generate_for(user_id, settings, llm, retriever, party_size=len(joined), lookup=lookup,
                                  prompt_out=prompts)
    if not parties.mark_started(party_id, quest, len(joined)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This group quest already started")
    model = getattr(llm, "model", "")
    for member in joined:
        record = save_generated(member, quest, model, context, prompt=prompts[0] if prompts else None)
        parties.set_quest_id(party_id, member, record.id)
    return parties.get(party_id, user_id)


@app.delete("/users/{user_id}/parties/{party_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_party(party_id: int, user_id: str = UserId) -> None:
    """Host only, before it starts."""
    parties.cancel(user_id, party_id)
