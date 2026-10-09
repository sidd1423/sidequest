# sidequest

Suggests "sidequests" that fit a user's interests, time, energy and constraints.

## Architecture

```
Streamlit UI (app.py)  ──HTTP/JSON──▶  FastAPI backend (backend/)  ──▶  SQLite (sidequest.db)
        │                                      │
        │                                      └──▶  Gemma via inference API (backend/llm.py)
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
