# sidequest

Sidequests are quick **5-30 minute things to do outside, right now** - small,
low-friction nudges to get people out of the house more often. The app tailors
each one to the user's interests, how much time they have, their energy and
accessibility needs - and to where they actually are: the live weather, time of
day and real places nearby are looked up from their location for every quest.
The app can also record the route you walk during a quest and show it on a map.

## Architecture

```
Streamlit UI (app.py)  ──HTTP/JSON──▶  FastAPI backend (backend/)  ──▶  SQLite (sidequest.db)
        │                                      │
        │                                      ├──▶  Gemma via inference API (backend/llm.py)
        │                                      └──▶  Example-quest library: local SQLite (backend/library.py)
        │                                                 or Tiger Data pgvector (backend/retrieval.py)
        └──────── shared Pydantic schema (backend/schemas.py) ────────┘
```

- **Frontend** `app.py`: preference form (interests, minutes available right
  now (5-30), difficulty, energy, accessibility, how far to go, crowds, group),
  plus a "Where are you right now?" box for each quest. Validates input with the
  shared schema, then sends it to the backend via `frontend/api_client.py`.
- **Backend** `backend/main.py`: REST API that validates and stores preferences.
- **Accounts** `backend/auth.py`: email + password sign-up/log-in. Passwords are
  hashed with salted PBKDF2-SHA256; log-in returns a random bearer token (only
  its SHA-256 is stored) valid for `SESSION_DAYS` (default 90, so the
  offline-first mobile app stays logged in). Every `/users/{user_id}/...` route
  only accepts the token of that user (401 without one, 403 for someone else's).
- **Storage** `backend/db.py`: preferences, quests and feedback in SQLite. Swap
  this module for Postgres later without touching the API or UI.
- **Quest generation** `backend/quest_generator.py`:
  `generate_quest(profile, retrieved_examples=None, feedback_history=None)`
  builds a prompt from the profile, asks Gemma for a JSON quest, validates it
  (and the user's time/setting limits), and retries up to 3 times.
  - `retrieved_examples`: the user's top-rated completed quests (`db.retrieve_examples`)
  - `feedback_history`: their recent completed/skipped quests with ratings & comments (`db.feedback_history`)
  - Both are empty on a user's first quest, so they're optional.
- **Example retrieval** `backend/retrieval.py`: turns the user's profile (and
  quests they loved) into a query, embeds it with `gemini-embedding-001`
  (768 dims), and pulls the 3 most similar quests from the Tiger Data `quests`
  table by cosine similarity, preferring ones that fit the user's time. These
  are passed to Gemma as `retrieved_examples`, so even first-time users get
  examples. If Tiger isn't configured or is unreachable, it falls back to the
  user's own top-rated quests.
- **Gemma client** `backend/llm.py`: calls any OpenAI-compatible
  `/chat/completions` endpoint - Google AI Studio by default, or Ollama/vLLM/etc.

### Feedback loop

Every rating the user sends (completed / didn't finish, 1-5 stars, time
spent, comment) changes the next quest in four places:

1. **Learned taste** (`backend/taste.py`): every quest the user has ever rated
   is boiled down to tags and difficulty they rate high or low (or abandon),
   whether they take longer or shorter than estimated, how often they finish,
   and their latest comments. This goes into the Gemma prompt as
   "What their feedback shows overall".
2. **Last 10 quests** (`data/user_history.db`): listed one by one as Loved /
   DISLIKED / Rated OK / Didn't finish, and never repeated.
3. **Example quests**: retrieval fetches extras and pushes examples that look
   like disliked quests to the back, so Gemma isn't inspired by them.
4. **Validation**: a Gemma answer built around disliked tags, or too similar to
   a disliked quest, is rejected and Gemma is asked again with the reason.

5. **Personal fine-tuned model** (optional, `backend/personal_model.py`) - see below.

The backend log prints the learned taste on each generation.

### Personal models (Tinker, optional)

With `TINKER_API_KEY` set, every user gets their **own LoRA adapter**, trained
with [Tinker](https://thinkingmachines.ai/tinker) on how their past quests went:

- **Loved** quests (completed, 4-5 stars; or didn't finish but rated 5) are
  reinforced with weighted fine-tuning on "the prompt -> that quest".
- **Disliked, abandoned and didn't-finish** quests are pushed *down* with a
  clipped PPO step (negative advantage), so the model learns what not to write
  without being wrecked by a few bad quests.
- **Recent quests weigh more**: weight halves every `PERSONAL_HALF_LIFE_DAYS`
  (14) days and every `PERSONAL_HALF_LIFE_QUESTS` (8) newer quests, whichever
  decays slower.

| Outcome | Reward |
|---|---|
| Completed 5 / 4 / 3 / 2 / 1 stars | +1.0 / +0.6 / +0.1 / -0.5 / -1.0 |
| Didn't finish, 5 / 4 / 3 / 2 / 1 stars | +0.5 / +0.2 / -0.3 / -0.8 / -1.0 |
| Didn't finish, no rating | -0.6 |

The first adapter is trained after `PERSONAL_MIN_FEEDBACK` (3) rated quests,
then retrained in a background thread after every `PERSONAL_RETRAIN_EVERY` (3)
new feedbacks (from the base model, on the whole recency-weighted history).
A new adapter only goes live if a test quest from it is valid JSON; the old
adapter checkpoint is then deleted.

Tinker has no Gemma, so adapters are trained on `PERSONAL_BASE_MODEL`
(default `Qwen/Qwen3.5-4B`). Gemma is still used for new users, if Tinker isn't
configured, and as an automatic fallback whenever the personal model fails.
The personal model still gets the full prompt (taste, last 10 quests,
examples, weather) and the same validation/retries. The exact prompt of every
quest is stored in `data/personal_models.db` as training input.

Other settings: `PERSONAL_LORA_RANK` (16), `PERSONAL_TRAIN_STEPS` (8),
`PERSONAL_LEARNING_RATE` (2e-4), `PERSONAL_MAX_EXAMPLES` (64),
`PERSONAL_MAX_TOKENS` (1024), `PERSONAL_TIMEOUT` (90 s),
`PERSONAL_MODELS=off` to disable while keeping the key.

### Live location context (`backend/local_context.py`)

Weather and "what's around you" are no longer profile questions. Each quest
request can carry the device's position (`location: {lat, lon, accuracy_m}`)
or a typed `place` ("Riverdale, Toronto", geocoded with Nominatim). The backend
then looks up, in parallel and with short timeouts (all free, no API keys):

- **Weather** from [Open-Meteo](https://open-meteo.com): temperature, feels-like,
  condition, rain chance for the next 2 hours, wind, UV, day/night, sunset, US AQI.
- **Place name** (neighbourhood, city) from OpenStreetMap Nominatim.
- **Real outdoor spots** within your travel distance from the OpenStreetMap
  Overpass API: parks, playgrounds, rivers, beaches, viewpoints, public art,
  trails, historic sites... with distance and compass direction.

**Google Maps places via SerpApi (optional, recommended).** Put
`SERPAPI_API_KEY=...` (from https://serpapi.com/manage-api-key) in `.env` and
nearby places come from Google Maps instead (`backend/serp_places.py`): names,
ratings, review counts, addresses and open/closed state, so quests can point at
a specific well-liked spot. Each quest runs `SERPAPI_MAX_QUERIES` searches
(default 2 = 2 credits): "park" plus one picked from your interests (art ->
"public art", history -> "historical landmark", custom interests as typed...).
Results are cached for `SERPAPI_CACHE_HOURS` (default 24) per search and ~100 m
area, and OpenStreetMap still fills in spots Google doesn't list (unnamed
viewpoints, paths). Typed places are geocoded with SerpApi too. If SerpApi fails
(bad key, out of searches) it falls back to OpenStreetMap automatically.

This goes into the prompt as a "Right now, where they are" section, plus
condition-specific hard rules (thunderstorm, icy, very hot/cold, windy, dark,
bad air, sunset soon), and Gemma is told to build the quest around real listed
places by exact name and never invent any. It also feeds the example-quest
search. The snapshot is stored with the quest (`QuestRecord.context`) and shown
on the quest card. Any lookup that fails is just left out - quests never wait on
the weather. Results are cached in memory (weather 10 min, places 1 day).
Config: `LOCAL_CONTEXT=off`, `CONTEXT_TIMEOUT`, `NOMINATIM_EMAIL` (recommended
by the Nominatim usage policy), `OPEN_METEO_URL`, `AIR_QUALITY_URL`,
`NOMINATIM_URL`, `OVERPASS_URL`.

Group quests: the host's position is sent when they press Start (never stored
on the invite, so invitees don't see it).

### Recorded routes (`backend/routes.py`)

The app records your path with GPS while you do a quest (foreground only) and
uploads it as a whole (`PUT`, safe to resend from the offline outbox). The
server stores it in `quest_routes` and works out distance (skipping fixes worse
than 75 m and jumps faster than 54 km/h) and duration. Only you can read it;
it's deleted with your account.

### API

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/health` | Health check |
| POST   | `/auth/signup` | Create an account `{name, email, password}` -> `{token, user}` |
| POST   | `/auth/login` | `{email, password}` -> `{token, user}` (a new session per device) |
| POST   | `/auth/logout` | Revoke the current token |
| GET / PATCH | `/auth/me` | The logged-in user / change name or email |
| DELETE | `/auth/me` | Delete the account and all its data. Body `{password}` |
| GET    | `/users/{user_id}/preferences` | Fetch saved preferences (404 if none) |
| PUT    | `/users/{user_id}/preferences` | Create or update preferences |
| DELETE | `/users/{user_id}/preferences` | Delete preferences |
| POST   | `/users/{user_id}/quests` | Generate a new sidequest with Gemma. Optional body `{duration_minutes, group_size, difficulty, energy_level, max_travel_km, location: {lat, lon, accuracy_m}, place}` overrides the profile for this quest and says where you are (weather + nearby places) |
| GET    | `/users/{user_id}/conditions?lat=&lon=&max_travel_km=` | Weather, place name and nearby spots at a position |
| PUT / GET / DELETE | `/users/{user_id}/quests/{quest_id}/route` | Recorded route `{points: [{lat, lon, t, accuracy_m}]}` -> with `distance_m`, `duration_seconds` |
| GET    | `/users/{user_id}/quests` | List the user's quests, newest first |
| GET    | `/users/{user_id}/rewards` | Points, level, streaks, badges and recent points (rules in `backend/rewards.py`) |
| GET    | `/users/{user_id}/streak?tz_offset_minutes=-240` | Duolingo-style daily streak: current/best, today's status, freezes, calendar days (rules in `backend/streak.py`) |
| GET    | `/users/{user_id}/friends?tz_offset_minutes=-240` | Friends (quests this week, minutes today, streak, level), incoming and outgoing friend requests |
| GET    | `/users/{user_id}/parties` | Group quests you host, joined or are invited to |
| POST   | `/users/{user_id}/parties` | Invite friends to a group quest: `{"friend_ids": [...], "settings": {...}}` |
| POST   | `/users/{user_id}/parties/{id}/join` · `/decline` | Answer a group quest invite (joining after it started gives you the quest too) |
| POST   | `/users/{user_id}/parties/{id}/start` | Host: generate ONE quest for everyone who joined (each gets a copy). Optional body `{location}` or `{place}` |
| DELETE | `/users/{user_id}/parties/{id}` | Host: cancel before it starts |
| POST   | `/users/{user_id}/friends/requests` | Send a friend request: `{"email": ...}` (their account email) |
| POST   | `/users/{user_id}/friends/requests/{id}/accept` · `/decline` | Answer a request sent to you |
| DELETE | `/users/{user_id}/friends/requests/{id}` · `/users/{user_id}/friends/{friend_id}` | Cancel a request you sent · unfriend |
| POST   | `/users/{user_id}/streak/freeze` | Buy a streak freeze for 100 points (409 if not enough points or already holding 2) |
| GET    | `/users/{user_id}/stats` | `{completed, generated, minutes_outside}` |
| GET / POST | `/users/{user_id}/quests/{quest_id}/logs` | Quest log: list / add a note or photo `{client_id, kind: note\|photo, text, image_base64?, mime?}` (same `client_id` again = update) |
| GET    | `/users/{user_id}/logs/{log_id}/photo` | A photo's bytes |
| DELETE | `/users/{user_id}/logs/{client_id}` | Delete a note or photo |
| POST   | `/users/{user_id}/quests/{quest_id}/feedback` | Mark completed/skipped, rate 1-5, comment |
| GET    | `/users/{user_id}/model` | Their personal model: `state` off/collecting/training/ready/failed, `version`, `reinforced`, `discouraged`, `feedback_until_retrain` |
| POST   | `/users/{user_id}/model/train` | Retrain their personal model now, in the background (202; 409 before 3 rated quests; 503 without `TINKER_API_KEY`) |

`/users/...` routes need `Authorization: Bearer <token>` (user ids look like
`u_3f2a...`). Set `AUTH_REQUIRED=false` in `.env` to allow token-less requests
for local experiments (a token for another user is still rejected).

Interactive docs: http://localhost:8000/docs (click **Authorize** and paste a token)

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Then set `GEMMA_API_KEY` in `.env` (free key: https://aistudio.google.com/apikey).
To run Gemma locally with Ollama instead, see the commented lines in `.env.example`.

## User history (`data/user_history.db`)

A second database that remembers each user's recent sidequests and how they
went, so the next one is steered by them:

- Every generated quest is added (and still added to the quest library too).
- Each user keeps their **10 most recent** quests; older ones are pruned,
  except quests with logged time, which are always kept.
- Every quest-library entry with `time_logged_minutes > 0` is copied in
  (`copied_from_library = 1`): all of them on startup, and immediately when
  feedback logs time on a quest that had already dropped out of the last 10.
- The last 10 go to Gemma grouped as *loved* (4-5 stars), *disliked*
  (1-2 stars), *rated OK*, *skipped* and *not done yet*. Gemma must not repeat
  any of them, and a new quest that is too close to a disliked one (same
  category + 2 shared tags, or the same title) is rejected and regenerated.

Table `user_quest_history`: user_id, app_quest_id, title, quest_text,
category, duration_minutes, difficulty, tags, quest_json, model, status,
completed, rating, feedback_comment, time_logged_minutes, created_at,
feedback_at, copied_from_library. Git-ignored (user data).

## Example-quest library

Gemma gets the 3 example quests most similar to the user's profile.

**Local (default)** - `data/quest_library.db` is created and seeded
automatically when the backend starts (30 quests from `tiger/seed_quests.json`).
It is git-ignored because it also stores users' generated quests and feedback. Embeddings come from
[WordLlama](https://github.com/dleemiller/WordLlama) (256 dims), which runs
offline with its weights bundled in the pip package - no API key needed.
Ranking = cosine similarity + a small boost for category/tag matches with the
user's interests, with quests that fit the time budget first.

The same `quests` table also stores **every generated sidequest** and its
feedback:

| column | seeded quests | generated quests |
|---|---|---|
| `quest_text`, `category`, `duration_minutes`, `difficulty`, `tags`, `embedding` | from the seed file | title + summary, first interest tag, estimated minutes, ... |
| `source` | `seed` | `generated` |
| `time_logged_minutes` | `0` | `0` until feedback, then minutes the user logged |
| `user_id`, `app_quest_id`, `title`, `quest_json`, `model` | - | set on generation |
| `status`, `completed`, `rating`, `feedback_comment`, `feedback_at` | - | set when feedback is sent |

Generated quests that were completed and rated 4+ become retrieval examples too.
Older library files are migrated automatically on startup (rows are kept).

Re-seed after editing `tiger/seed_quests.json` (generated rows are left alone):

```powershell
python -m backend.library
```

### Tiger Data (optional)

Setting `TIGER_DATABASE_URL` switches retrieval to Tiger Data instead.

1. Create a Tiger Data service and copy its connection string.
2. In `.env`, set `TIGER_DATABASE_URL=<connection string>`.
3. Create the table and load the 30 example quests (`tiger/seed_quests.json`):

   ```powershell
   python -m tiger.seed           # creates table + HNSW index, embeds and upserts
   python -m tiger.seed --check   # verify connection / row count
   ```

   Or run `tiger/schema.sql` in the Tiger console first and use `--skip-schema`.
   Re-running the seed is safe (upserts on `quest_text`).

Table: `quests(id, quest_text, category, duration_minutes, difficulty, tags text[], embedding vector(768), created_at)`

## Monitoring with Sentry (optional)

`backend/observability.py` sends errors, request traces and a record of every
Gemma call to [Sentry](https://sentry.io) - useful for the slow/timed-out Gemma
answers. Create a Python (FastAPI) project in Sentry, then add to `.env`:

```
SENTRY_DSN=https://...@o123.ingest.sentry.io/456
SENTRY_ENVIRONMENT=development        # or production
SENTRY_TRACES_SAMPLE_RATE=1.0         # optional (default 1.0)
SENTRY_SEND_PROMPTS=false             # true = attach prompts/answers to spans (contain preferences + location)
```

What shows up (nothing is sent without `SENTRY_DSN`):

- **Traces / AI insights**: each `POST /users/{id}/quests` -> `quest.generate` span ->
  one `gen_ai.chat` span per Gemma attempt with duration, input/output/reasoning
  tokens, finish reason, outcome (`ok`, `rejected`, `timeout`, `error`) and why it
  was rejected (`invalid_json`, `too_long`, `too_short`, `indoor`, `repeat`,
  `similar_to_disliked`, `taste_conflict`). Weather/places/SerpApi calls appear as
  HTTP spans in the same trace.
- **Issues**: one event per quest that couldn't be generated (`quest-generation-failed`,
  grouped by `failed` / `timeout`) with every attempt in the `quest_generation`
  context; plus any unhandled error.
- **Metrics**: `gemma.call.duration`, `gemma.tokens.input|output|reasoning`,
  `gemma.attempts`, `gemma.rejections` (by `reason`), `gemma.timeouts`,
  `quest.generate.duration`.
- Only the account id is attached as the user (no emails, IPs or headers).

The backend log prints the same per-attempt line even without Sentry:
`gemma attempt 2: rejected in 41.3s (tokens in/out/reasoning 2900/1650/1200; rejected for indoor)`.

## Run

Two terminals (activate the venv in each):

```powershell
uvicorn backend.main:app --reload     # backend on http://localhost:8000
streamlit run app.py                  # UI on http://localhost:8501
```

## Test

```powershell
pytest
```

pgvector tests are skipped unless `TEST_PG_URL` points at a Postgres with the
`vector` extension (they create and drop a `quests_test` table).

## Mobile app (Flutter)

`mobile/` is the Flutter app: sign up / log in against the backend, then a
bottom bar with Quest generator, History (+ quest detail) and Account (+ edit
account). It's offline-first - the session, profile and quest history are
stored on the device and ratings/preference edits made offline sync later.
See `mobile/README.md`.
