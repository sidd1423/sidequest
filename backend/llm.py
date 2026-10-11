"""Client for a Gemma model served behind an OpenAI-compatible inference API.

Works with any server that exposes `POST {base_url}/chat/completions`:

  Google AI Studio (default)  https://generativelanguage.googleapis.com/v1beta/openai   model: gemma-4-26b-a4b-it
  Ollama (local)              http://localhost:11434/v1                                  model: gemma3
  vLLM / TGI / OpenRouter     your server's /v1 URL                                     model: as served

Configure with GEMMA_BASE_URL, GEMMA_API_KEY and GEMMA_MODEL in .env.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Protocol

import requests

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemma-4-26b-a4b-it"
# Gemma 4 "thinks" before answering and those tokens count toward the limit,
# so leave plenty of room for the final JSON.
DEFAULT_MAX_TOKENS = 8192

log = logging.getLogger("sidequest.llm")


DEFAULT_TIMEOUT = 180  # seconds to wait for an answer (Gemma 4 thinks before replying)
CONNECT_TIMEOUT = 10


class LLMError(RuntimeError):
    """The inference API failed or returned something unusable."""


class LLMTimeout(LLMError):
    """The inference API didn't answer in time (often just a busy server - worth retrying)."""


class LLMClient(Protocol):
    model: str

    def complete(self, prompt: str, *, temperature: float = 0.9) -> str: ...


class GemmaClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("GEMMA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("GEMMA_API_KEY", "")
        self.model = model or os.getenv("GEMMA_MODEL") or DEFAULT_MODEL
        self.timeout = timeout or float(os.getenv("GEMMA_TIMEOUT") or DEFAULT_TIMEOUT)
        self.max_tokens = int(os.getenv("GEMMA_MAX_TOKENS", DEFAULT_MAX_TOKENS))
        # Optional: "low" asks reasoning models to think less (faster). Dropped
        # automatically if the server doesn't support it.
        self.reasoning_effort = os.getenv("GEMMA_REASONING_EFFORT", "").strip() or None
        # Stats for the last complete() call (backend/observability.py records them):
        # seconds, http_status, finish_reason, input/output/reasoning/total tokens.
        self.last_call: dict[str, Any] = {}

    def complete(self, prompt: str, *, temperature: float = 0.9) -> str:
        # Gemma has no separate system role on some hosts (e.g. Google AI Studio),
        # so all instructions go in a single user message.
        self.last_call = {"seconds": 0.0, "max_tokens": self.max_tokens, "reasoning_effort": self.reasoning_effort}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        resp = self._post(payload, headers)
        if resp.status_code == 400 and "reasoning" in resp.text.lower() and "reasoning_effort" in payload:
            log.warning("Server rejected reasoning_effort=%s - retrying without it", self.reasoning_effort)
            payload.pop("reasoning_effort")
            self.reasoning_effort = None
            resp = self._post(payload, headers)

        auth_problem = resp.status_code in (401, 403) or (
            resp.status_code == 400 and "authorization" in resp.text.lower()
        )
        if auth_problem and not self.api_key:
            raise LLMError(
                "GEMMA_API_KEY is empty - put your key in the .env file in the repo root "
                "(next to requirements.txt) and restart the backend"
            )
        if auth_problem:
            raise LLMError("Inference API rejected the key - check GEMMA_API_KEY in .env")
        if not resp.ok:
            raise LLMError(f"Inference API error {resp.status_code}: {resp.text[:300]}")

        try:
            choice = resp.json()["choices"][0]
            content = _text(choice["message"].get("content"))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"Unexpected response shape from inference API: {resp.text[:300]}") from exc

        finish = choice.get("finish_reason")
        self.last_call["finish_reason"] = finish
        self.last_call.update(usage_from(resp))
        log.info("model=%s finish_reason=%s chars=%d tokens in/out=%s/%s", self.model, finish, len(content),
                 self.last_call.get("input_tokens"), self.last_call.get("output_tokens"))
        log.debug("raw model output: %s", content[:2000])
        if not content.strip():
            hint = " (hit the token limit - raise GEMMA_MAX_TOKENS)" if finish == "length" else ""
            raise LLMError(f"Model returned an empty answer{hint}")
        return content

    def _post(self, payload: dict, headers: dict) -> requests.Response:
        started = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers,
                timeout=(CONNECT_TIMEOUT, self.timeout),
            )
        except requests.Timeout as exc:
            self.last_call["seconds"] = self.last_call.get("seconds", 0.0) + time.monotonic() - started
            self.last_call["timed_out_after"] = self.timeout
            raise LLMTimeout(
                f"Gemma didn't answer within {self.timeout:.0f}s - the inference API is probably busy. "
                "Try again, or raise GEMMA_TIMEOUT in .env"
            ) from exc
        except requests.RequestException as exc:
            self.last_call["seconds"] = self.last_call.get("seconds", 0.0) + time.monotonic() - started
            raise LLMError(f"Can't reach the inference API at {self.base_url}: {exc}") from exc
        self.last_call["seconds"] = self.last_call.get("seconds", 0.0) + time.monotonic() - started
        self.last_call["http_status"] = resp.status_code
        log.info("inference API answered in %.1fs (HTTP %s)", time.monotonic() - started, resp.status_code)
        return resp


def usage_from(resp: requests.Response) -> dict[str, int]:
    """Token counts from an OpenAI-style `usage` block (missing on some servers)."""
    try:
        usage = resp.json().get("usage") or {}
    except (ValueError, AttributeError):
        return {}
    out = {}
    for key, name in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"),
                      ("total_tokens", "total_tokens")):
        if isinstance(usage.get(key), (int, float)):
            out[name] = int(usage[key])
    details = usage.get("completion_tokens_details") or {}
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), (int, float)):
        out["reasoning_tokens"] = int(details["reasoning_tokens"])  # Gemma "thinking"
    return out


def _text(content: Any) -> str:
    """Content is usually a string, but some servers return a list of parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)
