"""The feedback loop: ratings -> learned taste -> prompt, examples and validation."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app, get_llm, get_retriever
from backend.quest_generator import build_prompt, generate_quest
from backend.schemas import FeedbackIn, PreferencesIn, Quest, QuestExample
from backend.taste import conflicts_with_taste, learn_taste, rerank_examples, taste_block


def quest(title, tags, minutes=15, difficulty="easy"):
    return Quest(
        title=f"Quest {title}", summary="Do a small thing outside for a while.", steps=["Go outside"],
        estimated_minutes=minutes, difficulty=difficulty, energy_required=2, tags=tags,
    )


def fb(rating=None, completed=True, minutes=None, comment=""):
    return FeedbackIn(completed=completed, rating=rating, time_logged_minutes=minutes, comment=comment)


PREFS = PreferencesIn(interests=["nature", "photography"])


def test_empty_history_learns_nothing():
    taste = learn_taste([])
    assert taste.is_empty
    assert "first quest" in build_prompt(PREFS, taste=taste)


def test_learns_liked_and_disliked_tags_difficulty_and_time():
    taste = learn_taste([
        (quest("Bird Count", ["birds", "nature"], minutes=10), fb(5, minutes=20, comment="loved the robins")),
        (quest("Tree Bark Rubbing", ["trees", "nature"], minutes=10), fb(4, minutes=15)),
        (quest("Street Selfie Run", ["photography", "urban"], difficulty="challenging"), fb(1)),
        (quest("Crowd Portraits", ["photography", "urban", "social"], difficulty="challenging"),
         fb(None, completed=False, comment="too awkward")),
    ])
    assert taste.rated == 4 and taste.completed == 3 and taste.not_finished == 1
    assert "nature" in taste.liked_tags and "birds" in taste.liked_tags
    assert {"photography", "urban"} <= set(taste.disliked_tags)
    assert taste.liked_difficulty == ["easy"] and taste.disliked_difficulty == ["challenging"]
    assert taste.time_ratio == 1.75
    block = taste_block(taste)
    assert "photography" in block and "longer than estimated" in block and "loved the robins" in block


def test_one_middling_rating_is_not_a_pattern():
    taste = learn_taste([(quest("Park Loop", ["walking"]), fb(4))])
    assert taste.liked_tags == [] and taste.disliked_tags == []


def test_often_unfinished_is_noticed():
    rated = [(quest(f"Q{i}", ["x"]), fb(None, completed=False)) for i in range(3)]
    rated.append((quest("Q9", ["y"]), fb(3)))
    assert "often don't finish" in taste_block(learn_taste(rated))


def test_conflict_and_rerank():
    taste = learn_taste([
        (quest("A", ["photography", "urban"]), fb(1)),
        (quest("B", ["birds", "nature"]), fb(5)),
    ])
    assert conflicts_with_taste(quest("C", ["photography", "urban", "running"]), taste) == ["photography", "urban"]
    assert conflicts_with_taste(quest("D", ["photography", "urban", "birds"]), taste) == []  # has a liked tag
    examples = [
        QuestExample(quest_text="urban photo walk", category="photography", duration_minutes=15,
                     difficulty="easy", tags=["urban"]),
        QuestExample(quest_text="pond watch", category="nature", duration_minutes=15, difficulty="easy",
                     tags=["birds"]),
        QuestExample(quest_text="bench sketch", category="art", duration_minutes=15, difficulty="easy", tags=[]),
    ]
    assert [e.quest_text for e in rerank_examples(examples, taste, 2)] == ["pond watch", "bench sketch"]


class ScriptedLLM:
    model = "scripted"

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def complete(self, prompt, *, temperature=0.9):
        self.prompts.append(prompt)
        return self.answers.pop(0)


def answer(title, tags, minutes=12):
    return json.dumps({
        "title": title, "summary": "Head outside and do this small thing right now.",
        "steps": ["Step outside", "Do it"], "estimated_minutes": minutes, "difficulty": "easy",
        "energy_required": 2, "tags": tags, "weather_backup": "Use a covered spot",
    })


def test_generator_rejects_quest_built_on_disliked_tags():
    taste = learn_taste([(quest("A", ["photography", "urban"]), fb(1)), (quest("B", ["photography", "urban"]), fb(2))])
    llm = ScriptedLLM([answer("Neon Snaps", ["photography", "urban"]), answer("Pond Ripples", ["nature", "water"])])
    q = generate_quest(PREFS, taste=taste, llm=llm)
    assert q.title == "Pond Ripples"
    assert "consistently rates low" in llm.prompts[1]


# ---------------------------------------------------------------------------
# End to end through the API: rate quests -> the next generation changes
# ---------------------------------------------------------------------------

@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_feedback_loop_end_to_end(api):
    llm = ScriptedLLM([
        answer("Neon Snaps", ["photography", "urban"]),
        answer("Street Sketch", ["art", "urban"]),
        # third request: first answer ignores the feedback and gets rejected, then a different one
        answer("Graffiti Hunt", ["photography", "urban"]),
        answer("Pond Ripples", ["nature", "water"]),
    ])
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_retriever] = lambda: None
    s = api.post("/auth/signup", json={"email": "loop@example.com", "password": "longpassword"}).json()
    uid, h = s["user"]["id"], {"Authorization": f"Bearer {s['token']}"}
    assert api.put(f"/users/{uid}/preferences", headers=h,
                   json={"interests": ["photography", "nature"]}).status_code == 200

    first = api.post(f"/users/{uid}/quests", headers=h, json={"group_size": "pair"}).json()
    assert "first quest" in llm.prompts[-1]
    assert "Works for this group right now: pair" in llm.prompts[-1]
    api.post(f"/users/{uid}/quests/{first['id']}/feedback", headers=h,
             json={"completed": True, "rating": 1, "comment": "hate taking photos of strangers"})

    second = api.post(f"/users/{uid}/quests", headers=h, json={}).json()
    api.post(f"/users/{uid}/quests/{second['id']}/feedback", headers=h,
             json={"completed": False, "comment": "nope"})

    third = api.post(f"/users/{uid}/quests", headers=h, json={"group_size": "solo"})
    assert third.status_code == 201, third.text
    assert third.json()["quest"]["title"] == "Pond Ripples"
    prompt = llm.prompts[-2]  # the first try of the third quest
    assert "What their feedback shows overall" in prompt
    assert "rate low or abandon: photography, urban" in prompt
    assert "hate taking photos of strangers" in prompt
    assert "DISLIKED" in prompt  # the per-quest history block is there too
    assert "consistently rates low" in llm.prompts[-1]  # the retry explains why
