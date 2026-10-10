"""Text embeddings.

- LocalEmbedder: WordLlama (256 dims), runs fully offline - weights ship inside
  the pip package. Used for the local SQLite quest library.
- GeminiEmbedder: Google's gemini-embedding-001 (768 dims) via the Gemini API,
  using the same key as Gemma. Used for the Tiger Data library.

Vectors are L2-normalised so a dot product is cosine similarity.
"""

from __future__ import annotations

import math
import os
from typing import Literal, Protocol, Sequence

import requests

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIM = 768
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
BATCH_LIMIT = 100

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Sequence[str], task: TaskType) -> list[list[float]]: ...


def _normalise(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class GeminiEmbedder:
    def __init__(self, api_key: str | None = None, model: str | None = None, dim: int | None = None) -> None:
        self.api_key = api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("GEMMA_API_KEY", "")
        self.model = model or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        self.dim = dim or int(os.getenv("EMBEDDING_DIM", DEFAULT_DIM))
        if not self.api_key:
            raise EmbeddingError("No embedding API key - set GEMMA_API_KEY (or EMBEDDING_API_KEY) in .env")

    def embed(self, texts: Sequence[str], task: TaskType = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_LIMIT):
            out.extend(self._batch(texts[i : i + BATCH_LIMIT], task))
        return out

    def _batch(self, texts: Sequence[str], task: TaskType) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": task,
                    "outputDimensionality": self.dim,
                }
                for t in texts
            ]
        }
        try:
            resp = requests.post(
                f"{API_ROOT}/models/{self.model}:batchEmbedContents",
                json=body,
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                timeout=60,
            )
        except requests.RequestException as exc:
            raise EmbeddingError(f"Can't reach the embedding API: {exc}") from exc
        if not resp.ok:
            raise EmbeddingError(f"Embedding API error {resp.status_code}: {resp.text[:300]}")
        try:
            vectors = [e["values"] for e in resp.json()["embeddings"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(f"Unexpected embedding response: {resp.text[:300]}") from exc
        if any(len(v) != self.dim for v in vectors):
            raise EmbeddingError(f"Expected {self.dim}-dim vectors, got {len(vectors[0])}")
        return [_normalise(v) for v in vectors]


class LocalEmbedder:
    """Offline embeddings with WordLlama (model weights are bundled in the wheel)."""

    model = "wordllama-l2-supercat-256"
    dim = 256
    _wl = None  # loaded once per process

    @classmethod
    def _load(cls):
        if cls._wl is None:
            try:
                from pathlib import Path

                import wordllama
                from wordllama import WordLlama
            except ImportError as exc:
                raise EmbeddingError("wordllama is not installed - run: pip install -r requirements.txt") from exc
            # The package ships its tokenizer under wordllama/tokenizers/, which the
            # loader only finds via cache_dir; this keeps it fully offline.
            cls._wl = WordLlama.load(cache_dir=Path(wordllama.__file__).parent, disable_download=True)
        return cls._wl

    def embed(self, texts: Sequence[str], task: TaskType = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        vectors = self._load().embed(list(texts), norm=True)
        return [list(map(float, v)) for v in vectors]
