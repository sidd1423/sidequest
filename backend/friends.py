"""Friends: send a request by email, the other person accepts.

One row per pair in `friendships` (sidequest.db):
  requester_id -> addressee_id, status 'pending' | 'accepted'.
Declining or cancelling a request, and unfriending, delete the row, so the
same people can ask again later.
If you send a request to someone who already asked you, it's accepted
straight away.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator

from . import auth, db

log = logging.getLogger("sidequest.friends")

SCHEMA = """
CREATE TABLE IF NOT EXISTS friendships (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id  TEXT NOT NULL,
    addressee_id  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    accepted_at   TEXT,
    UNIQUE (requester_id, addressee_id)
);
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships (addressee_id);
"""


def init_friends() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FriendRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return auth._clean_email(v)


class Person(BaseModel):
    user_id: str
    name: str
    email: str


class Friend(Person):
    since: datetime
    completed: int = 0  # quests completed
    points: int = 0
    level_name: str = ""
    current_streak: int = 0


class FriendRequest(BaseModel):
    request_id: int
    person: Person  # the other person
    created_at: datetime


class FriendsOut(BaseModel):
    friends: list[Friend]
    incoming: list[FriendRequest]  # waiting for you to accept
    outgoing: list[FriendRequest]  # you asked, waiting for them


class RequestResult(BaseModel):
    status: str  # 'pending' | 'accepted'
    request_id: int
    person: Person


def _person(user_id: str) -> Person | None:
    user = auth.get_user(user_id)
    return Person(user_id=user.id, name=user.name, email=user.email) if user else None


def _summary(person: Person, since: str) -> Friend:
    friend = Friend(**person.model_dump(), since=since)
    try:  # best effort - a friend's stats never break the list
        from . import rewards

        friend.completed = db.quest_stats(person.user_id)["completed"]
        r = rewards.compute(person.user_id)
        friend.points, friend.level_name, friend.current_streak = r.points, r.level_name, r.current_streak
    except Exception as exc:
        log.warning("Couldn't load stats for friend %s: %s", person.user_id, exc)
    return friend


def _pair(conn, a: str, b: str):
    return conn.execute(
        """SELECT * FROM friendships WHERE (requester_id = ? AND addressee_id = ?)
           OR (requester_id = ? AND addressee_id = ?)""",
        (a, b, b, a),
    ).fetchone()


def send_request(user_id: str, email: str) -> RequestResult:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "There's no Sidequest account with that email")
        other = row["id"]
        if other == user_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That's your own email")
        existing = _pair(conn, user_id, other)
        if existing is not None:
            if existing["status"] == "accepted":
                raise HTTPException(status.HTTP_409_CONFLICT, "You're already friends")
            if existing["requester_id"] == user_id:
                raise HTTPException(status.HTTP_409_CONFLICT, "You already sent them a friend request")
            # They already asked you - asking back means yes.
            conn.execute("UPDATE friendships SET status = 'accepted', accepted_at = ? WHERE id = ?",
                         (_now(), existing["id"]))
            request_id, state = existing["id"], "accepted"
        else:
            cur = conn.execute(
                "INSERT INTO friendships (requester_id, addressee_id, created_at) VALUES (?, ?, ?)",
                (user_id, other, _now()),
            )
            request_id, state = cur.lastrowid, "pending"
    return RequestResult(status=state, request_id=request_id, person=_person(other))


def _request_for(conn, request_id: int, column: str, user_id: str):
    row = conn.execute(
        f"SELECT * FROM friendships WHERE id = ? AND {column} = ? AND status = 'pending'",
        (request_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Friend request not found")
    return row


def respond(user_id: str, request_id: int, accept: bool) -> None:
    """Accept or decline a request sent TO you."""
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        _request_for(conn, request_id, "addressee_id", user_id)
        if accept:
            conn.execute("UPDATE friendships SET status = 'accepted', accepted_at = ? WHERE id = ?",
                         (_now(), request_id))
        else:
            conn.execute("DELETE FROM friendships WHERE id = ?", (request_id,))


def cancel(user_id: str, request_id: int) -> None:
    """Take back a request YOU sent."""
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        _request_for(conn, request_id, "requester_id", user_id)
        conn.execute("DELETE FROM friendships WHERE id = ?", (request_id,))


def remove(user_id: str, friend_id: str) -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        row = _pair(conn, user_id, friend_id)
        if row is None or row["status"] != "accepted":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "You're not friends with this person")
        conn.execute("DELETE FROM friendships WHERE id = ?", (row["id"],))


def list_for(user_id: str) -> FriendsOut:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            "SELECT * FROM friendships WHERE requester_id = ? OR addressee_id = ? ORDER BY created_at",
            (user_id, user_id),
        ).fetchall()
    friends: list[Friend] = []
    incoming: list[FriendRequest] = []
    outgoing: list[FriendRequest] = []
    for r in rows:
        other = r["addressee_id"] if r["requester_id"] == user_id else r["requester_id"]
        person = _person(other)
        if person is None:  # account gone
            continue
        if r["status"] == "accepted":
            friends.append(_summary(person, r["accepted_at"] or r["created_at"]))
        elif r["requester_id"] == user_id:
            outgoing.append(FriendRequest(request_id=r["id"], person=person, created_at=r["created_at"]))
        else:
            incoming.append(FriendRequest(request_id=r["id"], person=person, created_at=r["created_at"]))
    friends.sort(key=lambda f: (f.name or f.email).lower())
    return FriendsOut(friends=friends, incoming=incoming, outgoing=outgoing)


def delete_user(user_id: str) -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM friendships WHERE requester_id = ? OR addressee_id = ?", (user_id, user_id))
