import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.llm import GemmaClient, LLMError
from backend.quest_generator import build_prompt, generate_quest, parse_quest
from backend.schemas import FeedbackEntry, PreferencesIn, Quest, QuestExample

from .test_api import VALID

QUEST = {
    "title": "Waterfront Morning Light Walk",
    "summary": "Stroll the lakeshore at sunrise and photograph three reflections of the city.",
    "steps": ["Head to the waterfront trail", "Find three reflections", "Pick your favourite shot"],
    "estimated_minutes": 20,
    "difficulty": "easy",
    "energy_required": 2,
    "tags": ["Nature", "photography", "nature"],
    "accessibility_notes": "Paved, step-free path with benches.",
    "weather_backup": "Shoot reflections in a glass atrium downtown instead.",
    "why_it_fits": "Quiet, easy, photography by the water.",
}


DIFFERENT_QUEST = {
    **QUEST,
    "title": "Neighbourhood Bench Sketch",
    "summary": "Find a bench nearby and sketch the street scene in front of you for ten minutes.",
    "tags": ["art", "drawing", "quiet"],
}


class FakeLLM:
    model = "fake-gemma"

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, temperature: float = 0.9) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


PROFILE = PreferencesIn.model_validate(VALID)


# ---------------------------------------------------------------------------
# generate_quest()
# ---------------------------------------------------------------------------

def test_first_run_needs_only_profile():
    llm = FakeLLM(json.dumps(QUEST))
    quest = generate_quest(PROFILE, llm=llm)
    assert quest.title == QUEST["title"]
    assert quest.tags == ["nature", "photography"]
    assert "first quest" in llm.prompts[0]
    assert "Past quests" not in llm.prompts[0]
    assert "Feedback on previous" not in llm.prompts[0]


def test_examples_and_feedback_reach_prompt():
    example = QuestExample.from_quest(Quest.model_validate({**QUEST, "title": "Sunset Sketch Session"}))
    fb = FeedbackEntry(
        completed=False, rating=None, comment="too far away",
        quest_title="Island Ferry Hop", created_at=datetime.now(timezone.utc),
    )
    prompt = build_prompt(PROFILE, [example], [fb])
    assert "Sunset Sketch Session" in prompt
    assert "Island Ferry Hop [didn't finish]" in prompt
    assert "too far away" in prompt
    assert "first quest" not in prompt


def test_hard_constraints_in_prompt():
    prompt = build_prompt(PROFILE)
    assert "between 5 and 25 minutes" in prompt
    assert "within 1.5 km" in prompt
    assert "between 8 and 28" in prompt
    assert "OUTSIDE" in prompt and "RIGHT NOW" in prompt
    assert "indoor | outdoor" not in prompt and "time of day" not in prompt.lower()


def test_parses_fenced_json():
    assert parse_quest("```json\n" + json.dumps(QUEST) + "\n```").title == QUEST["title"]


def test_retries_bad_json_then_succeeds():
    llm = FakeLLM("Sure! Here's a quest: not json", json.dumps(QUEST))
    assert generate_quest(PROFILE, llm=llm).title == QUEST["title"]
    assert "previous answer was rejected" in llm.prompts[1]


def test_retries_when_quest_too_long():
    too_long = {**QUEST, "estimated_minutes": 45}
    llm = FakeLLM(json.dumps(too_long), json.dumps(QUEST))
    assert generate_quest(PROFILE, llm=llm).estimated_minutes == 20
    assert "exceeds" in llm.prompts[1]


def test_retries_when_quest_is_indoors():
    indoor = {**QUEST, "setting": "indoor"}
    llm = FakeLLM(json.dumps(indoor), json.dumps(QUEST))
    assert generate_quest(PROFILE, llm=llm).setting.value == "outdoor"
    assert "outdoors" in llm.prompts[1]


def test_retries_when_quest_too_short():
    llm = FakeLLM(json.dumps({**QUEST, "estimated_minutes": 2}), json.dumps(QUEST))
    assert generate_quest(PROFILE, llm=llm).estimated_minutes == 20


def test_quest_without_setting_defaults_outdoor():
    data = {k: v for k, v in QUEST.items() if k != "setting"}
    assert Quest.model_validate(data).setting.value == "outdoor"


def test_gives_up_after_three_attempts():
    with pytest.raises(LLMError):
        generate_quest(PROFILE, llm=FakeLLM("nope", "nope", "nope"))


# ---------------------------------------------------------------------------
# GemmaClient (HTTP mocked)
# ---------------------------------------------------------------------------

class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_gemma_client_request_shape(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return FakeResp(200, {"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr("backend.llm.requests.post", fake_post)
    client = GemmaClient(base_url="https://example.test/v1/", api_key="k", model="gemma-4-26b-a4b-it")
    assert client.complete("prompt") == "hi"
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer k"
    assert seen["json"]["model"] == "gemma-4-26b-a4b-it"
    assert seen["json"]["messages"] == [{"role": "user", "content": "prompt"}]


def test_gemma_client_bad_key(monkeypatch):
    monkeypatch.setattr("backend.llm.requests.post", lambda *a, **k: FakeResp(401, {"error": "bad"}))
    with pytest.raises(LLMError, match="GEMMA_API_KEY"):
        GemmaClient(base_url="https://x.test", api_key="bad").complete("p")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    from backend.main import app, get_llm, get_retriever

    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None  # local fallback only
    with TestClient(app) as c:
        yield c, llm
    app.dependency_overrides.clear()


def test_generate_requires_preferences(api):
    client, _ = api
    assert client.post("/users/gowtham/quests").status_code == 404


def test_full_loop_first_run_then_history(api):
    client, llm = api
    client.put("/users/gowtham/preferences", json=VALID)

    # First quest: no examples, no feedback
    llm.responses.append(json.dumps(QUEST))
    r = client.post("/users/gowtham/quests")
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["status"] == "suggested" and first["model"] == "fake-gemma"
    assert "first quest" in llm.prompts[-1]

    # Complete it and rate it highly
    r = client.post(f"/users/gowtham/quests/{first['id']}/feedback",
                    json={"completed": True, "rating": 5, "comment": "loved the light"})
    assert r.json()["status"] == "completed"

    # Second quest: the first one is now both an example and feedback
    llm.responses.append(json.dumps({**QUEST, "title": "Harbour Heron Hunt"}))
    r = client.post("/users/gowtham/quests")
    assert r.status_code == 201
    prompt = llm.prompts[-1]
    assert "Example quests matched to this user" in prompt and QUEST["title"] in prompt
    assert "loved the light" in prompt

    quests = client.get("/users/gowtham/quests").json()
    assert [q["quest"]["title"] for q in quests] == ["Harbour Heron Hunt", QUEST["title"]]


def test_low_rated_quest_is_feedback_not_example(api):
    client, llm = api
    client.put("/users/gowtham/preferences", json=VALID)
    llm.responses += [json.dumps(QUEST), json.dumps(DIFFERENT_QUEST)]
    qid = client.post("/users/gowtham/quests").json()["id"]
    client.post(f"/users/gowtham/quests/{qid}/feedback", json={"completed": True, "rating": 2})
    assert client.post("/users/gowtham/quests").status_code == 201
    assert "Example quests" not in llm.prompts[-1]
    assert "rated 2/5" in llm.prompts[-1] and "DISLIKED" in llm.prompts[-1]


def test_feedback_validation(api):
    client, llm = api
    client.put("/users/gowtham/preferences", json=VALID)
    llm.responses.append(json.dumps(QUEST))
    qid = client.post("/users/gowtham/quests").json()["id"]
    assert client.post(f"/users/gowtham/quests/{qid}/feedback", json={"completed": True}).status_code == 422
    assert client.post("/users/gowtham/quests/999/feedback", json={"completed": False}).status_code == 404
    assert client.post(f"/users/someone_else/quests/{qid}/feedback", json={"completed": False}).status_code == 404


def test_llm_failure_returns_502(api):
    client, llm = api
    client.put("/users/gowtham/preferences", json=VALID)
    llm.responses += ["x", "y", "z"]
    assert client.post("/users/gowtham/quests").status_code == 502


# ---------------------------------------------------------------------------
# Robust parsing of real-world model output
# ---------------------------------------------------------------------------

def test_parses_after_visible_thinking_with_braces():
    raw = (
        "<thought>The user likes {nature}. Maybe {\"title\": \"draft\"} ... let me refine.</thought>\n"
        "Here is your quest:\n```json\n" + json.dumps(QUEST) + "\n```\nEnjoy!"
    )
    assert parse_quest(raw).title == QUEST["title"]


def test_last_valid_object_wins():
    raw = json.dumps({"title": "x"}) + "\n" + json.dumps(QUEST)
    assert parse_quest(raw).title == QUEST["title"]


def test_unwraps_quest_key():
    assert parse_quest(json.dumps({"quest": QUEST})).title == QUEST["title"]


def test_client_handles_list_content_and_empty(monkeypatch):
    body = {"choices": [{"message": {"content": [{"type": "text", "text": "{\"a\": 1}"}]}, "finish_reason": "stop"}]}
    monkeypatch.setattr("backend.llm.requests.post", lambda *a, **k: FakeResp(200, body))
    assert GemmaClient(base_url="https://x.test", api_key="k").complete("p") == '{"a": 1}'

    empty = {"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
    monkeypatch.setattr("backend.llm.requests.post", lambda *a, **k: FakeResp(200, empty))
    with pytest.raises(LLMError, match="GEMMA_MAX_TOKENS"):
        GemmaClient(base_url="https://x.test", api_key="k").complete("p")


def test_client_sends_large_token_budget(monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(json)
        return FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("backend.llm.requests.post", fake_post)
    GemmaClient(base_url="https://x.test", api_key="k").complete("p")
    assert seen["max_tokens"] >= 4096


# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------

from backend.llm import LLMTimeout  # noqa: E402


class FlakyLLM(FakeLLM):
    """Raises LLMTimeout for the first `n` calls, then behaves like FakeLLM."""

    def __init__(self, n, *responses):
        super().__init__(*responses)
        self.timeouts_left = n

    def complete(self, prompt, *, temperature=0.9):
        if self.timeouts_left:
            self.timeouts_left -= 1
            self.prompts.append(prompt)
            raise LLMTimeout("Gemma didn't answer within 180s")
        return super().complete(prompt, temperature=temperature)


def test_retries_once_after_timeout():
    llm = FlakyLLM(1, json.dumps(QUEST))
    assert generate_quest(PROFILE, llm=llm).title == QUEST["title"]
    assert len(llm.prompts) == 2


def test_timeout_does_not_use_up_answer_attempts():
    llm = FlakyLLM(1, "not json", "still not json", json.dumps(QUEST))
    assert generate_quest(PROFILE, llm=llm).title == QUEST["title"]


def test_gives_up_after_two_timeouts():
    with pytest.raises(LLMTimeout):
        generate_quest(PROFILE, llm=FlakyLLM(2, json.dumps(QUEST)))


def test_time_budget_stops_retries(monkeypatch):
    monkeypatch.setenv("GEMMA_TIME_BUDGET", "0")
    llm = FakeLLM("nope", "nope", "nope")
    with pytest.raises(LLMError, match="1 attempt"):
        generate_quest(PROFILE, llm=llm)
    assert len(llm.prompts) == 1


def test_client_maps_timeout_and_splits_timeouts(monkeypatch):
    import requests

    seen = {}

    def slow_post(url, json, headers, timeout):
        seen["timeout"] = timeout
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr("backend.llm.requests.post", slow_post)
    with pytest.raises(LLMTimeout, match="GEMMA_TIMEOUT"):
        GemmaClient(base_url="https://x.test", api_key="k").complete("p")
    assert seen["timeout"] == (10, 180)


def test_reasoning_effort_is_optional_and_dropped_if_unsupported(monkeypatch):
    bodies = []

    def fake_post(url, json, headers, timeout):
        bodies.append(dict(json))
        if "reasoning_effort" in json:
            return FakeResp(400, {"error": {"message": "Unknown field reasoning_effort"}})
        return FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("backend.llm.requests.post", fake_post)
    assert GemmaClient(base_url="https://x.test", api_key="k").complete("p") == "ok"
    assert "reasoning_effort" not in bodies[-1] and len(bodies) == 1

    monkeypatch.setenv("GEMMA_REASONING_EFFORT", "low")
    client = GemmaClient(base_url="https://x.test", api_key="k")
    assert client.complete("p") == "ok"
    assert bodies[-2]["reasoning_effort"] == "low" and "reasoning_effort" not in bodies[-1]
    assert client.reasoning_effort is None  # not sent again


def test_api_reports_timeout_as_502(api):
    client, _ = api
    from backend.main import app, get_llm

    app.dependency_overrides[get_llm] = lambda: FlakyLLM(5)
    client.put("/users/gowtham/preferences", json=VALID)
    r = client.post("/users/gowtham/quests")
    assert r.status_code == 502 and "didn't answer" in r.json()["detail"]
