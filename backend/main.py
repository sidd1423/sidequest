"""Sidequest backend API.

Run with:  uvicorn backend.main:app --reload
Docs at:   http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, status

from . import db
from .schemas import USER_ID_PATTERN, PreferencesIn, PreferencesOut

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
