"""Thin HTTP client the Streamlit app uses to talk to the backend."""

from __future__ import annotations

import os
from typing import Any

import requests

from backend.schemas import PreferencesIn

TIMEOUT = 5


class BackendError(Exception):
    """Raised when the backend can't be reached or rejects a request."""


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


def _request(method: str, path: str, **kwargs: Any) -> requests.Response:
    try:
        return requests.request(method, f"{base_url()}{path}", timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise BackendError(f"Can't reach the backend at {base_url()} ({exc.__class__.__name__})") from exc


def is_healthy() -> bool:
    try:
        return _request("GET", "/health").ok
    except BackendError:
        return False


def get_preferences(user_id: str) -> dict | None:
    resp = _request("GET", f"/users/{user_id}/preferences")
    if resp.status_code == 404:
        return None
    if not resp.ok:
        raise BackendError(_detail(resp))
    return resp.json()


def save_preferences(user_id: str, prefs: PreferencesIn) -> dict:
    resp = _request(
        "PUT",
        f"/users/{user_id}/preferences",
        data=prefs.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    if not resp.ok:
        raise BackendError(_detail(resp))
    return resp.json()
