"""Client for a Gemma model served behind an OpenAI-compatible inference API.

Works with any server that exposes `POST {base_url}/chat/completions`:

  Google AI Studio (default)  https://generativelanguage.googleapis.com/v1beta/openai   model: gemma-3-27b-it
  Ollama (local)              http://localhost:11434/v1                                  model: gemma3
  vLLM / TGI / OpenRouter     your server's /v1 URL                                     model: as served

Configure with GEMMA_BASE_URL, GEMMA_API_KEY and GEMMA_MODEL in .env.
"""

from __future__ import annotations

import os
from typing import Protocol

import requests

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemma-3-27b-it"


class LLMError(RuntimeError):
    """The inference API failed or returned something unusable."""


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
        self.timeout = timeout or float(os.getenv("GEMMA_TIMEOUT", "90"))

    def complete(self, prompt: str, *, temperature: float = 0.9) -> str:
        # Gemma has no separate system role on some hosts (e.g. Google AI Studio),
        # so all instructions go in a single user message.
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": 1200,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise LLMError(f"Can't reach the inference API at {self.base_url}: {exc}") from exc

        if resp.status_code in (401, 403):
            raise LLMError("Inference API rejected the key - check GEMMA_API_KEY in .env")
        if not resp.ok:
            raise LLMError(f"Inference API error {resp.status_code}: {resp.text[:300]}")

        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected response shape from inference API: {resp.text[:300]}") from exc
