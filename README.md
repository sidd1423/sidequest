# sidequest

Suggests "sidequests" that fit a user's interests, time, energy and constraints.

## Architecture

```
Streamlit UI (app.py)  ──HTTP/JSON──▶  FastAPI backend (backend/)  ──▶  SQLite (sidequest.db)
        │                                      │
        │                                      ├──▶  Gemma via inference API (backend/llm.py)
        │                                      └──▶  Example-quest library: local SQLite (backend/library.py)
        │                                                 or Tiger Data pgvector (backend/retrieval.py)
        └──────── shared Pydantic schema (backend/schemas.py) ────────┘
```

- **Frontend** `app.py`: preference form (interests, available time, difficulty,
  energy, accessibility, environment, weather). Validates input with the
  shared schema, then sends it to the backend via `frontend/api_client.py`.
- **Backend** `backend/main.py`: REST API that validates and stores preferences.
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

### API

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/health` | Health check |
| GET    | `/users/{user_id}/preferences` | Fetch saved preferences (404 if none) |
| PUT    | `/users/{user_id}/preferences` | Create or update preferences |
| DELETE | `/users/{user_id}/preferences` | Delete preferences |
| POST   | `/users/{user_id}/quests` | Generate a new sidequest with Gemma |
| GET    | `/users/{user_id}/quests` | List the user's quests, newest first |
| POST   | `/users/{user_id}/quests/{quest_id}/feedback` | Mark completed/skipped, rate 1-5, comment |

Interactive docs: http://localhost:8000/docs

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Then set `GEMMA_API_KEY` in `.env` (free key: https://aistudio.google.com/apikey).
To run Gemma locally with Ollama instead, see the commented lines in `.env.example`.

## Example-quest library

Gemma gets the 3 example quests most similar to the user's profile.

**Local (default)** - `data/quest_library.db` ships with the repo, pre-seeded
with the 30 quests in `tiger/seed_quests.json`. Embeddings come from
[WordLlama](https://github.com/dleemiller/WordLlama) (256 dims), which runs
offline with its weights bundled in the pip package - no API key needed.
Ranking = cosine similarity + a small boost for category/tag matches with the
user's interests, with quests that fit the time budget first.

Re-seed after editing `tiger/seed_quests.json`:

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
