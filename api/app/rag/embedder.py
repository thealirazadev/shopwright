import hashlib
import logging
import math
import re
from collections.abc import Sequence
from typing import Literal, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
InputType = Literal["document", "query"]


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]: ...


class VoyageEmbedder:
    url = "https://api.voyageai.com/v1/embeddings"
    batch_size = 128

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._http = http or httpx.Client(timeout=30)

    def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            try:
                response = self._http.post(
                    self.url,
                    headers=self._headers,
                    json={
                        "input": batch,
                        "model": self._model,
                        "input_type": input_type,
                        "output_dimension": EMBEDDING_DIM,
                    },
                )
            except httpx.HTTPError as exc:
                raise EmbeddingError("embedding API unreachable") from exc
            if response.status_code != 200:
                raise EmbeddingError(f"embedding API returned HTTP {response.status_code}")
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in data)
        return vectors


class HashingEmbedder:
    """Deterministic bag-of-words embedder for tests and local runs without an API key."""

    def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha1(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % EMBEDDING_DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.voyage_api_key:
        return VoyageEmbedder(settings.voyage_api_key, settings.embedding_model)
    logger.warning("embedder.hashing_fallback")
    return HashingEmbedder()


def to_pgvector(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
