"""Accounts and sessions (email + password, bearer tokens).

- Passwords are hashed with PBKDF2-SHA256 (stdlib, salted, 600k iterations
  by default - set PASSWORD_HASH_ITERATIONS lower only for tests).
- Logging in returns a random session token. Only its SHA-256 hash is stored,
  so a leaked database doesn't leak working tokens.
- Sessions are long-lived (SESSION_DAYS, default 90) because the mobile app
  is offline-first: it keeps the token on the device and keeps working
  without a connection, then syncs when it's back online.
- Tables live in the main DATABASE_PATH database next to preferences/quests.

AUTH_REQUIRED (default true): when false, requests without a token are still
allowed on /users/{id}/... (handy for local Streamlit/dev use). A token for
a *different* user is always rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db
from .schemas import USER_ID_PATTERN

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL DEFAULT '',
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
"""

MIN_PASSWORD_LENGTH = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def init_auth() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _iterations() -> int:
    return int(os.getenv("PASSWORD_HASH_ITERATIONS", "600000"))


def _session_days() -> int:
    return int(os.getenv("SESSION_DAYS", "90"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Passwords & tokens
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    iterations = _iterations()
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

def _clean_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_RE.match(value) or len(value) > 254:
        raise ValueError("Enter a valid email address")
    return value


class SignUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field("", max_length=80)
    email: str
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _clean_email(v)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class LogInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str = Field(..., max_length=256)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=80)
    email: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return None if v is None else _clean_email(v)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime


class SessionOut(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _user_from_row(row: sqlite3.Row) -> UserOut:
    return UserOut(id=row["id"], email=row["email"], name=row["name"], created_at=row["created_at"])


def create_user(data: SignUpIn) -> UserOut:
    user_id = "u_" + secrets.token_hex(8)  # matches USER_ID_PATTERN
    created = _now().isoformat()
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO users (id, email, name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, data.email, data.name, hash_password(data.password), created),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from exc
    return UserOut(id=user_id, email=data.email, name=data.name, created_at=created)


def authenticate(email: str, password: str) -> UserOut | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        hash_password(password)  # same work either way, so timing doesn't reveal which emails exist
        return None
    return _user_from_row(row) if verify_password(password, row["password_hash"]) else None


def get_user(user_id: str) -> UserOut | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_from_row(row) if row else None


def update_user(user_id: str, changes: AccountUpdate) -> UserOut:
    fields = changes.model_dump(exclude_none=True)
    if "name" in fields:
        fields["name"] = fields["name"].strip()
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        try:
            with db.connect() as conn:
                conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), user_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from exc
    user = get_user(user_id)
    assert user is not None
    return user


def create_session(user: UserOut) -> SessionOut:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=_session_days())
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_hash_token(token), user.id, now.isoformat(), expires.isoformat()),
        )
    return SessionOut(token=token, expires_at=expires, user=user)


def user_for_token(token: str) -> UserOut | None:
    with db.connect() as conn:
        row = conn.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (_hash_token(token), _now().isoformat()),
        ).fetchone()
    return _user_from_row(row) if row else None


def delete_session(token: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)

UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "Log in again - your session is missing or has expired",
    headers={"WWW-Authenticate": "Bearer"},
)


def optional_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> UserOut | None:
    """The logged-in user, None if no token was sent. A bad/expired token is a 401."""
    if creds is None:
        return None
    user = user_for_token(creds.credentials)
    if user is None:
        raise UNAUTHORIZED
    return user


def current_user(user: UserOut | None = Depends(optional_user)) -> UserOut:
    if user is None:
        raise UNAUTHORIZED
    return user


def current_token(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if creds is None:
        raise UNAUTHORIZED
    return creds.credentials


def authorized_user_id(
    user_id: str = Path(..., pattern=USER_ID_PATTERN, description="3-64 chars: letters, digits, _ . @ -"),
    user: UserOut | None = Depends(optional_user),
) -> str:
    """Guard for /users/{user_id}/...: you can only touch your own data."""
    if user is None:
        if auth_required():
            raise UNAUTHORIZED
        return user_id  # dev mode (AUTH_REQUIRED=false)
    if user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only access your own data")
    return user_id
