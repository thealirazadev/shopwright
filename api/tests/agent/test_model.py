import json
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from app.agent.model import ClaudeModel, ModelError, get_model
from app.config import get_settings


def claude_with(handler: httpx.MockTransport) -> ClaudeModel:
    model = ClaudeModel("sk-test", "claude-sonnet-5-5")
    model._client = anthropic.Anthropic(
        api_key="sk-test", max_retries=0, http_client=httpx.Client(transport=handler)
    )
    return model


def test_a_reply_keeps_blocks_usage_and_caches_the_system_prompt() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Checking"},
                    {"type": "tool_use", "id": "t1", "name": "search_catalog", "input": {}},
                ],
                "usage": {"input_tokens": 11, "output_tokens": 4},
            },
        )

    reply = claude_with(httpx.MockTransport(handler)).create(
        "system", [{"role": "user", "content": "hi"}], []
    )

    assert reply.stop_reason == "tool_use"
    assert [b["type"] for b in reply.content] == ["text", "tool_use"]
    assert (reply.input_tokens, reply.output_tokens) == (11, 4)
    assert sent[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent[0]["model"] == "claude-sonnet-5-5"


def test_an_api_error_becomes_a_model_error() -> None:
    handler = httpx.MockTransport(
        lambda r: httpx.Response(529, json={"type": "error", "error": {"type": "overloaded"}})
    )
    with pytest.raises(ModelError):
        claude_with(handler).create("system", [{"role": "user", "content": "hi"}], [])


def test_get_model_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(ModelError):
        get_model()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    get_settings.cache_clear()
    assert isinstance(get_model(), ClaudeModel)
    get_settings.cache_clear()
