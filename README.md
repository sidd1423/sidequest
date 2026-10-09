# sidequest

Suggests "sidequests" that fit a user's interests, time, energy and constraints.

## Architecture

```
Streamlit UI (app.py)  ──HTTP/JSON──▶  FastAPI backend (backend/)  ──▶  SQLite (sidequest.db)
        │                                      │
        └──────── shared Pydantic schema (backend/schemas.py) ────────┘
```

- **Frontend** `app.py`: preference form (interests, available time, difficulty,
  energy, accessibility, environment, weather). Validates input with the
  shared schema, then sends it to the backend via `frontend/api_client.py`.
- **Backend** `backend/main.py`: REST API that validates and stores preferences.
- **Storage** `backend/db.py`: one JSON document per user in SQLite. Swap this
  module for Postgres later without touching the API or UI.

### API

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/health` | Health check |
| GET    | `/users/{user_id}/preferences` | Fetch saved preferences (404 if none) |
| PUT    | `/users/{user_id}/preferences` | Create or update preferences |
| DELETE | `/users/{user_id}/preferences` | Delete preferences |

Interactive docs: http://localhost:8000/docs

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

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
