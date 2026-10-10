"""User history database (data/user_history.db) and how it steers generation."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from backend import history
from backend.quest_generator import build_prompt, generate_quest, too_similar_to_disliked
from backend.schemas import FeedbackIn, PastQuest, PreferencesIn, Quest

from .test_api import VALID
from .test_quests import DIFFERENT_QUEST, QUEST, FakeLLM

PROFILE = PreferencesIn.model_validate(VALID)


def q(title, tags=("nature", "photography"), **over):
    return Quest.model_validate({**QUEST, "title": title, "tags": list(tags), **over})


def rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("select * from user_quest_history order by id")]
    finally:
        conn.close()


@pytest.fixture()
def hpath(tmp_path):
    return tmp_path / "user_history.db"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def test_keeps_last_10_per_user(hpath):
    for i in range(1, 13):
        history.add_quest(i, "gowtham", q(f"Quest number {i}"), path=hpath)
    history.add_quest(100, "someone_else", q("Other user's quest"), path=hpath)

    recent = history.recent("gowtham", path=hpath)
    assert [p.title for p in recent] == [f"Quest number {i}" for i in range(12, 2, -1)]
    assert len(history.recent("someone_else", path=hpath)) == 1


def test_quests_with_logged_time_are_never_pruned(hpath):
    history.add_quest(1, "u1", q("The one I did"), path=hpath)
    history.record_feedback(1, FeedbackIn(completed=True, rating=5, time_logged_minutes=12), path=hpath)
    for i in range(2, 15):
        history.add_quest(i, "u1", q(f"Later quest {i}"), path=hpath)
    titles = {r["title"] for r in rows(hpath)}
    assert "The one I did" in titles
    assert len([r for r in rows(hpath) if r["time_logged_minutes"] == 0]) == 10


def test_feedback_updates_row(hpath):
    history.add_quest(5, "u1", q("Rate me"), path=hpath)
    assert history.record_feedback(5, FeedbackIn(completed=True, rating=1, comment="boring",
                                                 time_logged_minutes=9), path=hpath)
    [p] = history.recent("u1", path=hpath)
    assert (p.status.value, p.rating, p.comment, p.time_logged_minutes, p.disliked) == \
        ("completed", 1, "boring", 9, True)
    assert history.record_feedback(999, FeedbackIn(completed=False), path=hpath) is False


def test_backfills_logged_entries_from_quest_library(tmp_path, hpath):
    from backend import library

    lib = tmp_path / "lib.db"
    library.init_library(lib)
    library.add_generated(1, "gowtham", q("Done with time"), path=lib)
    library.add_generated(2, "gowtham", q("Never done"), path=lib)
    library.add_generated(3, "maya", q("Skipped one"), path=lib)
    library.record_feedback(1, FeedbackIn(completed=True, rating=4, time_logged_minutes=22), path=lib)
    library.record_feedback(3, FeedbackIn(completed=False), path=lib)

    assert history.init_history(hpath, library_db=lib) == 1
    [r] = rows(hpath)
    assert (r["title"], r["user_id"], r["time_logged_minutes"], r["rating"], r["copied_from_library"]) == \
        ("Done with time", "gowtham", 22, 4, 1)
    assert json.loads(r["quest_json"])["title"] == "Done with time"

    assert history.init_history(hpath, library_db=lib) == 0  # idempotent
    assert len(rows(hpath)) == 1


def test_backfill_from_old_format_library_is_a_noop(hpath):
    old = Path(__file__).parent / "fixtures" / "old_format_library.db"
    assert history.init_history(hpath, library_db=old) == 0


# ---------------------------------------------------------------------------
# Steering generation
# ---------------------------------------------------------------------------

def past(title, tags=("nature", "photography"), category="nature", **over):
    base = dict(title=title, quest_text=f"{title}: ...", category=category, duration_minutes=15,
                difficulty="easy", tags=list(tags), status="suggested")
    return PastQuest(**{**base, **over})


LOVED = past("Sunrise Puddle Photos", status="completed", completed=True, rating=5, time_logged_minutes=14)
HATED = past("Leaf Rubbing Walk", tags=("nature", "plants", "learning"), status="completed", completed=True,
             rating=1, comment="too slow", time_logged_minutes=8)
SKIPPED = past("Stair Sprint", tags=("fitness",), category="fitness", status="skipped", completed=False)
PENDING = past("Bench Bird Count")


def test_prompt_groups_recent_quests():
    prompt = build_prompt(PROFILE, recent_quests=[PENDING, SKIPPED, HATED, LOVED])
    assert "last 4 sidequests" in prompt
    loved_at, hated_at = prompt.index("Loved"), prompt.index("DISLIKED")
    assert loved_at < prompt.index("Sunrise Puddle Photos") < hated_at < prompt.index("Leaf Rubbing Walk")
    assert 'said: "too slow"' in prompt and "took 8 min" in prompt
    assert "Didn't finish, no rating" in prompt and "Stair Sprint" in prompt
    assert "not done yet" in prompt and "Bench Bird Count" in prompt
    assert "first quest" not in prompt


def test_similarity_rule():
    assert too_similar_to_disliked(q("Leaf Hunt", tags=("nature", "plants")), HATED)
    assert too_similar_to_disliked(q("leaf rubbing walk!", tags=("art",)), HATED)  # same title
    assert not too_similar_to_disliked(q("Bench Sketch", tags=("art", "drawing")), HATED)
    assert not too_similar_to_disliked(q("Leafy Photos", tags=("photography", "plants")), HATED)  # other category


def test_rejects_copy_of_disliked_then_accepts_different():
    near_copy = {**QUEST, "title": "Leaf Collector", "tags": ["nature", "plants", "outdoor"]}
    llm = FakeLLM(json.dumps(near_copy), json.dumps(DIFFERENT_QUEST))
    quest = generate_quest(PROFILE, recent_quests=[HATED], llm=llm)
    assert quest.title == DIFFERENT_QUEST["title"]
    assert "rated 1/5" in llm.prompts[1] and "clearly different" in llm.prompts[1]


def test_rejects_repeated_title():
    llm = FakeLLM(json.dumps({**QUEST, "title": "Bench Bird Count"}), json.dumps(QUEST))
    assert generate_quest(PROFILE, recent_quests=[PENDING], llm=llm).title == QUEST["title"]
    assert "repeats one of the user's recent quests" in llm.prompts[1]


def test_similar_to_loved_is_fine():
    llm = FakeLLM(json.dumps({**QUEST, "title": "Lakeside Reflections"}))
    assert generate_quest(PROFILE, recent_quests=[LOVED], llm=llm).title == "Lakeside Reflections"


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------

def test_api_history_end_to_end(tmp_path):
    from fastapi.testclient import TestClient

    from backend import library
    from backend.main import app, get_llm, get_retriever

    # A quest the user completed before the history DB existed
    lib = Path(os.environ["LIBRARY_PATH"])
    library.init_library(lib)
    library.add_generated(500, "gowtham", q("Old Completed Quest", tags=("art",)), path=lib)
    library.record_feedback(500, FeedbackIn(completed=True, rating=4, time_logged_minutes=17), path=lib)

    titles = [f"Fresh Quest {i}" for i in range(12)]
    llm = FakeLLM(*[json.dumps({**QUEST, "title": t, "tags": ["outdoors", f"t{i}"]}) for i, t in enumerate(titles)])
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None
    try:
        with TestClient(app) as c:  # startup copies the logged library quest into the history
            c.put("/users/gowtham/preferences", json=VALID)
            first = c.post("/users/gowtham/quests").json()
            assert "Old Completed Quest" in llm.prompts[0]  # backfilled entry influences the 1st quest
            c.post(f"/users/gowtham/quests/{first['id']}/feedback",
                   json={"completed": True, "rating": 1, "comment": "meh", "time_logged_minutes": 6})
            for _ in range(11):
                assert c.post("/users/gowtham/quests").status_code == 201
    finally:
        app.dependency_overrides.clear()

    assert "DISLIKED" in llm.prompts[1] and "Fresh Quest 0" in llm.prompts[1]
    hist = rows(os.environ["HISTORY_PATH"])
    logged = [r for r in hist if r["time_logged_minutes"] > 0]
    assert {r["title"] for r in logged} == {"Old Completed Quest", "Fresh Quest 0"}
    assert len([r for r in hist if r["time_logged_minutes"] == 0]) == 10   # rolling window of 10
    assert "Fresh Quest 1" not in {r["title"] for r in hist}               # oldest pruned
    # every generated quest still goes into the quest library too
    conn = sqlite3.connect(lib)
    assert conn.execute("select count(*) from quests where source = 'generated'").fetchone()[0] == 13
    conn.close()


# ---------------------------------------------------------------------------
# Rating quests you didn't finish
# ---------------------------------------------------------------------------

UNFINISHED_HATED = past("Leaf Rubbing Walk", tags=("nature", "plants", "learning"), status="skipped",
                        completed=False, rating=1, comment="gave up, boring", time_logged_minutes=3)
UNFINISHED_LOVED = past("Sunset Cloud Spotting", tags=("nature", "sky"), status="skipped",
                        completed=False, rating=5, comment="loved it, ran out of time")


def test_unfinished_ratings_count():
    assert UNFINISHED_HATED.disliked and not UNFINISHED_HATED.loved
    assert UNFINISHED_LOVED.loved and not UNFINISHED_LOVED.disliked
    prompt = build_prompt(PROFILE, recent_quests=[UNFINISHED_HATED, UNFINISHED_LOVED])
    loved = prompt.split("Loved")[1].split("DISLIKED")[0]
    disliked = prompt.split("DISLIKED")[1]
    assert "Sunset Cloud Spotting" in loved and "didn't finish" in loved
    assert "Leaf Rubbing Walk" in disliked and "gave up, boring" in disliked
    assert "no rating" not in prompt


def test_unfinished_disliked_quest_is_avoided():
    near_copy = {**QUEST, "title": "Leaf Collector", "tags": ["nature", "plants", "outdoor"]}
    llm = FakeLLM(json.dumps(near_copy), json.dumps(DIFFERENT_QUEST))
    assert generate_quest(PROFILE, recent_quests=[UNFINISHED_HATED], llm=llm).title == DIFFERENT_QUEST["title"]


def test_api_rates_unfinished_quest_everywhere():
    from fastapi.testclient import TestClient

    from backend.main import app, get_llm, get_retriever

    llm = FakeLLM(json.dumps(QUEST), json.dumps(DIFFERENT_QUEST))
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None
    try:
        with TestClient(app) as c:
            c.put("/users/gowtham/preferences", json=VALID)
            qid = c.post("/users/gowtham/quests").json()["id"]
            r = c.post(f"/users/gowtham/quests/{qid}/feedback",
                       json={"completed": False, "rating": 2, "comment": "too cold", "time_logged_minutes": 5})
            assert r.status_code == 200 and r.json()["status"] == "skipped"
            assert r.json()["feedback"]["rating"] == 2
            # rating is optional when you didn't finish
            assert c.post("/users/gowtham/quests").status_code == 201
            qid2 = c.get("/users/gowtham/quests").json()[0]["id"]
            assert c.post(f"/users/gowtham/quests/{qid2}/feedback", json={"completed": False}).status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert "DISLIKED" in llm.prompts[1] and "too cold" in llm.prompts[1]
    [h] = [r for r in rows(os.environ["HISTORY_PATH"]) if r["app_quest_id"] == qid]
    assert (h["status"], h["rating"], h["time_logged_minutes"]) == ("skipped", 2, 5)
    conn = sqlite3.connect(os.environ["LIBRARY_PATH"])
    assert conn.execute("select rating, time_logged_minutes from quests where app_quest_id = ?",
                        (qid,)).fetchone() == (2, 5)
    conn.close()


# ---------------------------------------------------------------------------
# Pruned quest gets logged time later -> copied back immediately
# ---------------------------------------------------------------------------

def test_pruned_quest_with_logged_time_is_copied_back_immediately(tmp_path, hpath):
    from backend import library

    lib = tmp_path / "lib.db"
    library.init_library(lib)
    for i in range(1, 13):  # quest 1 and 2 fall out of the last 10
        library.add_generated(i, "u1", q(f"Quest number {i}"), path=lib)
        history.add_quest(i, "u1", q(f"Quest number {i}"), path=hpath)
    assert "Quest number 1" not in {r["title"] for r in rows(hpath)}

    fb = FeedbackIn(completed=True, rating=4, comment="did it later", time_logged_minutes=11)
    library.record_feedback(1, fb, path=lib)
    assert history.record_feedback(1, fb, path=hpath, library_db=lib) is True
    [r] = [r for r in rows(hpath) if r["app_quest_id"] == 1]
    assert (r["title"], r["rating"], r["time_logged_minutes"], r["copied_from_library"]) == \
        ("Quest number 1", 4, 11, 1)

    # no logged time -> nothing to copy
    zero = FeedbackIn(completed=False)
    library.record_feedback(2, zero, path=lib)
    assert history.record_feedback(2, zero, path=hpath, library_db=lib) is False
    assert 2 not in {r["app_quest_id"] for r in rows(hpath)}

    # the copied row survives later pruning
    history.add_quest(13, "u1", q("Quest number 13"), path=hpath)
    assert 1 in {r["app_quest_id"] for r in rows(hpath)}


def test_api_copies_pruned_quest_with_logged_time(tmp_path):
    from fastapi.testclient import TestClient

    from backend.main import app, get_llm, get_retriever

    llm = FakeLLM(*[json.dumps({**QUEST, "title": f"API Quest {i}", "tags": ["outdoors", f"t{i}"]})
                    for i in range(12)])
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None
    try:
        with TestClient(app) as c:
            c.put("/users/gowtham/preferences", json=VALID)
            ids = [c.post("/users/gowtham/quests").json()["id"] for _ in range(12)]
            assert ids[0] not in {r["app_quest_id"] for r in rows(os.environ["HISTORY_PATH"])}
            r = c.post(f"/users/gowtham/quests/{ids[0]}/feedback",
                       json={"completed": True, "rating": 5, "time_logged_minutes": 20})
            assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()

    [h] = [r for r in rows(os.environ["HISTORY_PATH"]) if r["app_quest_id"] == ids[0]]
    assert (h["title"], h["rating"], h["time_logged_minutes"]) == ("API Quest 0", 5, 20)
