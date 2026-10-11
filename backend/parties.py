"""Group quests ("parties"): invite friends first, generate the quest later.

1. The host invites friends (POST /users/{id}/parties) with this quest's
   settings. Only accepted friends can be invited.
2. Friends join or decline (.../parties/{pid}/join | decline).
3. The host starts it (.../parties/{pid}/start) once at least one friend has
   joined: ONE quest is generated for exactly that many people, and everyone
   who joined gets their own copy (own rating, quest log, streak).
4. Someone still "invited" can join after the start and gets a copy too.
   The quest card shows who's in (joined / invited / declined).

Tables in sidequest.db: parties, party_members.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from . import auth, db
from .schemas import PartyMemberTag, PartyTag, Quest, QuestRecord, QuestSettings

MAX_INVITES = 7  # host + 7 friends
SHOW_STARTED_FOR = timedelta(hours=24)  # started parties stay in GET /parties this long

SCHEMA = """
CREATE TABLE IF NOT EXISTS parties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | started
    settings    TEXT,                           -- QuestSettings JSON
    quest_json  TEXT,                           -- the generated quest (for late joiners)
    size        INTEGER,                        -- people it was generated for
    created_at  TEXT NOT NULL,
    started_at  TEXT
);
CREATE TABLE IF NOT EXISTS party_members (
    party_id      INTEGER NOT NULL,
    user_id       TEXT NOT NULL,
    status        TEXT NOT NULL,                -- invited | joined | declined
    quest_id      INTEGER,                      -- their copy in quests
    responded_at  TEXT,
    PRIMARY KEY (party_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_party_members_user ON party_members (user_id);
CREATE INDEX IF NOT EXISTS idx_party_members_quest ON party_members (quest_id);
"""


def init_parties() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PartyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    friend_ids: list[str] = Field(..., min_length=1, max_length=MAX_INVITES)
    settings: QuestSettings | None = None


class PartyMember(BaseModel):
    user_id: str
    name: str
    email: str
    status: str  # invited | joined | declined
    is_host: bool = False


class PartyOut(BaseModel):
    id: int
    host_id: str
    host_name: str
    status: str  # open | started
    created_at: datetime
    started_at: datetime | None = None
    members: list[PartyMember]  # host first
    joined: int  # people in (host included)
    size: int | None = None  # people the quest was made for (once started)
    my_status: str  # host | invited | joined | declined
    my_quest_id: int | None = None  # your copy of the quest (once started and joined)
    quest_title: str | None = None
    settings: QuestSettings | None = None


def _name(user: auth.UserOut) -> str:
    return user.name or user.email


def _load(conn, party_id: int, viewer: str) -> PartyOut | None:
    p = conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
    if p is None:
        return None
    rows = conn.execute("SELECT * FROM party_members WHERE party_id = ?", (party_id,)).fetchall()
    members: list[PartyMember] = []
    mine = None
    for r in rows:
        user = auth.get_user(r["user_id"])
        if user is None:  # account deleted
            continue
        members.append(PartyMember(user_id=user.id, name=_name(user), email=user.email, status=r["status"],
                                   is_host=user.id == p["host_id"]))
        if r["user_id"] == viewer:
            mine = r
    if mine is None:
        return None
    members.sort(key=lambda m: (not m.is_host, m.name.lower()))
    host = next((m for m in members if m.is_host), None)
    quest = Quest.model_validate_json(p["quest_json"]) if p["quest_json"] else None
    return PartyOut(
        id=p["id"],
        host_id=p["host_id"],
        host_name=host.name if host else "",
        status=p["status"],
        created_at=p["created_at"],
        started_at=p["started_at"],
        members=members,
        joined=sum(m.status == "joined" for m in members),
        size=p["size"],
        my_status="host" if viewer == p["host_id"] else mine["status"],
        my_quest_id=mine["quest_id"],
        quest_title=quest.title if quest else None,
        settings=QuestSettings.model_validate_json(p["settings"]) if p["settings"] else None,
    )


def get(party_id: int, viewer: str) -> PartyOut:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        party = _load(conn, party_id, viewer)
    if party is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group quest not found")
    return party


def _are_friends(conn, a: str, b: str) -> bool:
    from . import friends

    conn.executescript(friends.SCHEMA)
    return conn.execute(
        """SELECT 1 FROM friendships WHERE status = 'accepted' AND
           ((requester_id = ? AND addressee_id = ?) OR (requester_id = ? AND addressee_id = ?))""",
        (a, b, b, a),
    ).fetchone() is not None


def create(host_id: str, data: PartyIn) -> PartyOut:
    invitees = list(dict.fromkeys(i for i in data.friend_ids if i != host_id))
    if not invitees:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invite at least one friend")
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        for friend_id in invitees:
            if not _are_friends(conn, host_id, friend_id):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "You can only invite people who are your friends")
        cur = conn.execute(
            "INSERT INTO parties (host_id, settings, created_at) VALUES (?, ?, ?)",
            (host_id, data.settings.model_dump_json() if data.settings else None, _now()),
        )
        pid = cur.lastrowid
        conn.execute("INSERT INTO party_members (party_id, user_id, status, responded_at) VALUES (?, ?, 'joined', ?)",
                     (pid, host_id, _now()))
        conn.executemany("INSERT INTO party_members (party_id, user_id, status) VALUES (?, ?, 'invited')",
                         [(pid, f) for f in invitees])
    return get(pid, host_id)


def list_for(user_id: str) -> list[PartyOut]:
    """Open group quests you're in (or invited to), plus ones started in the last day.
    Ones you declined are left out."""
    since = (datetime.now(timezone.utc) - SHOW_STARTED_FOR).isoformat()
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        ids = [r[0] for r in conn.execute(
            """SELECT p.id FROM parties p JOIN party_members m ON m.party_id = p.id
               WHERE m.user_id = ? AND m.status != 'declined'
                 AND (p.status = 'open' OR p.started_at >= ?)
               ORDER BY p.created_at DESC""",
            (user_id, since),
        )]
        parties = [_load(conn, pid, user_id) for pid in ids]
    return [p for p in parties if p is not None]


def _member(conn, party_id: int, user_id: str):
    party = conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
    row = conn.execute("SELECT * FROM party_members WHERE party_id = ? AND user_id = ?",
                       (party_id, user_id)).fetchone()
    if party is None or row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group quest not found")
    return party, row


def respond(user_id: str, party_id: int, join: bool) -> tuple[PartyOut, str | None, int | None]:
    """Join or decline an invite. Returns (party, quest_json to copy, size) when
    joining a group quest that already started, so the caller stores your copy."""
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        party, row = _member(conn, party_id, user_id)
        if party["host_id"] == user_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You're the host of this group quest")
        if row["status"] != "invited":
            raise HTTPException(status.HTTP_409_CONFLICT, f"You already {row['status']} this group quest")
        conn.execute("UPDATE party_members SET status = ?, responded_at = ? WHERE party_id = ? AND user_id = ?",
                     ("joined" if join else "declined", _now(), party_id, user_id))
        late = join and party["status"] == "started"
    return get(party_id, user_id), (party["quest_json"] if late else None), party["size"]


def set_quest_id(party_id: int, user_id: str, quest_id: int) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE party_members SET quest_id = ? WHERE party_id = ? AND user_id = ?",
                     (quest_id, party_id, user_id))


def check_can_start(host_id: str, party_id: int) -> tuple[list[str], QuestSettings | None]:
    """(people who joined, host first; the quest settings) - or an HTTP error."""
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        party, _ = _member(conn, party_id, host_id)
        if party["host_id"] != host_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the host can start the group quest")
        if party["status"] != "open":
            raise HTTPException(status.HTTP_409_CONFLICT, "This group quest already started")
        joined = [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM party_members WHERE party_id = ? AND status = 'joined'", (party_id,))]
    if len(joined) < 2:
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait until at least one friend has joined")
    joined.sort(key=lambda u: u != host_id)
    settings = QuestSettings.model_validate_json(party["settings"]) if party["settings"] else None
    return joined, settings


def mark_started(party_id: int, quest: Quest, size: int) -> bool:
    """Record the generated quest. False if someone else started it meanwhile."""
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE parties SET status = 'started', quest_json = ?, size = ?, started_at = ? "
            "WHERE id = ? AND status = 'open'",
            (quest.model_dump_json(), size, _now(), party_id),
        )
        return cur.rowcount == 1


def cancel(host_id: str, party_id: int) -> None:
    """The host calls it off (only before it starts)."""
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        party, _ = _member(conn, party_id, host_id)
        if party["host_id"] != host_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the host can cancel the group quest")
        if party["status"] != "open":
            raise HTTPException(status.HTTP_409_CONFLICT, "This group quest already started")
        conn.execute("DELETE FROM party_members WHERE party_id = ?", (party_id,))
        conn.execute("DELETE FROM parties WHERE id = ?", (party_id,))


def attach(records: list[QuestRecord]) -> list[QuestRecord]:
    """Fill QuestRecord.party for quests that belong to a group quest."""
    ids = [r.id for r in records]
    if not ids:
        return records
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        marks = ",".join("?" * len(ids))
        links = {row["quest_id"]: row["party_id"] for row in conn.execute(
            f"SELECT quest_id, party_id FROM party_members WHERE quest_id IN ({marks})", ids)}
        tags: dict[int, PartyTag] = {}
        for pid in set(links.values()):
            p = conn.execute("SELECT * FROM parties WHERE id = ?", (pid,)).fetchone()
            members = []
            for r in conn.execute("SELECT user_id, status FROM party_members WHERE party_id = ?", (pid,)):
                user = auth.get_user(r["user_id"])
                if user is not None:
                    members.append(PartyMemberTag(user_id=user.id, name=_name(user), status=r["status"]))
            members.sort(key=lambda m: (m.user_id != p["host_id"], m.name.lower()))
            tags[pid] = PartyTag(party_id=pid, host_id=p["host_id"], size=p["size"] or len(members),
                                 members=members)
    for r in records:
        if r.id in links:
            r.party = tags[links[r.id]]
    return records


def delete_user(user_id: str) -> None:
    """Account deletion: leave every party; parties you host that haven't started go away."""
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        hosted = [r[0] for r in conn.execute(
            "SELECT id FROM parties WHERE host_id = ? AND status = 'open'", (user_id,))]
        for pid in hosted:
            conn.execute("DELETE FROM party_members WHERE party_id = ?", (pid,))
            conn.execute("DELETE FROM parties WHERE id = ?", (pid,))
        conn.execute("DELETE FROM party_members WHERE user_id = ?", (user_id,))
