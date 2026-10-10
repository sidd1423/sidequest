"""Local SQLite quest library with offline WordLlama embeddings."""

import json
import sqlite3

import pytest

from backend.schemas import PreferencesIn

from .test_api import VALID
from .test_quests import QUEST, FakeLLM

pytest.importorskip("wordllama")

from backend.library import LocalLibraryRetriever, seed  # noqa: E402
from backend.retrieval import RetrievalError  # noqa: E402


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    path = tmp_path_factory.mktemp("lib") / "quest_library.db"
    assert seed(path) == 30
    assert seed(path) == 30  # idempotent
    return path


def prefs(**over):
    return PreferencesIn.model_validate({**VALID, **over})


def test_seed_writes_vectors(lib):
    conn = sqlite3.connect(lib)
    n, with_emb, size, models = conn.execute(
        "select count(*), count(embedding), min(length(embedding)), count(distinct embedding_model) from quests"
    ).fetchone()
    assert (n, with_emb, size, models) == (30, 30, 256 * 4, 1)


def test_top3_matches_interests(lib):
    r = LocalLibraryRetriever(lib)
    for interests, expect in [
        (["nature", "photography"], {"nature", "photography"}),
        (["fitness", "outdoors"], {"fitness", "outdoors"}),
        (["food", "social"], {"food", "social"}),
        (["music", "nightlife"], {"music", "nightlife"}),
    ]:
        results = r.retrieve(prefs(interests=interests, availability={"duration_minutes": 30}))
        assert len(results) == 3
        assert all(x.source == "local_library" for x in results)
        on_topic = [x for x in results if x.category in expect or expect & set(x.tags)]
        assert len(on_topic) >= 2, (interests, [x.category for x in results])


def test_prefers_quests_that_fit_time(lib):
    results = LocalLibraryRetriever(lib).retrieve(prefs(interests=["fitness"], availability={"duration_minutes": 10}))
    assert results[0].duration_minutes <= 10


def test_custom_interest_birdwatching(lib):
    results = LocalLibraryRetriever(lib).retrieve(prefs(interests=[], custom_interests=["birdwatching"]))
    assert "birdwatching" in results[0].tags


def test_missing_library_raises(tmp_path):
    with pytest.raises(RetrievalError, match="python -m backend.library"):
        LocalLibraryRetriever(tmp_path / "nope.db").retrieve(prefs())


def test_model_mismatch_detected(lib, tmp_path):
    copy = tmp_path / "copy.db"
    copy.write_bytes(lib.read_bytes())
    conn = sqlite3.connect(copy)
    conn.execute("update quests set embedding_model = 'other-model'")
    conn.commit()
    conn.close()
    with pytest.raises(RetrievalError, match="re-run"):
        LocalLibraryRetriever(copy).retrieve(prefs())


def test_api_uses_local_library_on_first_quest(lib, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    copy = tmp_path / "lib_copy.db"  # the API writes generated quests into the library
    copy.write_bytes(lib.read_bytes())
    monkeypatch.setenv("LIBRARY_PATH", str(copy))
    from backend.main import app, get_llm

    llm = FakeLLM(json.dumps(QUEST))
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        with TestClient(app) as c:  # real get_retriever -> local library
            c.put("/users/newbie/preferences", json=VALID)
            assert c.post("/users/newbie/quests").status_code == 201
    finally:
        app.dependency_overrides.clear()

    section = llm.prompts[-1].split("## Example quests matched to this user")[1].split("##")[0]
    assert section.count("\n- ") == 3
    assert "bird-watching" in section or "photograph" in section


# ---------------------------------------------------------------------------
# Generated quests + feedback stored in the library
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from backend import library  # noqa: E402
from backend.schemas import FeedbackIn, Quest  # noqa: E402

OLD_FORMAT = Path(__file__).parent / "fixtures" / "old_format_library.db"


def _rows(path, where="1=1"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"select * from quests where {where} order by id")]
    finally:
        conn.close()


def test_migrate_keeps_old_rows(tmp_path):
    path = tmp_path / "lib.db"
    path.write_bytes(OLD_FORMAT.read_bytes())
    before = _rows(path)
    assert "time_logged_minutes" not in before[0]

    conn = sqlite3.connect(path)
    assert library.migrate(conn) is True
    assert library.migrate(conn) is False  # idempotent
    conn.close()
    after = _rows(path)
    assert len(after) == len(before) == 30
    assert all(r["time_logged_minutes"] == 0 and r["source"] == "seed" for r in after)
    assert [r["quest_text"] for r in after] == [r["quest_text"] for r in before]
    assert all(r["embedding"] == b["embedding"] for r, b in zip(after, before))


def test_init_upgrades_old_library_to_current_seed_quests(tmp_path):
    path = tmp_path / "lib.db"
    path.write_bytes(OLD_FORMAT.read_bytes())
    library.init_library(path)
    seeds = _rows(path, "source = 'seed'")
    expected = [q["quest_text"] for q in json.loads(library.SEED_FILE.read_text(encoding="utf-8"))]
    assert sorted(r["quest_text"] for r in seeds) == sorted(expected)
    assert all(5 <= r["duration_minutes"] <= 30 for r in seeds)
    assert {r["time_logged_minutes"] for r in seeds} == {0}

    library.init_library(path)  # unchanged seed file -> nothing to do
    assert seed(path) == 30     # explicit re-seed still upserts, no duplicates
    assert len(_rows(path)) == 30


def test_reseed_keeps_generated_quests(tmp_path):
    path = tmp_path / "lib.db"
    library.init_library(path)
    library.add_generated(1, "u", Quest.model_validate(QUEST), path=path)
    library.record_feedback(1, FeedbackIn(completed=True, rating=5, time_logged_minutes=18), path=path)

    smaller = tmp_path / "seed.json"
    smaller.write_text(json.dumps(json.loads(library.SEED_FILE.read_text(encoding="utf-8"))[:5]))
    library.init_library(path, seed_file=smaller)  # seed file changed -> re-seed
    assert len(_rows(path, "source = 'seed'")) == 5
    [g] = _rows(path, "source = 'generated'")
    assert (g["rating"], g["time_logged_minutes"]) == (5, 18)


def test_init_creates_and_seeds_missing_library(tmp_path):
    path = tmp_path / "new" / "lib.db"
    library.init_library(path)
    rows = _rows(path)
    assert len(rows) == 30 and {r["time_logged_minutes"] for r in rows} == {0}


def test_generated_quest_and_feedback_rows(lib, tmp_path):
    path = tmp_path / "lib.db"
    path.write_bytes(lib.read_bytes())
    library.init_library(path)
    quest = Quest.model_validate(QUEST)

    library.add_generated(7, "gowtham", quest, model="gemma-test", path=path)
    library.add_generated(7, "gowtham", quest, model="gemma-test", path=path)  # no duplicate
    [g] = _rows(path, "source = 'generated'")
    assert g["app_quest_id"] == 7 and g["user_id"] == "gowtham" and g["title"] == QUEST["title"]
    assert g["status"] == "suggested" and g["time_logged_minutes"] == 0
    assert g["completed"] is None and g["rating"] is None
    assert g["category"] in ("nature", "photography")
    assert json.loads(g["quest_json"])["steps"] == QUEST["steps"]
    assert len(g["embedding"]) == 256 * 4

    # Not an example until it's completed and rated highly
    r = LocalLibraryRetriever(path)
    assert all(x.source == "local_library" for x in r.search(g["quest_text"], k=31))

    fb = FeedbackIn(completed=True, rating=5, comment="loved it", time_logged_minutes=55)
    assert library.record_feedback(7, fb, path=path)
    [g] = _rows(path, "source = 'generated'")
    assert (g["status"], g["completed"], g["rating"], g["feedback_comment"], g["time_logged_minutes"]) == \
        ("completed", 1, 5, "loved it", 55)
    assert g["feedback_at"]
    top = r.search(g["quest_text"], k=1)[0]
    assert top.source == "local_library_rated" and top.quest_text == g["quest_text"]


def test_skipped_feedback(lib, tmp_path):
    path = tmp_path / "lib.db"
    path.write_bytes(lib.read_bytes())
    library.init_library(path)
    library.add_generated(9, "u1", Quest.model_validate(QUEST), path=path)
    library.record_feedback(9, FeedbackIn(completed=False, rating=3, comment="rained", time_logged_minutes=4),
                            path=path)
    [g] = _rows(path, "app_quest_id = 9")
    # unfinished quests keep their rating and partial time
    assert (g["status"], g["completed"], g["rating"], g["time_logged_minutes"]) == ("skipped", 0, 3, 4)
    assert library.record_feedback(999, FeedbackIn(completed=False), path=path) is False


def test_api_writes_generated_quests_and_feedback_to_library(lib, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    path = tmp_path / "lib.db"
    path.write_bytes(OLD_FORMAT.read_bytes())  # startup should migrate it
    monkeypatch.setenv("LIBRARY_PATH", str(path))
    from backend.main import app, get_llm

    llm = FakeLLM(json.dumps(QUEST), json.dumps({**QUEST, "title": "Second Quest Title"}))
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        with TestClient(app) as c:
            c.put("/users/gowtham/preferences", json=VALID)
            q1 = c.post("/users/gowtham/quests").json()
            r = c.post(f"/users/gowtham/quests/{q1['id']}/feedback",
                       json={"completed": True, "rating": 5, "comment": "great", "time_logged_minutes": 80})
            assert r.status_code == 200
            assert r.json()["feedback"]["time_logged_minutes"] == 80
            q2 = c.post("/users/gowtham/quests").json()
    finally:
        app.dependency_overrides.clear()

    seeds = _rows(path, "source = 'seed'")
    gen = _rows(path, "source = 'generated'")
    assert len(seeds) == 30 and {s["time_logged_minutes"] for s in seeds} == {0}
    assert [g["app_quest_id"] for g in gen] == [q1["id"], q2["id"]]
    assert (gen[0]["rating"], gen[0]["time_logged_minutes"], gen[0]["status"]) == (5, 80, "completed")
    assert (gen[1]["status"], gen[1]["time_logged_minutes"]) == ("suggested", 0)
    # the loved quest is now offered back to Gemma as an example
    section = llm.prompts[-1].split("## Example quests matched to this user")[1].split("##")[0]
    assert QUEST["title"] in section
