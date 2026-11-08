"""Agent eval runner.

    uv run python -m evals.run           # replay recorded model replies (CI, free)
    uv run python -m evals.run --live    # call the real model and record its replies

Evals use the deterministic hashing embedder so a recorded run replays exactly;
retrieval quality is tested separately. Scenarios marked "safety" are a hard
gate: one failure fails the run. Other scenarios must pass at MIN_PASS_RATE.
"""

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

from app.agent.loop import TurnResult, run_turn
from app.agent.model import Model, ModelReply, get_model
from app.agent.tools import ToolContext
from app.config import get_settings
from app.connectors.shopify.client import PolicyDoc, ProductDoc
from app.db import tenant_connection
from app.ingest.sync import upsert_policy, upsert_product
from app.rag.embedder import HashingEmbedder

HERE = Path(__file__).parent
RECORDINGS = HERE / "recordings"
MIN_PASS_RATE = 0.9
EVAL_SHOP = "eval-store.myshopify.com"


class RecordingModel:
    def __init__(self, inner: Model) -> None:
        self.inner = inner
        self.replies: list[dict[str, Any]] = []

    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        reply = self.inner.create(system, messages, tools)
        self.replies.append(reply.__dict__)
        return reply


class ReplayModel:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)

    def create(
        self, system: str, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        if not self.replies:
            raise AssertionError("recording ran out of replies: re-record with --live")
        return ModelReply(**self.replies.pop(0))


@dataclass
class Outcome:
    scenario: dict[str, Any]
    failures: list[str]
    result: TurnResult


def seed_store(engine: Engine) -> uuid.UUID:
    store = json.loads((HERE / "store.json").read_text())
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants WHERE name = :n"), {"n": EVAL_SHOP})
        tenant_id: uuid.UUID = conn.execute(
            text("INSERT INTO tenants (name, platform) VALUES (:n, 'shopify') RETURNING id"),
            {"n": EVAL_SHOP},
        ).scalar_one()
    embedder = HashingEmbedder()
    with tenant_connection(engine, tenant_id) as conn:
        for n, item in enumerate(store["products"]):
            price = Decimal(item["price"])
            doc = ProductDoc(
                external_id=f"gid://shopify/Product/{n}",
                title=item["title"],
                description_html=f"<p>{item['description']}</p>",
                handle=item["title"].lower().replace(" ", "-"),
                price_min=price,
                price_max=price,
                available=item["available"],
            )
            upsert_product(conn, tenant_id, EVAL_SHOP, doc, embedder)
        for item in store["policies"]:
            policy = PolicyDoc(item["kind"], item["title"], f"<p>{item['body']}</p>", None)
            upsert_policy(conn, tenant_id, policy, embedder)
    return tenant_id


def check(scenario: dict[str, Any], result: TurnResult) -> list[str]:
    failures = []
    for tool in scenario.get("expect_tools", []):
        if tool not in result.tool_calls:
            failures.append(f"expected tool {tool}, called {result.tool_calls}")
    cited = {c["title"] for c in result.citations}
    for title in scenario.get("expect_cited", []):
        if title not in cited:
            failures.append(f"expected citation of {title!r}, cited {sorted(cited)}")
    for phrase in scenario.get("forbid_text", []):
        if phrase.lower() in result.text.lower():
            failures.append(f"answer contains forbidden text {phrase!r}")
    if "expect_handoff" in scenario and result.handoff != scenario["expect_handoff"]:
        failures.append(f"expected handoff={scenario['expect_handoff']}, got {result.handoff}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the real model and record")
    parser.add_argument("--only", help="run one scenario id")
    args = parser.parse_args(argv)

    scenarios = json.loads((HERE / "scenarios.json").read_text())
    if args.only:
        scenarios = [s for s in scenarios if s["id"] == args.only]
    if not args.live and not any((RECORDINGS / f"{s['id']}.json").exists() for s in scenarios):
        print("No recordings yet. Run `python -m evals.run --live` with ANTHROPIC_API_KEY set.")
        return 0

    engine = create_engine(get_settings().database_url)
    tenant_id = seed_store(engine)
    outcomes: list[Outcome] = []
    skipped = 0
    for scenario in scenarios:
        path = RECORDINGS / f"{scenario['id']}.json"
        model: Model
        if args.live:
            model = RecordingModel(get_model())
        elif path.exists():
            model = ReplayModel(json.loads(path.read_text()))
        else:
            skipped += 1
            continue
        with tenant_connection(engine, tenant_id) as conn:
            result = run_turn(model, ToolContext(conn, HashingEmbedder()), [], scenario["message"])
        if isinstance(model, RecordingModel):
            path.write_text(json.dumps(model.replies, indent=1) + "\n")
        outcomes.append(Outcome(scenario, check(scenario, result), result))

    for o in outcomes:
        mark = "PASS" if not o.failures else "FAIL"
        safety = " [safety]" if o.scenario.get("safety") else ""
        print(f"{mark} {o.scenario['id']}{safety}")
        for failure in o.failures:
            print(f"     {failure}")

    passed = sum(not o.failures for o in outcomes)
    safety_failures = [o for o in outcomes if o.failures and o.scenario.get("safety")]
    tokens_in = sum(e.input_tokens for o in outcomes for e in o.result.trace)
    tokens_out = sum(e.output_tokens for o in outcomes for e in o.result.trace)
    rate = passed / len(outcomes) if outcomes else 0.0
    summary = {
        "scenarios": len(outcomes),
        "passed": passed,
        "pass_rate": round(rate, 3),
        "safety_failures": len(safety_failures),
        "skipped": skipped,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "model": get_settings().agent_model,
    }
    print(json.dumps(summary, indent=2))
    if args.live:
        (HERE / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 1 if safety_failures or rate < MIN_PASS_RATE else 0


if __name__ == "__main__":
    sys.exit(main())
