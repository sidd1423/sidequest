"""Per-user fine-tuned quest models (backend/personal_model.py) with a fake Tinker."""

import json
import os
import sqlite3
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend import personal_model as pm
from backend.llm import LLMError
from backend.schemas import FeedbackIn

from .test_api import VALID
from .test_quests import DIFFERENT_QUEST, QUEST, FakeLLM

try:  # the real tinker.types if installed (validates our Datum/params); a stub otherwise
    from tinker import types as TYPES
except ImportError:  # pragma: no cover
    class _MI:
        def __init__(self, tokens):
            self.tokens = list(tokens)

        @classmethod
        def from_ints(cls, tokens):
            return cls(tokens)

    TYPES = SimpleNamespace(
        ModelInput=_MI,
        Datum=lambda model_input, loss_fn_inputs: SimpleNamespace(model_input=model_input,
                                                                 loss_fn_inputs=loss_fn_inputs),
        AdamParams=lambda **kw: SimpleNamespace(**kw),
        SamplingParams=lambda **kw: SimpleNamespace(**kw),
    )


def _values(x):
    return list(x.tolist()) if hasattr(x, "tolist") else list(x)


def _tokens(model_input):
    if hasattr(model_input, "to_ints"):
        return model_input.to_ints()
    return list(model_input.tokens)


# ---------------------------------------------------------------------------
# A fake Tinker: character-level tokenizer, records every call
# ---------------------------------------------------------------------------

class FakeTokenizer:
    eos_token = "<|im_end|>"

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False, enable_thinking=True):
        text = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
        if add_generation_prompt:
            text += "<|im_start|>assistant\n"
        return text

    def encode(self, text, add_special_tokens=False):
        return [ord(c) for c in text]

    def decode(self, tokens, skip_special_tokens=True):
        return "".join(chr(t) for t in tokens)


def done(value):
    f = Future()
    f.set_result(value)
    return f


class FakeTrainingClient:
    def __init__(self, tinker):
        self.tinker = tinker

    def get_tokenizer(self):
        return FakeTokenizer()

    def forward(self, data, loss_fn):
        self.tinker.calls.append(("forward", loss_fn, data))
        outs = [{"logprobs": [-1.0] * len(_values(d.loss_fn_inputs["target_tokens"]))} for d in data]
        return done(SimpleNamespace(loss_fn_outputs=outs, metrics={}))

    def forward_backward(self, data, loss_fn):
        self.tinker.calls.append(("forward_backward", loss_fn, data))
        return done(SimpleNamespace(loss_fn_outputs=[], metrics={"loss:sum": 1.5}))

    def optim_step(self, params):
        self.tinker.calls.append(("optim_step", params))
        return done(SimpleNamespace())

    def save_weights_for_sampler(self, name):
        self.tinker.saved.append(name)
        return done(SimpleNamespace(path=f"tinker://run/sampler_weights/{name}"))


class FakeSampler:
    def __init__(self, tinker, path):
        self.tinker, self.path = tinker, path

    def get_tokenizer(self):
        return FakeTokenizer()

    def sample(self, prompt, num_samples, sampling_params):
        self.tinker.sampled.append((self.path, FakeTokenizer().decode(_tokens(prompt))))
        if self.tinker.fail_sampling:
            raise RuntimeError("tinker is down")
        answer = self.tinker.answers.pop(0) if self.tinker.answers else json.dumps(QUEST)
        return done(SimpleNamespace(sequences=[SimpleNamespace(tokens=FakeTokenizer().encode(answer),
                                                               stop_reason="stop")]))


class FakeTinker:
    def __init__(self):
        self.calls, self.saved, self.sampled, self.deleted, self.answers = [], [], [], [], []
        self.fail_sampling = False
        self.trainings = []

    def create_lora_training_client(self, base_model, rank, user_metadata=None):
        self.trainings.append((base_model, rank, user_metadata))
        return FakeTrainingClient(self)

    def create_sampling_client(self, model_path):
        return FakeSampler(self, model_path)

    def create_rest_client(self):
        return SimpleNamespace(delete_checkpoint_from_tinker_path=lambda p: done(self.deleted.append(p)))


@pytest.fixture()
def tinker(monkeypatch):
    fake = FakeTinker()
    monkeypatch.setenv("TINKER_API_KEY", "test-key")
    monkeypatch.setenv("PERSONAL_TRAIN_STEPS", "2")
    pm.set_service_factory(lambda: fake, TYPES)
    monkeypatch.setattr(pm, "TRAIN_INLINE", True)
    yield fake
    pm.set_service_factory(None)


def rated_quest(user, title, fb, days_ago=0.0):
    """A quest in sidequest.db with feedback given `days_ago`."""
    from backend import db

    db.init_db()
    rec = db.add_quest(user, pm.Quest.model_validate({**QUEST, "title": title}), model="fake-gemma")
    db.set_feedback(user, rec.id, fb)
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with db.connect() as conn:
        conn.execute("UPDATE quests SET feedback_at = ?, created_at = ? WHERE id = ?", (when, when, rec.id))
    return rec.id


def save_prefs(user="ana"):
    from backend import db
    from backend.schemas import PreferencesIn

    db.init_db()
    db.upsert_preferences(user, PreferencesIn.model_validate(VALID))


LOVED = FeedbackIn(completed=True, rating=5, time_logged_minutes=12)
OK = FeedbackIn(completed=True, rating=3, time_logged_minutes=12)
HATED = FeedbackIn(completed=True, rating=1, comment="boring", time_logged_minutes=12)
GAVE_UP = FeedbackIn(completed=False)
GAVE_UP_LIKED = FeedbackIn(completed=False, rating=5, time_logged_minutes=4)


# ---------------------------------------------------------------------------
# Rewards and recency
# ---------------------------------------------------------------------------

def test_rewards_good_bad_and_unfinished():
    assert pm.reward(LOVED) == 1.0
    assert pm.reward(FeedbackIn(completed=True, rating=4)) > pm.reward(OK) > 0
    assert pm.reward(HATED) == -1.0
    assert pm.reward(GAVE_UP) < 0                       # walked away without a rating
    assert pm.reward(GAVE_UP_LIKED) > 0                 # didn't finish but loved it
    assert pm.reward(GAVE_UP_LIKED) < pm.reward(LOVED)  # finishing still counts for more
    assert pm.reward(FeedbackIn(completed=False, rating=3)) < 0


def test_recent_quests_weigh_more():
    assert pm.recency_weight(0, 0) == 1.0
    assert pm.recency_weight(14, 20, 14, 8) == pytest.approx(0.5)     # a fortnight old
    assert pm.recency_weight(30, 8, 14, 8) > pm.recency_weight(30, 16, 14, 8)  # more newer quests -> less
    assert pm.recency_weight(10, 30, 14, 8) > pm.recency_weight(20, 30, 14, 8)  # older -> less
    # rare quester: 10th-newest quest from yesterday still counts a lot
    assert pm.recency_weight(1, 10, 14, 8) > 0.9
    # frequent quester: a quest from today with 40 newer ones barely counts... unless days say otherwise
    assert pm.recency_weight(60, 40, 14, 8) < 0.06


def test_training_set_uses_stored_prompts_and_recency():
    save_prefs("ana")
    old = rated_quest("ana", "Old Loved Walk", LOVED, days_ago=30)
    new = rated_quest("ana", "New Hated Walk", HATED, days_ago=0)
    gave_up = rated_quest("ana", "Abandoned Walk", GAVE_UP, days_ago=1)
    pm.save_prompt(new, "ana", "PROMPT FOR NEW")
    examples = {e.app_quest_id: e for e in pm.training_set("ana")}

    assert examples[new].prompt == "PROMPT FOR NEW" and not examples[new].rebuilt_prompt
    assert examples[old].rebuilt_prompt and "## User profile" in examples[old].prompt
    assert examples[new].weight == 1.0 > examples[gave_up].weight > examples[old].weight
    assert examples[new].signal < 0 < examples[old].signal
    assert examples[gave_up].signal < 0 and examples[gave_up].outcome == "didn't finish"
    assert json.loads(examples[old].completion)["title"] == "Old Loved Walk"
    assert set(json.loads(examples[old].completion)) == set(pm.OUTPUT_FIELDS)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def test_train_user_reinforces_good_and_discourages_bad(tinker):
    save_prefs("ana")
    good = rated_quest("ana", "Loved Walk", LOVED)
    rated_quest("ana", "Hated Walk", HATED, days_ago=2)
    rated_quest("ana", "Abandoned Walk", GAVE_UP, days_ago=1)
    pm.save_prompt(good, "ana", "PROMPT FOR GOOD")

    res = pm.train_user("ana")
    assert res.trained and res.version == 1 and (res.positives, res.negatives) == (1, 2)
    assert tinker.trainings[0][0] == "Qwen/Qwen3.5-4B"
    assert "ana" not in json.dumps(tinker.trainings[0][2])  # user id isn't sent to Tinker

    ref = [c for c in tinker.calls if c[0] == "forward"]
    sft = [c for c in tinker.calls if c[0] == "forward_backward" and c[1] == "cross_entropy"]
    ppo = [c for c in tinker.calls if c[0] == "forward_backward" and c[1] == "ppo"]
    steps = [c for c in tinker.calls if c[0] == "optim_step"]
    assert len(ref) == 1 and len(ref[0][2]) == 2       # reference logprobs for the 2 bad quests
    assert len(sft) == len(ppo) == len(steps) == 2      # PERSONAL_TRAIN_STEPS=2

    [d] = sft[0][2]
    w = _values(d.loss_fn_inputs["weights"])
    prompt_len = len(FakeTokenizer().apply_chat_template(
        [{"role": "user", "content": "PROMPT FOR GOOD"}], add_generation_prompt=True))
    assert all(x == 0 for x in w[:prompt_len - 1])      # no loss on the prompt
    assert all(x > 0 for x in w[prompt_len - 1:])       # reinforce the loved quest
    answer = FakeTokenizer().decode(_values(d.loss_fn_inputs["target_tokens"])[prompt_len - 1:])
    assert answer.startswith('{"title": "Loved Walk"') and answer.endswith("<|im_end|>")

    for d in ppo[0][2]:
        assert set(d.loss_fn_inputs) == {"target_tokens", "logprobs", "advantages"}
        adv = _values(d.loss_fn_inputs["advantages"])
        assert min(adv) < 0 and max(adv) == 0           # pushed down, prompt masked
        assert len(adv) == len(_values(d.loss_fn_inputs["logprobs"])) == len(_values(d.loss_fn_inputs["target_tokens"]))

    # newer bad quest pushed harder than the older one
    by_strength = sorted(min(_values(d.loss_fn_inputs["advantages"])) for d in ppo[0][2])
    assert by_strength[0] < by_strength[1]

    st = pm.status("ana")
    assert st.state == "ready" and st.version == 1 and (st.reinforced, st.discouraged) == (1, 2)


def test_not_trained_without_enough_or_any_good_quests(tinker):
    save_prefs("ana")
    rated_quest("ana", "One", LOVED)
    assert not pm.train_user("ana").trained                       # needs 3
    rated_quest("bo", "Walk A", HATED), rated_quest("bo", "Walk B", GAVE_UP), rated_quest("bo", "Walk C", HATED)
    save_prefs("bo")
    res = pm.train_user("bo")
    assert not res.trained and "nothing to imitate" in res.reason
    assert tinker.trainings == []


def test_broken_new_adapter_keeps_the_previous_one(tinker):
    save_prefs("ana")
    for i in range(3):
        rated_quest("ana", f"Walk {i}", LOVED)
    assert pm.train_user("ana").trained
    first = pm.status("ana")
    rated_quest("ana", "Walk 3", LOVED)
    tinker.answers = ["this is not json"]
    res = pm.train_user("ana")
    assert not res.trained and "valid quest" in res.reason
    after = pm.status("ana")
    assert after.state == "ready" and after.version == first.version == 1 and after.last_error
    assert tinker.deleted == ["tinker://run/sampler_weights/" + tinker.saved[-1]]


def test_retrain_replaces_and_deletes_the_old_adapter(tinker):
    save_prefs("ana")
    for i in range(3):
        rated_quest("ana", f"Walk {i}", LOVED)
    pm.train_user("ana")
    pm.train_user("ana")
    assert pm.status("ana").version == 2
    assert tinker.deleted == [f"tinker://run/sampler_weights/{tinker.saved[0]}"]


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------

def _api(llm):
    from fastapi.testclient import TestClient

    from backend.main import app, get_llm, get_retriever

    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None
    return TestClient(app), app


def test_api_trains_after_feedback_and_then_uses_the_personal_model(tinker, monkeypatch):
    monkeypatch.setenv("PERSONAL_RETRAIN_EVERY", "2")
    titles = [f"Gemma Quest {i}" for i in range(3)]
    gemma = FakeLLM(*[json.dumps({**QUEST, "title": t, "tags": ["outdoors", f"t{i}"]}) for i, t in enumerate(titles)])
    client, app = _api(gemma)
    try:
        with client as c:
            c.put("/users/ana/preferences", json=VALID)
            assert c.get("/users/ana/model").json()["state"] == "collecting"
            ratings = [{"completed": True, "rating": 5, "time_logged_minutes": 10},
                       {"completed": False},
                       {"completed": True, "rating": 2, "time_logged_minutes": 10}]
            for fb in ratings:
                qid = c.post("/users/ana/quests").json()["id"]
                assert c.post(f"/users/ana/quests/{qid}/feedback", json=fb).status_code == 200
            st = c.get("/users/ana/model").json()
            assert st["state"] == "ready" and st["version"] == 1, st
            assert (st["reinforced"], st["discouraged"]) == (1, 2)
            assert st["feedback_until_retrain"] == 2

            # the stored prompts were the training input
            ref_prompts = [FakeTokenizer().decode(_tokens(d.model_input)) for d in
                           next(c_ for c_ in tinker.calls if c_[0] == "forward")[2]]
            assert any("## User profile" in p for p in ref_prompts)

            # next quest comes from ana's own model
            tinker.answers = [json.dumps({**DIFFERENT_QUEST, "title": "Personal Quest"})]
            new = c.post("/users/ana/quests").json()
            assert new["quest"]["title"] == "Personal Quest"
            assert new["model"].startswith("tinker:Qwen/Qwen3.5-4B:personal-v1")
            assert len(gemma.prompts) == 3                       # Gemma wasn't asked

            # Tinker down -> Gemma answers instead
            tinker.fail_sampling = True
            gemma.responses.append(json.dumps({**QUEST, "title": "Gemma Rescue"}))
            new = c.post("/users/ana/quests").json()
            assert new["quest"]["title"] == "Gemma Rescue" and new["model"] == "fake-gemma"
            tinker.fail_sampling = False

            # 2 more feedbacks -> retrain to v2
            for qid in (c.get("/users/ana/quests").json()[0]["id"], c.get("/users/ana/quests").json()[1]["id"]):
                c.post(f"/users/ana/quests/{qid}/feedback",
                       json={"completed": True, "rating": 4, "time_logged_minutes": 9})
            assert c.get("/users/ana/model").json()["version"] == 2

            # other users don't get ana's model
            c.put("/users/bob/preferences", json=VALID)
            gemma.responses.append(json.dumps({**QUEST, "title": "Bo Quest"}))
            r = c.post("/users/bob/quests")
            assert r.status_code == 201, r.text
            assert r.json()["model"] == "fake-gemma"
    finally:
        app.dependency_overrides.clear()


def test_api_manual_train_and_account_deletion(tinker, monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    client, app = _api(FakeLLM(*[json.dumps({**QUEST, "title": f"Quest {i}"}) for i in range(3)]))
    try:
        with client as c:
            s = c.post("/auth/signup", json={"name": "Ana", "email": "ana@example.com",
                                             "password": "long-password"}).json()
            h, uid = {"Authorization": f"Bearer {s['token']}"}, s["user"]["id"]
            c.put(f"/users/{uid}/preferences", json=VALID, headers=h)
            assert c.post(f"/users/{uid}/model/train", headers=h).status_code == 409
            monkeypatch.setenv("PERSONAL_RETRAIN_EVERY", "99")
            monkeypatch.setenv("PERSONAL_MIN_FEEDBACK", "99")   # no automatic training
            for _ in range(3):
                qid = c.post(f"/users/{uid}/quests", headers=h).json()["id"]
                c.post(f"/users/{uid}/quests/{qid}/feedback", headers=h,
                       json={"completed": True, "rating": 5, "time_logged_minutes": 8})
            assert c.get(f"/users/{uid}/model", headers=h).json()["state"] == "collecting"
            monkeypatch.setenv("PERSONAL_MIN_FEEDBACK", "3")
            r = c.post(f"/users/{uid}/model/train", headers=h)
            assert r.status_code == 202 and r.json()["state"] == "ready"
            assert c.request("DELETE", "/auth/me", headers=h, json={"password": "long-password"}).status_code == 204
    finally:
        app.dependency_overrides.clear()
    assert tinker.deleted == [f"tinker://run/sampler_weights/{tinker.saved[0]}"]
    conn = sqlite3.connect(os.environ["PERSONAL_MODELS_PATH"])
    assert conn.execute("select count(*) from personal_models").fetchone()[0] == 0
    assert conn.execute("select count(*) from quest_prompts").fetchone()[0] == 0
    conn.close()


def test_off_without_tinker_key():
    client, app = _api(FakeLLM(json.dumps(QUEST)))
    try:
        with client as c:
            c.put("/users/ana/preferences", json=VALID)
            assert c.get("/users/ana/model").json() == {**c.get("/users/ana/model").json(),
                                                         "enabled": False, "state": "off"}
            assert c.post("/users/ana/model/train").status_code == 503
            assert c.post("/users/ana/quests").json()["model"] == "fake-gemma"
    finally:
        app.dependency_overrides.clear()


def test_fallback_wrapper_sticks_to_gemma_after_a_failure(tinker):
    tinker.fail_sampling = True
    gemma = FakeLLM("a", "b")
    llm = pm.PersonalWithFallback(pm.TinkerQuestClient("tinker://x", 1), gemma)
    assert llm.model.startswith("tinker:")
    assert llm.complete("p1") == "a" and llm.model == "fake-gemma" and "tinker is down" in llm.fell_back_because
    tinker.fail_sampling = False
    assert llm.complete("p2") == "b"           # doesn't flip back mid-quest
    with pytest.raises(LLMError):
        tinker.fail_sampling = True
        pm.TinkerQuestClient("tinker://x", 1).complete("p")


def test_training_runs_in_the_background(tinker, monkeypatch):
    import threading

    monkeypatch.setattr(pm, "TRAIN_INLINE", False)
    save_prefs("ana")
    for i in range(3):
        rated_quest("ana", f"Walk {i}", LOVED)
    gate = threading.Event()
    real_train = pm.train_user
    monkeypatch.setattr(pm, "train_user", lambda u, p=None: (gate.wait(5), real_train(u, p))[1])
    assert pm.note_feedback("ana")                  # returns right away
    assert pm.status("ana").state == "training"
    assert pm.schedule("ana")                       # feedback mid-training -> one more run queued
    gate.set()
    pm._executor.shutdown(wait=True)
    pm._executor = None
    assert pm.status("ana").state == "ready" and pm.status("ana").version == 2
