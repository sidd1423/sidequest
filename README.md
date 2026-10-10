# sidequest

Sidequests are quick **5-30 minute things to do outside, right now** - small,
low-friction nudges to get people out of the house more often. The app tailors
each one to the user's interests, how much time they have, their energy,
accessibility needs, what's around them and the weather they want to avoid.

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
  now (5-30), difficulty, energy, accessibility, surroundings / how far to go,
  crowds, group, weather). Validates input with the
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

Gemma itself isn't retrained - it's personalised through the prompt every
time.
The backend log prints the learned taste on each generation.

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
| POST   | `/users/{user_id}/quests` | Generate a new sidequest with Gemma. Optional body `{duration_minutes, group_size, difficulty, energy_level, max_travel_km}` overrides the profile for this quest |
| GET    | `/users/{user_id}/quests` | List the user's quests, newest first |
| GET    | `/users/{user_id}/rewards` | Points, level, streaks, badges and recent points (rules in `backend/rewards.py`) |
| GET    | `/users/{user_id}/streak?tz_offset_minutes=-240` | Duolingo-style daily streak: current/best, today's status, freezes, calendar days (rules in `backend/streak.py`) |
| POST   | `/users/{user_id}/streak/freeze` | Buy a streak freeze for 100 points (409 if not enough points or already holding 2) |
| GET    | `/users/{user_id}/stats` | `{completed, generated, minutes_outside}` |
| GET / POST | `/users/{user_id}/quests/{quest_id}/logs` | Quest log: list / add a note or photo `{client_id, kind: note\|photo, text, image_base64?, mime?}` (same `client_id` again = update) |
| GET    | `/users/{user_id}/logs/{log_id}/photo` | A photo's bytes |
| DELETE | `/users/{user_id}/logs/{client_id}` | Delete a note or photo |
| POST   | `/users/{user_id}/quests/{quest_id}/feedback` | Mark completed/skipped, rate 1-5, comment |

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
