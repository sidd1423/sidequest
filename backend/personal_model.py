"""Per-user fine-tuned quest models, trained with Tinker (https://thinkingmachines.ai/tinker).

Every user gets their OWN small LoRA adapter that learns from how their past
quests went - not just in-context hints in the prompt, but actual weight
updates:

* Loved quests (completed, rated 4-5) are reinforced: supervised fine-tuning
  (cross-entropy) on "this prompt -> this quest", weighted by how good it was.
* Disliked, abandoned or "didn't finish" quests are pushed DOWN: a PPO
  policy-gradient step with a negative advantage. PPO's ratio clipping keeps
  this unlikelihood bounded, so a few bad quests can't wreck the model.
* Recent quests count more: each quest's weight halves every
  PERSONAL_HALF_LIFE_DAYS days and every PERSONAL_HALF_LIFE_QUESTS newer quests
  (whichever decays slower), so a user who quests rarely isn't forgotten and
  a user whose taste changed is followed quickly.

Tinker can't fine-tune Gemma (no Gemma in its model list as of 2026-10), so
the personal model is a LoRA on PERSONAL_BASE_MODEL (default Qwen/Qwen3.5-4B).
Gemma stays the fallback: for new users (fewer than PERSONAL_MIN_FEEDBACK
rated quests), when Tinker isn't configured, and whenever the personal model
fails or times out.

Training runs in a background thread after every PERSONAL_RETRAIN_EVERY new
feedbacks (never blocks the API). Each run trains a fresh adapter on the
user's whole recency-weighted history - weights change as quests age, so
retraining from the base model keeps it simple and reproducible. A new
adapter is only used if a test quest from it parses as a valid quest;
otherwise the previous one stays live.

Storage: data/personal_models.db (PERSONAL_MODELS_PATH)
  quest_prompts    the exact prompt each quest was generated from (training input)
  personal_models  one row per user: Tinker sampler checkpoint, version, status

Enable by setting TINKER_API_KEY (and `pip install tinker`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .llm import LLMClient, LLMError, LLMTimeout
from .schemas import FeedbackIn, PreferencesIn, Quest

log = logging.getLogger("sidequest.personal")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "personal_models.db"

DEFAULT_BASE_MODEL = "Qwen/Qwen3.5-4B"

# The quest fields the model is asked to output (quest_generator.QUEST_JSON_SHAPE).
OUTPUT_FIELDS = ("title", "summary", "steps", "estimated_minutes", "difficulty", "energy_required", "tags",
                 "accessibility_notes", "weather_backup")

SCHEMA = """
CREATE TABLE IF NOT EXISTS quest_prompts (
    app_quest_id  INTEGER PRIMARY KEY,           -- quests.id in sidequest.db
    user_id       TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS quest_prompts_user_idx ON quest_prompts (user_id);
CREATE TABLE IF NOT EXISTS personal_models (
    user_id        TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'none',  -- none | training | ready | failed
    base_model     TEXT,
    sampler_path   TEXT,                          -- tinker://... sampler weights now in use
    version        INTEGER NOT NULL DEFAULT 0,
    trained_at     TEXT,
    data_cutoff    TEXT,                          -- newest feedback_at included in that training
    examples       INTEGER NOT NULL DEFAULT 0,
    positives      INTEGER NOT NULL DEFAULT 0,
    negatives      INTEGER NOT NULL DEFAULT 0,
    last_loss      REAL,
    last_error     TEXT,
    updated_at     TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, default))


def is_enabled() -> bool:
    """On when TINKER_API_KEY is set (PERSONAL_MODELS=off turns it off anyway)."""
    if (os.getenv("PERSONAL_MODELS") or "").strip().lower() in ("0", "off", "false", "no"):
        return False
    return bool(os.getenv("TINKER_API_KEY"))


def base_model() -> str:
    return os.getenv("PERSONAL_BASE_MODEL") or DEFAULT_BASE_MODEL


def min_feedback() -> int:
    return max(1, _env_int("PERSONAL_MIN_FEEDBACK", 3))


def retrain_every() -> int:
    return max(1, _env_int("PERSONAL_RETRAIN_EVERY", 3))


def models_path() -> Path:
    return Path(os.getenv("PERSONAL_MODELS_PATH") or DEFAULT_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or models_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def init(path: Path | None = None) -> None:
    conn = _connect(path)
    conn.close()
    # A server restart kills any training thread - don't leave users stuck on "training".
    conn = _connect(path)
    try:
        conn.execute("UPDATE personal_models SET status = CASE WHEN sampler_path IS NULL THEN 'none' ELSE 'ready' "
                     "END WHERE status = 'training'")
        conn.commit()
    finally:
        conn.close()
    if is_enabled():
        log.info("Personal models ON: per-user LoRA on %s via Tinker (first after %d rated quests, "
                 "retrain every %d)", base_model(), min_feedback(), retrain_every())


# ---------------------------------------------------------------------------
# Prompts each quest was generated from
# ---------------------------------------------------------------------------

def save_prompt(app_quest_id: int, user_id: str, prompt: str, path: Path | None = None) -> None:
    conn = _connect(path)
    try:
        conn.execute(
            """INSERT INTO quest_prompts (app_quest_id, user_id, prompt, created_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(app_quest_id) DO UPDATE SET prompt = excluded.prompt""",
            (app_quest_id, user_id, prompt, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def delete_quest(app_quest_id: int, path: Path | None = None) -> int:
    """Forget the prompt of a quest that was deleted (never started)."""
    p = Path(path or models_path())
    if not p.exists():
        return 0
    conn = _connect(p)
    try:
        n = conn.execute("DELETE FROM quest_prompts WHERE app_quest_id = ?", (app_quest_id,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def _prompts(user_id: str, path: Path | None = None) -> dict[int, str]:
    conn = _connect(path)
    try:
        return {r["app_quest_id"]: r["prompt"] for r in
                conn.execute("SELECT app_quest_id, prompt FROM quest_prompts WHERE user_id = ?", (user_id,))}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Training data: rewards + recency weights
# ---------------------------------------------------------------------------

# How good an outcome was, -1 (never again) .. +1 (more like this).
COMPLETED_REWARD = {5: 1.0, 4: 0.6, 3: 0.1, 2: -0.5, 1: -1.0}
UNFINISHED_REWARD = {5: 0.5, 4: 0.2, 3: -0.3, 2: -0.8, 1: -1.0}
UNFINISHED_UNRATED_REWARD = -0.6   # walked away without saying why: probably not appealing
COMPLETED_UNRATED_REWARD = 0.4
MIN_WEIGHT = 0.03                  # older than this (after decay) = no longer trained on


def reward(fb: FeedbackIn) -> float:
    if fb.completed:
        return COMPLETED_REWARD.get(fb.rating, COMPLETED_UNRATED_REWARD) if fb.rating else COMPLETED_UNRATED_REWARD
    if fb.rating:
        return UNFINISHED_REWARD[fb.rating]
    return UNFINISHED_UNRATED_REWARD


def outcome(fb: FeedbackIn) -> str:
    if not fb.completed:
        return "didn't finish" + (f", rated {fb.rating}" if fb.rating else "")
    return f"completed, rated {fb.rating}" if fb.rating else "completed"


def recency_weight(age_days: float, newer_quests: int, half_life_days: float | None = None,
                   half_life_quests: float | None = None) -> float:
    """1.0 for the newest quest, halving every `half_life_days` days AND every
    `half_life_quests` newer quests - whichever decays SLOWER wins, so both
    rare and frequent questers keep a useful history."""
    hd = half_life_days or _env_float("PERSONAL_HALF_LIFE_DAYS", 14.0)
    hq = half_life_quests or _env_float("PERSONAL_HALF_LIFE_QUESTS", 8.0)
    return 0.5 ** min(max(age_days, 0.0) / hd, max(newer_quests, 0) / hq)


@dataclass
class Example:
    app_quest_id: int
    prompt: str
    completion: str          # the quest as the JSON the model should (or shouldn't) write
    reward: float            # -1 .. 1
    weight: float            # recency, 0 .. 1
    outcome: str
    feedback_at: str
    rebuilt_prompt: bool = False

    @property
    def signal(self) -> float:
        return self.reward * self.weight


def completion_json(quest: Quest) -> str:
    data = quest.model_dump(mode="json")
    return json.dumps({k: data[k] for k in OUTPUT_FIELDS}, ensure_ascii=False)


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def rated_rows(user_id: str, limit: int) -> list[sqlite3.Row]:
    from . import db

    with db.connect() as conn:
        return conn.execute(
            """SELECT id, data, feedback, created_at, feedback_at FROM quests
               WHERE user_id = ? AND feedback IS NOT NULL
               ORDER BY feedback_at DESC, id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()


def training_set(user_id: str, now: datetime | None = None, path: Path | None = None) -> list[Example]:
    """Every rated quest of this user (newest first) with its reward and recency weight.

    The input is the exact prompt the quest was generated from. Quests from
    before prompts were stored get a prompt rebuilt from the user's current
    preferences (good enough - they still teach what this user likes)."""
    from . import db
    from .quest_generator import build_prompt

    now = now or datetime.now(timezone.utc)
    rows = rated_rows(user_id, _env_int("PERSONAL_MAX_EXAMPLES", 64))
    prompts = _prompts(user_id, path)
    fallback_prompt: str | None = None
    examples: list[Example] = []
    for i, r in enumerate(rows):
        try:
            quest = Quest.model_validate_json(r["data"])
            fb = FeedbackIn.model_validate_json(r["feedback"])
        except ValueError:
            continue
        when = _parse_time(r["feedback_at"]) or _parse_time(r["created_at"]) or now
        weight = recency_weight((now - when).total_seconds() / 86400, i)
        if weight < MIN_WEIGHT:
            continue
        prompt = prompts.get(r["id"])
        rebuilt = prompt is None
        if prompt is None:
            if fallback_prompt is None:
                profile = db.get_preferences(user_id)
                if profile is None:
                    continue
                prefs = PreferencesIn.model_validate(
                    profile.model_dump(exclude={"user_id", "created_at", "updated_at"}))
                fallback_prompt = build_prompt(prefs)
            prompt = fallback_prompt
        examples.append(Example(r["id"], prompt, completion_json(quest), reward(fb), weight, outcome(fb),
                                r["feedback_at"] or r["created_at"], rebuilt))
    return examples


# ---------------------------------------------------------------------------
# Tinker
# ---------------------------------------------------------------------------

_service_lock = threading.Lock()
_service: Any = None
_service_factory: Callable[[], Any] | None = None   # tests swap in a fake Tinker
_types_override: Any = None
_tokenizers: dict[str, Any] = {}
_samplers: dict[str, Any] = {}


def set_service_factory(factory: Callable[[], Any] | None, types_module: Any = None) -> None:
    """Tests: use a fake Tinker ServiceClient + `tinker.types` (None = the real ones)."""
    global _service_factory, _service, _types_override
    with _service_lock:
        _service_factory, _service, _types_override = factory, None, types_module
        _tokenizers.clear()
        _samplers.clear()


def service() -> Any:
    global _service
    with _service_lock:
        if _service is None:
            if _service_factory is not None:
                _service = _service_factory()
            else:
                try:
                    import tinker
                except ImportError as exc:
                    raise LLMError("TINKER_API_KEY is set but the tinker package isn't installed - "
                                   "run: pip install tinker") from exc
                _service = tinker.ServiceClient()  # reads TINKER_API_KEY
        return _service


def _types() -> Any:
    if _types_override is not None:
        return _types_override
    from tinker import types

    return types


def _model_input(tokens: list[int]) -> Any:
    return _types().ModelInput.from_ints(tokens=list(tokens))


def _datum(tokens: list[int], **loss_fn_inputs: list) -> Any:
    return _types().Datum(model_input=_model_input(tokens), loss_fn_inputs=loss_fn_inputs)


def render_prompt(tokenizer: Any, prompt: str) -> str:
    """Chat-format the prompt exactly like at inference: one user message, no
    'thinking' (the quest JSON is the whole answer)."""
    messages = [{"role": "user", "content": prompt}]
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def _end_text(tokenizer: Any) -> str:
    """End-of-turn marker: <|im_end|> for ChatML models (Qwen), else the tokenizer's EOS."""
    try:
        if "<|im_end|>" in tokenizer.get_vocab():
            return "<|im_end|>"
    except Exception:  # noqa: BLE001 - not every tokenizer exposes its vocab
        pass
    return getattr(tokenizer, "eos_token", None) or "<|im_end|>"


def _stops(tokenizer: Any) -> list[str]:
    return list(dict.fromkeys(s for s in (_end_text(tokenizer), getattr(tokenizer, "eos_token", None)) if s))


def tokenize_example(tokenizer: Any, prompt: str, completion: str) -> tuple[list[int], list[int]]:
    """(prompt tokens, completion tokens incl. the end-of-turn token)."""
    prompt_text = render_prompt(tokenizer, prompt)
    full_text = None
    try:
        full_text = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}, {"role": "assistant", "content": completion}],
            tokenize=False, enable_thinking=False)
    except Exception:
        full_text = None
    if full_text and full_text.startswith(prompt_text) and completion in full_text:
        answer_text = full_text[len(prompt_text):].rstrip("\n")
    else:  # template does something unusual (e.g. reformats past turns) - append the answer by hand
        answer_text = completion + _end_text(tokenizer)
    return (tokenizer.encode(prompt_text, add_special_tokens=False),
            tokenizer.encode(answer_text, add_special_tokens=False))


def _shift(prompt_tokens: list[int], answer_tokens: list[int], per_token: float,
           prompt_value: float = 0.0) -> tuple[list[int], list[int], list[float]]:
    """Input = all tokens but the last; targets = all but the first; one value per target."""
    full = prompt_tokens + answer_tokens
    values = [prompt_value] * (len(prompt_tokens) - 1) + [per_token] * len(answer_tokens)
    return full[:-1], full[1:], values


def _result(future: Any, timeout: float | None = None) -> Any:
    return future.result(timeout=timeout) if hasattr(future, "result") else future


def _tolist(x: Any) -> list[float]:
    if hasattr(x, "tolist"):
        return list(x.tolist())
    if hasattr(x, "data"):
        return list(x.data)
    return list(x)


# ---------------------------------------------------------------------------
# Training one user's model
# ---------------------------------------------------------------------------

class TrainingResult(BaseModel):
    trained: bool
    reason: str = ""
    version: int = 0
    sampler_path: str | None = None
    examples: int = 0
    positives: int = 0
    negatives: int = 0
    loss: float | None = None


def _safe_id(user_id: str) -> str:
    return "sq-" + hashlib.sha256(user_id.encode()).hexdigest()[:12]


def _registry(user_id: str, path: Path | None = None) -> dict | None:
    conn = _connect(path)
    try:
        r = conn.execute("SELECT * FROM personal_models WHERE user_id = ?", (user_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _update_registry(user_id: str, path: Path | None = None, **fields: Any) -> None:
    fields["updated_at"] = _now()
    conn = _connect(path)
    try:
        conn.execute("INSERT INTO personal_models (user_id, updated_at) VALUES (?, ?) "
                     "ON CONFLICT(user_id) DO NOTHING", (user_id, fields["updated_at"]))
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE personal_models SET {sets} WHERE user_id = ?", (*fields.values(), user_id))
        conn.commit()
    finally:
        conn.close()


def train_user(user_id: str, path: Path | None = None) -> TrainingResult:
    """Train a fresh personal LoRA for this user from all their rated quests.
    Synchronous (call it from a background thread); never raises."""
    examples = training_set(user_id, path=path)
    positives = [e for e in examples if e.signal > 0]
    negatives = [e for e in examples if e.signal < 0]
    if len(examples) < min_feedback():
        return TrainingResult(trained=False, reason=f"needs {min_feedback()} rated quests, has {len(examples)}",
                              examples=len(examples))
    if not positives:
        return TrainingResult(trained=False, reason="no quest went well yet - nothing to imitate",
                              examples=len(examples), negatives=len(negatives))

    prev = _registry(user_id, path) or {}
    version = int(prev.get("version") or 0) + 1
    data_cutoff = max(e.feedback_at for e in examples)
    _update_registry(user_id, path, status="training", last_error=None)
    started = time.monotonic()
    try:
        result = _train(user_id, examples, positives, negatives, version)
    except Exception as exc:  # noqa: BLE001 - a failed training must never break the app
        log.exception("Personal model training failed for %s", user_id)
        _update_registry(user_id, path, status="ready" if prev.get("sampler_path") else "failed",
                         last_error=str(exc)[:500])
        return TrainingResult(trained=False, reason=f"training failed: {exc}", examples=len(examples))

    old_path = prev.get("sampler_path")
    _update_registry(user_id, path, status="ready", base_model=base_model(), sampler_path=result.sampler_path,
                     version=version, trained_at=_now(), data_cutoff=data_cutoff, examples=len(examples),
                     positives=len(positives), negatives=len(negatives), last_loss=result.loss, last_error=None)
    log.info("Personal model v%d for %s ready in %.0fs (%d examples: %d reinforced, %d discouraged) -> %s",
             version, user_id, time.monotonic() - started, len(examples), len(positives), len(negatives),
             result.sampler_path)
    if old_path and old_path != result.sampler_path:
        _delete_checkpoint(old_path)
    return result


def _train(user_id: str, examples: list[Example], positives: list[Example], negatives: list[Example],
           version: int) -> TrainingResult:
    types = _types()
    svc = service()
    tc = svc.create_lora_training_client(base_model=base_model(), rank=_env_int("PERSONAL_LORA_RANK", 16),
                                         user_metadata={"app": "sidequest", "user": _safe_id(user_id)})
    tokenizer = tc.get_tokenizer()
    _tokenizers[base_model()] = tokenizer

    # Each quest's share of the update: reward x recency, spread over its tokens
    # (long quests don't count more than short ones); normalised so the
    # strongest signals sum to 1 - Adam is scale-invariant, this only sets the
    # balance between reinforcing and discouraging.
    total = sum(abs(e.signal) for e in examples) or 1.0
    tokenized = {e.app_quest_id: tokenize_example(tokenizer, e.prompt, e.completion) for e in examples}

    sft = []
    for e in positives:
        p, a = tokenized[e.app_quest_id]
        inp, tgt, w = _shift(p, a, e.signal / (total * max(len(a), 1)))
        sft.append(_datum(inp, target_tokens=tgt, weights=w))

    ppo = []
    if negatives:
        # Reference log-probs of the bad quests under the untrained model; PPO
        # lowers them but stops at its clip ratio (bounded "don't do that").
        ref_data = []
        for e in negatives:
            p, a = tokenized[e.app_quest_id]
            inp, tgt, w = _shift(p, a, 1.0)
            ref_data.append(_datum(inp, target_tokens=tgt, weights=w))
        ref = _result(tc.forward(ref_data, "cross_entropy"))
        for e, out in zip(negatives, ref.loss_fn_outputs):
            p, a = tokenized[e.app_quest_id]
            inp, tgt, adv = _shift(p, a, e.signal / (total * max(len(a), 1)))
            logprobs = _tolist(out["logprobs"])
            logprobs = [0.0] * (len(p) - 1) + logprobs[len(p) - 1:]  # prompt positions are masked anyway
            ppo.append(_datum(inp, target_tokens=tgt, logprobs=logprobs[:len(tgt)], advantages=adv))

    steps = max(1, _env_int("PERSONAL_TRAIN_STEPS", 8))
    lr = _env_float("PERSONAL_LEARNING_RATE", 2e-4)
    loss = None
    for step in range(steps):
        fb = tc.forward_backward(sft, "cross_entropy")      # gradients from both calls accumulate
        fb_neg = tc.forward_backward(ppo, "ppo") if ppo else None
        opt = tc.optim_step(types.AdamParams(learning_rate=lr, grad_clip_norm=1.0))
        out = _result(fb)
        if fb_neg is not None:
            _result(fb_neg)
        _result(opt)
        metrics = getattr(out, "metrics", {}) or {}
        loss = metrics.get("loss:sum", getattr(out, "loss", None))
        log.info("personal model %s step %d/%d loss %s", _safe_id(user_id), step + 1, steps, loss)

    saved = _result(tc.save_weights_for_sampler(name=f"{_safe_id(user_id)}-v{version}"))
    sampler_path = saved.path

    # Only switch to the new adapter if it still writes a valid quest.
    check = TinkerQuestClient(sampler_path, version, base=base_model())
    try:
        from .quest_generator import parse_quest

        parse_quest(check.complete(examples[0].prompt, temperature=0.7))
    except Exception as exc:
        _delete_checkpoint(sampler_path)
        raise LLMError(f"new adapter didn't produce a valid quest ({exc}) - keeping the previous one") from exc

    return TrainingResult(trained=True, version=version, sampler_path=sampler_path, examples=len(examples),
                          positives=len(positives), negatives=len(negatives),
                          loss=float(loss) if isinstance(loss, (int, float)) and math.isfinite(loss) else None)


def _delete_checkpoint(tinker_path: str) -> None:
    """Old adapters cost storage - remove them (best effort)."""
    try:
        rest = service().create_rest_client()
        _result(rest.delete_checkpoint_from_tinker_path(tinker_path), timeout=30)
    except Exception as exc:  # noqa: BLE001
        log.info("Couldn't delete old checkpoint %s: %s", tinker_path, exc)


# ---------------------------------------------------------------------------
# Generating with a user's model
# ---------------------------------------------------------------------------

class TinkerQuestClient:
    """LLMClient that samples from one user's fine-tuned adapter."""

    def __init__(self, sampler_path: str, version: int = 0, base: str | None = None,
                 timeout: float | None = None) -> None:
        self.sampler_path = sampler_path
        self.base = base or base_model()
        self.model = f"tinker:{self.base}:personal-v{version}"
        self.max_tokens = _env_int("PERSONAL_MAX_TOKENS", 1024)
        self.timeout = timeout or _env_float("PERSONAL_TIMEOUT", 90.0)
        self.last_call: dict[str, Any] = {}

    def _sampler(self) -> Any:
        s = _samplers.get(self.sampler_path)
        if s is None:
            s = service().create_sampling_client(model_path=self.sampler_path)
            _samplers[self.sampler_path] = s
        return s

    def _tokenizer(self, sampler: Any) -> Any:
        tok = _tokenizers.get(self.base)
        if tok is None:
            tok = sampler.get_tokenizer()
            _tokenizers[self.base] = tok
        return tok

    def complete(self, prompt: str, *, temperature: float = 0.9) -> str:
        started = time.monotonic()
        self.last_call = {"seconds": 0.0, "max_tokens": self.max_tokens}
        try:
            sampler = self._sampler()
            tok = self._tokenizer(sampler)
            tokens = tok.encode(render_prompt(tok, prompt), add_special_tokens=False)
            params = _types().SamplingParams(max_tokens=self.max_tokens, temperature=temperature,
                                             stop=_stops(tok))
            future = sampler.sample(prompt=_model_input(tokens), num_samples=1, sampling_params=params)
            response = future.result(timeout=self.timeout)
        except TimeoutError as exc:
            self.last_call["seconds"] = time.monotonic() - started
            raise LLMTimeout(f"Personal model didn't answer within {self.timeout:.0f}s") from exc
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - any Tinker problem -> fall back to Gemma
            self.last_call["seconds"] = time.monotonic() - started
            raise LLMError(f"Personal model (Tinker) failed: {exc}") from exc
        seq = response.sequences[0]
        out_tokens = list(seq.tokens)
        text = tok.decode(out_tokens, skip_special_tokens=True)
        self.last_call.update(seconds=round(time.monotonic() - started, 2), input_tokens=len(tokens),
                              output_tokens=len(out_tokens), total_tokens=len(tokens) + len(out_tokens),
                              finish_reason=str(getattr(seq, "stop_reason", "")))
        if not text.strip():
            raise LLMError("Personal model returned an empty answer")
        return text


class PersonalWithFallback:
    """Try the user's own model; on any failure use Gemma for the rest of this quest."""

    def __init__(self, personal: TinkerQuestClient, fallback: LLMClient) -> None:
        self.personal = personal
        self.fallback = fallback
        self.active: Any = personal
        self.fell_back_because = ""

    @property
    def model(self) -> str:
        return getattr(self.active, "model", "") or ""

    @property
    def last_call(self) -> dict:
        return getattr(self.active, "last_call", {}) or {}

    @property
    def max_tokens(self) -> Any:
        return getattr(self.active, "max_tokens", None)

    def complete(self, prompt: str, *, temperature: float = 0.9) -> str:
        if self.active is self.personal:
            try:
                return self.personal.complete(prompt, temperature=temperature)
            except LLMError as exc:
                log.warning("Personal model failed (%s) - using %s instead", exc,
                            getattr(self.fallback, "model", "Gemma"))
                self.fell_back_because = str(exc)[:300]
                self.active = self.fallback
        return self.fallback.complete(prompt, temperature=temperature)


def llm_for(user_id: str, default: LLMClient, path: Path | None = None) -> LLMClient:
    """The user's personal model (with `default` as fallback) if they have a ready one."""
    if not is_enabled():
        return default
    try:
        reg = _registry(user_id, path)
    except sqlite3.Error as exc:
        log.warning("Personal model registry unavailable: %s", exc)
        return default
    if not reg or not reg.get("sampler_path"):
        return default
    if reg.get("base_model") and reg["base_model"] != base_model():
        return default  # PERSONAL_BASE_MODEL changed - wait for the retrain on the new base
    return PersonalWithFallback(TinkerQuestClient(reg["sampler_path"], reg["version"], base=reg["base_model"]),
                                default)


# ---------------------------------------------------------------------------
# When to (re)train
# ---------------------------------------------------------------------------

_executor: ThreadPoolExecutor | None = None
_running: set[str] = set()
_again: set[str] = set()
_sched_lock = threading.Lock()
TRAIN_INLINE = False  # tests: train synchronously instead of in a background thread


def _new_feedback_count(user_id: str, since: str | None) -> tuple[int, int]:
    """(rated quests in total, rated since `since`)."""
    from . import db

    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM quests WHERE user_id = ? AND feedback IS NOT NULL",
                             (user_id,)).fetchone()[0]
        if since is None:
            return total, total
        new = conn.execute("SELECT COUNT(*) FROM quests WHERE user_id = ? AND feedback IS NOT NULL "
                           "AND feedback_at > ?", (user_id, since)).fetchone()[0]
    return total, new


def due(user_id: str, path: Path | None = None) -> bool:
    reg = _registry(user_id, path) or {}
    total, new = _new_feedback_count(user_id, reg.get("data_cutoff") if reg.get("sampler_path") else None)
    if not reg.get("sampler_path"):
        return total >= min_feedback()
    return new >= retrain_every() or (reg.get("base_model") not in (None, base_model()))


def note_feedback(user_id: str, path: Path | None = None) -> bool:
    """Call after every feedback. Starts a background retrain when enough new
    feedback has come in. Returns True if training was scheduled."""
    if not is_enabled():
        return False
    try:
        if not due(user_id, path):
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Couldn't check whether %s's personal model needs retraining: %s", user_id, exc)
        return False
    return schedule(user_id, path)


def schedule(user_id: str, path: Path | None = None) -> bool:
    global _executor
    with _sched_lock:
        if user_id in _running:
            _again.add(user_id)  # feedback arrived mid-training: run once more afterwards
            return True
        _running.add(user_id)
        if not TRAIN_INLINE and _executor is None:
            _executor = ThreadPoolExecutor(max_workers=max(1, _env_int("PERSONAL_TRAIN_WORKERS", 1)),
                                           thread_name_prefix="personal-train")
    if TRAIN_INLINE:
        _train_job(user_id, path)
    else:
        _executor.submit(_train_job, user_id, path)  # type: ignore[union-attr]
    return True


def _train_job(user_id: str, path: Path | None) -> None:
    while True:
        try:
            res = train_user(user_id, path)
            if not res.trained:
                log.info("Personal model for %s not trained: %s", user_id, res.reason)
        finally:
            with _sched_lock:
                again = user_id in _again
                _again.discard(user_id)
                if not again:
                    _running.discard(user_id)
        if not again:
            return


# ---------------------------------------------------------------------------
# Status / account deletion
# ---------------------------------------------------------------------------

class PersonalModelStatus(BaseModel):
    enabled: bool
    state: str              # off | collecting | training | ready | failed
    base_model: str | None = None
    version: int = 0
    trained_at: str | None = None
    examples: int = 0
    reinforced: int = 0     # quests that went well (trained toward)
    discouraged: int = 0    # disliked / unfinished quests (trained away from)
    rated_quests: int = 0
    feedback_until_retrain: int = 0
    last_error: str | None = None


def status(user_id: str, path: Path | None = None) -> PersonalModelStatus:
    if not is_enabled():
        return PersonalModelStatus(enabled=False, state="off")
    reg = _registry(user_id, path) or {}
    has_model = bool(reg.get("sampler_path"))
    total, new = _new_feedback_count(user_id, reg.get("data_cutoff") if has_model else None)
    with _sched_lock:
        running = user_id in _running
    if running or reg.get("status") == "training":
        state = "training"
    elif has_model:
        state = "ready"
    elif reg.get("status") == "failed":
        state = "failed"
    else:
        state = "collecting"
    until = max(0, (retrain_every() - new) if has_model else (min_feedback() - total))
    return PersonalModelStatus(
        enabled=True, state=state, base_model=reg.get("base_model") or base_model(),
        version=int(reg.get("version") or 0) if has_model else 0, trained_at=reg.get("trained_at"),
        examples=int(reg.get("examples") or 0), reinforced=int(reg.get("positives") or 0),
        discouraged=int(reg.get("negatives") or 0), rated_quests=total, feedback_until_retrain=until,
        last_error=reg.get("last_error"),
    )


def delete_user(user_id: str, path: Path | None = None) -> int:
    """Remove a deleted account's prompts, registry row and Tinker adapter."""
    p = Path(path or models_path())
    if not p.exists():
        return 0
    reg = _registry(user_id, path) or {}
    if reg.get("sampler_path") and is_enabled():
        _delete_checkpoint(reg["sampler_path"])
    conn = _connect(path)
    try:
        n = conn.execute("DELETE FROM quest_prompts WHERE user_id = ?", (user_id,)).rowcount
        n += conn.execute("DELETE FROM personal_models WHERE user_id = ?", (user_id,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()
