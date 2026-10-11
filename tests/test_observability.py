"""Sentry records every Gemma attempt (spans, rejection reasons, tokens) - checked with an in-memory transport."""

import json

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from backend import observability as obs
from backend.llm import LLMError, LLMTimeout
from backend.quest_generator import generate_quest
from backend.schemas import PastQuest, PreferencesIn

PROFILE = PreferencesIn.model_validate({"interests": ["nature"], "availability": {"duration_minutes": 20}})
GOOD = {"title": "Puddle Mirror Hunt", "summary": "Find reflections in puddles nearby.", "steps": ["Go out"],
        "estimated_minutes": 15, "difficulty": "easy", "energy_required": 2, "tags": ["nature"]}


class Captured(Transport):
    envelopes: list = []

    def capture_envelope(self, envelope):
        Captured.envelopes.append(envelope)


def items(kind):
    out = []
    for env in Captured.envelopes:
        for item in env.items:
            if item.type == kind:
                out.append(json.loads(item.payload.get_bytes()))
    return out


@pytest.fixture()
def sentry():
    Captured.envelopes = []
    assert obs.init(dsn="https://key@o0.ingest.sentry.io/0", transport=Captured, traces_sample_rate=1.0)
    yield
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # back to a disabled client
    obs._enabled = False


class ScriptedLLM:
    """Answers in order; a str is returned, an exception raised. Reports usage like GemmaClient."""
    model = "gemma-test"
    max_tokens = 8192
    timeout = 180

    def __init__(self, *answers):
        self.answers = list(answers)
        self.last_call = {}

    def complete(self, prompt, *, temperature=0.9):
        answer = self.answers.pop(0)
        self.last_call = {"seconds": 1.5, "input_tokens": 900, "output_tokens": 300, "reasoning_tokens": 120,
                          "finish_reason": "stop"}
        if isinstance(answer, Exception):
            self.last_call = {"seconds": 180.0}
            raise answer
        return answer


def gen_spans():
    """All spans: classic ones inside transactions, plus streamed v2 span items (newer
    sentry-sdk versions send gen_ai spans that way), normalized to {op, data, status, ids}."""
    txs = items("transaction")
    spans = [s for tx in txs for s in tx["spans"]]
    for batch in items("span"):
        for sp in batch.get("items", []):
            attrs = {k: v.get("value") for k, v in (sp.get("attributes") or {}).items()}
            spans.append({"op": attrs.get("sentry.op"), "data": attrs, "status": sp.get("status"),
                          "span_id": sp["span_id"], "parent_span_id": sp.get("parent_span_id")})
    return spans, txs


def test_every_attempt_is_a_span_with_reasons_and_tokens(sentry):
    indoor = dict(GOOD, title="Mall Walk", setting="indoor")
    disliked = PastQuest(title="Bench Bird Count", quest_text="x", category="nature", duration_minutes=10,
                         difficulty="easy", tags=["nature", "birds", "quiet"], rating=1)
    similar = dict(GOOD, title="Bird Bench Tally", tags=["nature", "birds", "quiet"])
    llm = ScriptedLLM("not json", json.dumps(indoor), LLMTimeout("slow"), json.dumps(GOOD))
    import backend.quest_generator as qg
    qg_max = qg.MAX_ATTEMPTS
    qg.MAX_ATTEMPTS = 4
    try:
        with sentry_sdk.start_transaction(op="http.server", name="POST /users/{id}/quests"):
            quest = generate_quest(PROFILE, llm=llm, recent_quests=[disliked])
    finally:
        qg.MAX_ATTEMPTS = qg_max
    sentry_sdk.flush()
    assert quest.title == "Puddle Mirror Hunt"
    spans, _ = gen_spans()
    outer = next(s for s in spans if s["op"] == "quest.generate")
    chats = [s for s in spans if s["op"] == "gen_ai.chat"]
    assert [c["data"]["sidequest.outcome"] for c in chats] == ["rejected", "rejected", "timeout", "ok"]
    assert chats[0]["data"]["sidequest.rejection_reasons"] == "invalid_json"
    assert chats[1]["data"]["sidequest.rejection_reasons"] == "indoor"
    assert chats[2]["status"] in ("deadline_exceeded", "error")
    assert chats[3]["data"]["gen_ai.usage.input_tokens"] == 900
    assert chats[3]["data"]["gen_ai.usage.output_tokens.reasoning"] == 120
    assert chats[3]["data"]["gen_ai.request.model"] == "gemma-test"
    assert all(c["parent_span_id"] == outer["span_id"] for c in chats)
    assert outer["data"]["outcome"] == "ok" and outer["data"]["attempts"] == 4
    assert outer["data"]["rejection_reasons"] == "invalid_json,indoor"
    assert "gen_ai.request.messages" not in chats[0]["data"]  # prompts stay private by default
    del similar


def test_failed_generation_is_reported_with_all_attempts(sentry):
    repeat = dict(GOOD, title="Old Favourite")
    past = PastQuest(title="Old Favourite", quest_text="x", duration_minutes=10, difficulty="easy")
    llm = ScriptedLLM(json.dumps(repeat), json.dumps(dict(GOOD, estimated_minutes=45)), json.dumps(repeat))
    with pytest.raises(LLMError):
        generate_quest(PROFILE, llm=llm, recent_quests=[past])
    sentry_sdk.flush()
    events = items("event")
    assert len(events) == 1
    ctx = events[0]["contexts"]["quest_generation"]
    assert ctx["outcome"] == "failed" and ctx["attempts"] == 3
    assert ctx["rejection_reasons"] == ["repeat", "too_long", "repeat"]
    assert ctx["input_tokens"] == 2700
    assert events[0]["tags"]["gemma.last_rejection"] == "repeat"
    assert events[0]["fingerprint"] == ["quest-generation-failed", "failed"]


def test_timeouts_reported_as_timeout(sentry):
    llm = ScriptedLLM(LLMTimeout("slow 1"), LLMTimeout("slow 2"))
    with pytest.raises(LLMTimeout, match="slow 2"):
        generate_quest(PROFILE, llm=llm)
    sentry_sdk.flush()
    ctx = items("event")[0]["contexts"]["quest_generation"]
    assert ctx["outcome"] == "timeout" and [c["outcome"] for c in ctx["calls"]] == ["timeout", "timeout"]


def test_prompts_only_when_asked(sentry, monkeypatch):
    monkeypatch.setenv("SENTRY_SEND_PROMPTS", "true")
    with sentry_sdk.start_transaction(op="test", name="t"):
        generate_quest(PROFILE, llm=ScriptedLLM(json.dumps(GOOD)))
    sentry_sdk.flush()
    chat = next(s for s in gen_spans()[0] if s["op"] == "gen_ai.chat")
    assert "OUTSIDE" in json.dumps(chat["data"]["gen_ai.request.messages"])
    assert chat["data"]["gen_ai.usage.input_tokens"] == 900


def test_off_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert obs.init() is False and not obs.enabled()
    # Everything is a no-op.
    with obs.span("x", "y", a=1) as s:
        s.set_data("b", 2)
    obs.metric("count", "n")
    assert generate_quest(PROFILE, llm=ScriptedLLM(json.dumps(GOOD))).title == "Puddle Mirror Hunt"


def test_usage_parsed_from_openai_response():
    from backend.llm import usage_from

    class R:
        def json(self):
            return {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                              "completion_tokens_details": {"reasoning_tokens": 3}}}
    assert usage_from(R()) == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "reasoning_tokens": 3}


def test_api_request_trace_contains_generation(sentry):
    from fastapi.testclient import TestClient
    from backend.main import app, get_llm, get_retriever

    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(json.dumps(GOOD))
    app.dependency_overrides[get_retriever] = lambda: None
    try:
        with TestClient(app) as c:
            c.put("/users/tester/preferences", json={"interests": ["nature"]})
            assert c.post("/users/tester/quests", json={"duration_minutes": 20}).status_code == 201
    finally:
        app.dependency_overrides.clear()
    sentry_sdk.flush()
    spans, txs = gen_spans()
    tx = next(t for t in txs if "quests" in t["transaction"] and "POST" in json.dumps(t.get("request", {})) or
              t["transaction"].endswith("/quests"))
    assert tx["transaction"] == "/users/{user_id}/quests"
    assert tx["user"] == {"id": "tester"}
    assert any(s["op"] == "quest.generate" for s in spans)
    assert any(s["op"] == "gen_ai.chat" and s["data"].get("sidequest.outcome") == "ok" for s in spans)


def test_gemma_500_is_retried_after_a_pause(monkeypatch):
    """Google AI Studio sometimes answers HTTP 500 "internal error" - retry instead of failing the quest."""
    from backend import quest_generator as qg
    from backend.llm import LLMServerError
    pauses = []
    monkeypatch.setattr(qg.time, "sleep", lambda s: pauses.append(s))
    llm = ScriptedLLM(LLMServerError("HTTP 500 internal error", 500), LLMServerError("HTTP 503", 503),
                      json.dumps(GOOD))
    assert generate_quest(PROFILE, llm=llm).title == "Puddle Mirror Hunt"
    assert pauses == [3.0, 8.0]

    llm = ScriptedLLM(*[LLMServerError("HTTP 500 internal error", 500)] * 3)
    with pytest.raises(LLMServerError, match="500"):
        generate_quest(PROFILE, llm=llm)


def test_gemma_client_marks_5xx_and_429_as_temporary(monkeypatch):
    from backend import llm as llm_mod

    class R:
        def __init__(self, status):
            self.status_code, self.text, self.ok = status, '{"error":{"code":%d,"status":"INTERNAL"}}' % status, False

    for status in (500, 503, 429):
        monkeypatch.setattr(llm_mod.requests, "post", lambda *a, _s=status, **k: R(_s))
        with pytest.raises(llm_mod.LLMServerError) as err:
            llm_mod.GemmaClient(base_url="https://x.test", api_key="k").complete("p")
        assert err.value.status == status
    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: R(404))
    with pytest.raises(LLMError) as err:
        llm_mod.GemmaClient(base_url="https://x.test", api_key="k").complete("p")
    assert not isinstance(err.value, llm_mod.LLMServerError)
