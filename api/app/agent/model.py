"""Model access behind a small interface, so the loop can run against Claude or a script."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

from app.config import get_settings

Block = dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    stop_reason: str
    content: list[Block]
    input_tokens: int = 0
    output_tokens: int = 0


class ModelError(Exception):
    pass


class Model(Protocol):
    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply: ...


class ClaudeModel:
    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=60)
        self._model = model
        self._max_tokens = max_tokens

    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=list(tools),  # type: ignore[arg-type]
                messages=list(messages),  # type: ignore[arg-type]
            )
        except anthropic.APIError as exc:
            raise ModelError(str(exc)) from exc
        return ModelReply(
            stop_reason=response.stop_reason or "end_turn",
            content=[block.model_dump(exclude_none=True) for block in response.content],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


def get_model() -> Model:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ModelError("ANTHROPIC_API_KEY is not set")
    return ClaudeModel(settings.anthropic_api_key, settings.agent_model)
