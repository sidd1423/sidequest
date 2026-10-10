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
        results = r.retrieve(prefs(interests=interests, availability={"duration_minutes": 180}))
        assert len(results) == 3
        assert all(x.source == "local_library" for x in results)
        on_topic = [x for x in results if x.category in expect or expect & set(x.tags)]
        assert len(on_topic) >= 2, (interests, [x.category for x in results])


def test_prefers_quests_that_fit_time(lib):
    results = LocalLibraryRetriever(lib).retrieve(prefs(interests=["wellness"], availability={"duration_minutes": 30}))
    assert results[0].duration_minutes <= 30


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

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("LIBRARY_PATH", str(lib))
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
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
