from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from abc import ABC, abstractmethod

import numpy as np

from ..config import get_settings

log = logging.getLogger("docuchat.embeddings")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


class Embedder(ABC):
    name: str = "base"
    model: str = ""
    dim: int = 0
    degraded: bool = False

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        ...

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def status(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "dim": self.dim,
            "degraded": self.degraded,
        }


class HashingEmbedder(Embedder):
    """Dependency-free lexical vectorizer: feature-hashed word/char n-grams.

    Used as a fallback when the neural embedding model cannot be loaded. It is a
    real vector-space model but is not a neural semantic embedder; the active
    provider is always reported by /api/system/status.
    """

    name = "hashing"
    model = "hashing-ngram-v1"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        words = _TOKEN_RE.findall(text.lower())
        tokens = list(words)
        tokens.extend(f"{a}_{b}" for a, b in zip(words, words[1:]))
        for word in words:
            if len(word) > 4:
                padded = f"#{word}#"
                tokens.extend(padded[i : i + 3] for i in range(len(padded) - 2))
        return tokens

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            counts: dict[int, float] = {}
            for token in self._tokens(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                counts[bucket] = counts.get(bucket, 0.0) + sign
            for bucket, value in counts.items():
                out[row, bucket] = math.copysign(math.log1p(abs(value)), value)
            norm = np.linalg.norm(out[row])
            if norm > 0:
                out[row] /= norm
        return out


class FastEmbedEmbedder(Embedder):
    name = "fastembed"

    def __init__(self, model_name: str, cache_dir: str):
        from fastembed import TextEmbedding

        self.model = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        probe = list(self._model.embed(["dimension probe"]))
        self.dim = int(np.asarray(probe[0]).shape[0])

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = [np.asarray(v, dtype=np.float32) for v in self._model.embed(texts, batch_size=get_settings().embed_batch_size)]
        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def embed_query(self, text: str) -> np.ndarray:
        if hasattr(self._model, "query_embed"):
            vector = np.asarray(list(self._model.query_embed([text]))[0], dtype=np.float32)
            norm = np.linalg.norm(vector)
            return vector / norm if norm else vector
        return super().embed_query(text)


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str):
        import httpx

        self.model = model
        self.dim = 1536
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )

    def embed(self, texts: list[str]) -> np.ndarray:
        response = self._client.post("/embeddings", json={"model": self.model, "input": texts})
        response.raise_for_status()
        data = response.json()["data"]
        matrix = np.array([row["embedding"] for row in data], dtype=np.float32)
        self.dim = matrix.shape[1]
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


_embedder: Embedder | None = None
_lock = threading.Lock()
_init_error: str | None = None


def get_embedder() -> Embedder:
    global _embedder, _init_error
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        settings = get_settings()
        provider = settings.embed_provider.lower()
        fallback_reason = None
        if provider == "fastembed":
            try:
                _embedder = FastEmbedEmbedder(settings.embed_model, settings.embed_cache_dir)
            except Exception as exc:  # model download/onnx failure
                log.warning("fastembed unavailable (%s); falling back to hashing embedder", exc)
                _init_error = str(exc)
                fallback_reason = f"fastembed unavailable: {exc}"
                _embedder = HashingEmbedder()
        elif provider == "openai":
            if not settings.llm_api_key:
                raise RuntimeError("EMBED_PROVIDER=openai requires LLM_API_KEY")
            _embedder = OpenAIEmbedder(settings.llm_api_key, "text-embedding-3-small", settings.llm_base_url)
        else:
            _embedder = HashingEmbedder()

        if fallback_reason:
            _embedder.degraded = True
            _embedder.model = f"{_embedder.model} (fallback: {fallback_reason[:120]})"
        return _embedder


def embedder_status() -> dict:
    status = get_embedder().status()
    status["init_error"] = _init_error
    return status
