"""Thin HTTP client the Streamlit app uses to talk to the backend."""

from __future__ import annotations

import os
import threading
from typing import Any

import requests

from backend.schemas import PreferencesIn

TIMEOUT = 5


class BackendError(Exception):
    """Raised when the backend can't be reached or rejects a request."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# The logged-in user's session token. Streamlit runs each browser session's
# script in its own thread, so a thread-local keeps sessions apart; app.py
# calls set_token() at the top of every run.
_local = threading.local()


def set_token(token: str | None) -> None:
    _local.token = token


def _auth_headers() -> dict[str, str]:
    token = getattr(_local, "token", None)
    return {"Authorization": f"Bearer {token}"} if token else {}


def base_url() -> str:
    return os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def _detail(resp: requests.Response) -> str:
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(f"{'.'.join(map(str, e.get('loc', [])))}: {e.get('msg')}" for e in detail)
    return f"{resp.status_code}: {detail}"


def _request(method: str, path: str, timeout: float = TIMEOUT, **kwargs: Any) -> requests.Response:
    headers = {**_auth_headers(), **kwargs.pop("headers", {})}
    try:
        return requests.request(method, f"{base_url()}{path}", timeout=timeout, headers=headers, **kwargs)
    except requests.RequestException as exc:
        raise BackendError(f"Can't reach the backend at {base_url()} ({exc.__class__.__name__})") from exc


def is_healthy() -> bool:
    try:
        return _request("GET", "/health").ok
    except BackendError:
        return False


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def sign_up(name: str, email: str, password: str) -> dict:
    resp = _request("POST", "/auth/signup", json={"name": name, "email": email, "password": password})
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()


def log_in(email: str, password: str) -> dict:
    resp = _request("POST", "/auth/login", json={"email": email, "password": password})
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()


def log_out() -> None:
    try:
        _request("POST", "/auth/logout")
    except BackendError:
        pass  # the local session is cleared either way


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def get_preferences(user_id: str) -> dict | None:
    resp = _request("GET", f"/users/{user_id}/preferences")
    if resp.status_code == 404:
        return None
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()


def save_preferences(user_id: str, prefs: PreferencesIn) -> dict:
    resp = _request(
        "PUT",
        f"/users/{user_id}/preferences",
        data=prefs.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()


# ---------------------------------------------------------------------------
# Quests
# ---------------------------------------------------------------------------

GENERATE_TIMEOUT = 360  # backend gives Gemma up to GEMMA_TIME_BUDGET (300s) incl. retries


def generate_quest(user_id: str, place: str = "") -> dict:
    """place: where the user is ("Riverdale, Toronto") - the backend looks up the
    weather and nearby spots there. Empty = no location."""
    body = {"place": place.strip()[:120]} if place.strip() else None
    resp = _request("POST", f"/users/{user_id}/quests", timeout=GENERATE_TIMEOUT, json=body)
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()


def list_quests(user_id: str, limit: int = 20) -> list[dict]:
    resp = _request("GET", f"/users/{user_id}/quests", params={"limit": limit})
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()


def send_feedback(
    user_id: str,
    quest_id: int,
    completed: bool,
    rating: int | None,
    comment: str,
    time_logged_minutes: int | None = None,
) -> dict:
    resp = _request(
        "POST",
        f"/users/{user_id}/quests/{quest_id}/feedback",
        json={"completed": completed, "rating": rating, "comment": comment,
              "time_logged_minutes": time_logged_minutes},
    )
    if not resp.ok:
        raise BackendError(_detail(resp), resp.status_code)
    return resp.json()
