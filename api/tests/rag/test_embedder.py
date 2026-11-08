import json

import httpx
import pytest

from app.config import get_settings
from app.rag.embedder import (
    EMBEDDING_DIM,
    EmbeddingError,
    HashingEmbedder,
    VoyageEmbedder,
    get_embedder,
)


def test_voyage_batches_inputs_and_restores_order() -> None:
    batches: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        batches.append(body["input"])
        assert body["output_dimension"] == EMBEDDING_DIM
        assert request.headers["authorization"] == "Bearer vk"
        data = [{"index": i, "embedding": [float(len(t))]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})

    embedder = VoyageEmbedder(
        "vk", "voyage-3.5", httpx.Client(transport=httpx.MockTransport(handler))
    )
    embedder.batch_size = 2
    vectors = embedder.embed(["a", "bb", "ccc"], input_type="document")

    assert [len(b) for b in batches] == [2, 1]
    assert vectors == [[1.0], [2.0], [3.0]]


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(429, json={}),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
    ],
    ids=["http-error", "unreachable"],
)
def test_voyage_failures_raise_embedding_error(handler: object) -> None:
    http = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    with pytest.raises(EmbeddingError):
        VoyageEmbedder("vk", "voyage-3.5", http).embed(["a"], input_type="query")


def test_get_embedder_uses_voyage_only_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "")
    get_settings.cache_clear()
    assert isinstance(get_embedder(), HashingEmbedder)
    monkeypatch.setenv("VOYAGE_API_KEY", "vk")
    get_settings.cache_clear()
    assert isinstance(get_embedder(), VoyageEmbedder)
    get_settings.cache_clear()
