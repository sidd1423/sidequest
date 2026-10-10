"""Tiger Data retrieval tests.

The pgvector tests need a real Postgres with the `vector` extension. Point
TEST_PG_URL at one to run them (e.g. a throwaway Tiger service or local
Postgres); otherwise they're skipped. Embeddings are faked with a
deterministic bag-of-words hash so no API key is needed.
"""

import hashlib
import json
import math
import os
import re

import pytest

from backend.embeddings import EmbeddingError, GeminiEmbedder
from backend.retrieval import RetrievalError, TigerRetriever, build_query_text
from backend.schemas import PreferencesIn

from .test_api import VALID
from .test_quests import QUEST, FakeLLM

PG_URL = os.getenv("TEST_PG_URL")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set TEST_PG_URL to run pgvector tests")

DIM = 768
STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "your", "you", "it", "at", "then",
        "about", "takes", "minutes", "difficulty", "tags", "category", "out", "level", "energy", "sidequest"}


class BagOfWordsEmbedder:
    """Deterministic stand-in: hashed word counts, L2-normalised."""

    dim = DIM
    model = "bag-of-words-test"

    def __init__(self):
        self.calls = []

    def embed(self, texts, task="RETRIEVAL_DOCUMENT"):
        self.calls.append((list(texts), task))
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"[a-z]+", t.lower()):
                if w in STOP or len(w) < 3:
                    continue
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


PROFILE = PreferencesIn.model_validate(VALID)  # nature + photography, 120 min, waterfront, easy


# ---------------------------------------------------------------------------
# No database needed
# ---------------------------------------------------------------------------

def test_query_text_describes_user():
    q = build_query_text(PROFILE)
    for word in ("nature", "photography", "120 minutes", "easy", "waterfront", "step free", "rain"):
        assert word in q


def test_seed_file_is_valid():
    from tiger.seed import load_seed
    from pathlib import Path

    rows = load_seed(Path("tiger/seed_quests.json"))
    assert 20 <= len(rows) <= 30
    assert len({r["quest_text"] for r in rows}) == len(rows)


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body, self.ok = status, body, 200 <= status < 300
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_gemini_embedder_request_and_normalisation(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, body=json, headers=headers)
        return FakeResp(200, {"embeddings": [{"values": [3.0, 4.0] + [0.0] * (DIM - 2)}]})

    monkeypatch.setattr("backend.embeddings.requests.post", fake_post)
    [v] = GeminiEmbedder(api_key="k").embed(["hi"], task="RETRIEVAL_QUERY")
    assert seen["url"].endswith("models/gemini-embedding-001:batchEmbedContents")
    assert seen["headers"]["x-goog-api-key"] == "k"
    req = seen["body"]["requests"][0]
    assert req["taskType"] == "RETRIEVAL_QUERY" and req["outputDimensionality"] == DIM
    assert v[:2] == [0.6, 0.8]


def test_gemini_embedder_wrong_dim(monkeypatch):
    monkeypatch.setattr("backend.embeddings.requests.post",
                        lambda *a, **k: FakeResp(200, {"embeddings": [{"values": [1.0, 2.0]}]}))
    with pytest.raises(EmbeddingError, match="768"):
        GeminiEmbedder(api_key="k").embed(["hi"])


def test_api_falls_back_when_tiger_fails(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    from backend.main import app, get_llm, get_retriever

    class Broken:
        def retrieve(self, *a, **k):
            raise RetrievalError("connection refused")

    llm = FakeLLM(json.dumps(QUEST))
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: Broken()
    try:
        with TestClient(app) as c:
            c.put("/users/gowtham/preferences", json=VALID)
            assert c.post("/users/gowtham/quests").status_code == 201  # generation still works
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Real Postgres + pgvector
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded(monkeypatch):
    import psycopg

    table = "quests_test"
    monkeypatch.setenv("TIGER_DATABASE_URL", PG_URL)
    monkeypatch.setenv("TIGER_QUESTS_TABLE", table)
    embedder = BagOfWordsEmbedder()
    monkeypatch.setattr("backend.embeddings.GeminiEmbedder", lambda *a, **k: embedder)
    monkeypatch.setattr("backend.retrieval.GeminiEmbedder", lambda *a, **k: embedder)

    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    from tiger import seed

    assert seed.main([]) == 0
    assert seed.main([]) == 0  # idempotent re-run
    yield TigerRetriever(embedder=embedder), table, embedder
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {table}")


@needs_pg
def test_seed_creates_and_fills_table(seeded):
    import psycopg

    _, table, embedder = seeded
    with psycopg.connect(PG_URL) as conn:
        total, with_emb = conn.execute(f"select count(*), count(embedding) from {table}").fetchone()
        dims = conn.execute(f"select vector_dims(embedding) from {table} limit 1").fetchone()[0]
        idx = conn.execute("select indexdef from pg_indexes where tablename = %s", (table,)).fetchall()
    assert total == with_emb == 30
    assert dims == DIM
    assert any("hnsw" in i[0] and "vector_cosine_ops" in i[0] for i in idx)
    assert embedder.calls[0][1] == "RETRIEVAL_DOCUMENT"


@needs_pg
def test_retrieves_three_relevant_quests(seeded):
    retriever, _, embedder = seeded
    results = retriever.retrieve(PROFILE, k=3)
    assert len(results) == 3
    assert embedder.calls[-1][1] == "RETRIEVAL_QUERY"
    assert all(r.duration_minutes <= 120 for r in results)
    assert results[0].similarity >= results[1].similarity >= results[2].similarity
    # nature/photography/waterfront profile should surface matching quests
    assert any({"photography", "nature", "waterfront"} & set(r.tags) for r in results)


@needs_pg
def test_prefers_quests_that_fit_time(seeded):
    retriever, _, _ = seeded
    short = PreferencesIn.model_validate({**VALID, "interests": ["outdoors", "fitness"],
                                          "availability": {"duration_minutes": 30}})
    results = retriever.retrieve(short, k=3)
    fitting = [r for r in results if r.duration_minutes <= 30]
    assert fitting and results[0].duration_minutes <= 30


@needs_pg
def test_first_quest_gets_library_examples(seeded, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    retriever, _, _ = seeded
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    from backend.main import app, get_llm

    llm = FakeLLM(json.dumps(QUEST))
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        with TestClient(app) as c:  # real get_retriever -> reads TIGER_* env
            c.put("/users/newbie/preferences", json=VALID)
            assert c.post("/users/newbie/quests").status_code == 201
    finally:
        app.dependency_overrides.clear()

    prompt = llm.prompts[-1]
    section = prompt.split("## Example quests matched to this user")[1].split("##")[0]
    assert section.count("\n- ") == 3
    assert "first quest" in prompt  # no feedback yet, but examples still provided


@needs_pg
def test_bad_url_raises_retrieval_error():
    r = TigerRetriever(url="postgresql://nobody@127.0.0.1:1/x", embedder=BagOfWordsEmbedder())
    with pytest.raises(RetrievalError):
        r.retrieve(PROFILE)
