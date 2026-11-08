"""Eval-only model backend that drives Claude through the Claude Code CLI (`claude -p`).

For recording evals without an Anthropic API key. Tool use is expressed as structured output
(a JSON reply naming the tools to call), not the Messages API's native tool use, so results
recorded this way are labelled with the backend in results.json. Production uses ClaudeModel.
"""

import json
import subprocess
import uuid
from collections.abc import Sequence
from typing import Any

from app.agent.model import ModelError, ModelReply

PROTOCOL = """

You are running behind a tool protocol. The store tools described at the end are available and \
working, but you never call them directly: the only tool you can invoke is StructuredOutput. To \
use a store tool, put it in the tool_calls field of your StructuredOutput reply; it runs and you \
see its result in the next message. The conversation so far, including earlier tool calls and \
their results, is given as JSON. Reply with the assistant's next message only:
- To use store tools, list them in tool_calls with inputs that match their schemas, and leave \
text empty or a short note.
- To answer the shopper, put the answer in text and leave tool_calls empty.

Store tools (JSON Schema inputs):
"""


def _schema(names: list[str]) -> str:
    return json.dumps(
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": names},
                            "input": {"type": "object"},
                        },
                        "required": ["name", "input"],
                    },
                },
            },
            "required": ["text", "tool_calls"],
        }
    )


class ClaudeCodeModel:
    def __init__(self, model: str, timeout: int = 180) -> None:
        self._model = model
        self._timeout = timeout

    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        command = [
            "claude",
            "-p",
            "--model",
            self._model,
            "--system-prompt",
            system + PROTOCOL + json.dumps(list(tools)),
            "--tools",
            "",
            "--strict-mcp-config",
            "--json-schema",
            _schema([t["name"] for t in tools]),
            "--output-format",
            "json",
        ]
        try:
            done = subprocess.run(
                command,
                input=json.dumps(list(messages)),
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
            out = json.loads(done.stdout)
            reply = out["structured_output"]
        except (subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
            raise ModelError(f"claude CLI failed: {exc}") from exc
        usage = out.get("modelUsage", {}).get(self._model, {})
        content: list[dict[str, Any]] = []
        if reply["text"]:
            content.append({"type": "text", "text": reply["text"]})
        for call in reply["tool_calls"]:
            content.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_{uuid.uuid4().hex[:20]}",
                    "name": call["name"],
                    "input": call["input"],
                }
            )
        return ModelReply(
            stop_reason="tool_use" if reply["tool_calls"] else "end_turn",
            content=content,
            input_tokens=usage.get("inputTokens", 0)
            + usage.get("cacheReadInputTokens", 0)
            + usage.get("cacheCreationInputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )
