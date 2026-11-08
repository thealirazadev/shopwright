# Product Requirements - Shopwright

## What we are building

A customer-support agent for Shopify (and later WooCommerce) stores. A shopper chats with it
through a widget on the store; it answers from the store's own catalog and policies with
citations, looks up the shopper's own orders after verifying who they are, and prepares refunds,
returns, and cancellations for a human to approve. It never moves money or changes an order on
its own.

The merchant connects the store, reviews pending actions in a dashboard, and sees every
conversation with its tool calls, cost, and latency.

## Target user

- **Merchant:** a small or mid-size Shopify store owner or support lead who answers the same
  questions every day ("where is my order", "can I return this", "does this come in blue") and
  wants them handled without risking a wrong refund or a leaked order.
- **Shopper:** a customer of that store who wants an accurate answer now, not an email in two days.

## Core features (prioritized)

1. **Grounded answers.** Product and policy questions are answered only from the store's synced
   catalog and policy pages, with citations to the source. If the sources do not cover the
   question, the agent says so and offers a human.
2. **Verified order lookup.** Order status, items, and tracking are shown only after the shopper
   proves ownership (order number plus the email on the order). Unverified requests get no order
   data, including whether an order exists.
3. **Actions behind approval.** Refund, return, and cancellation requests become proposals with
   the agent's reasoning and the policy it relied on. A merchant approves or rejects each one in
   the dashboard; only an approval calls the Shopify API.
4. **Human handoff.** The shopper can ask for a person at any time, and the agent hands off on its
   own when it is unsure, after two failed attempts, or when the shopper is upset.
5. **Conversation traces.** Every turn records the messages, tool calls with arguments and
   results, tokens, cost, and latency, visible to the merchant.
6. **Evals in CI.** A versioned scenario suite measures answer accuracy, citation accuracy, tool
   choice, and policy safety, and gates merges.
7. **Embeddable widget.** One script tag, authenticated with short-lived signed tokens.

## Non-goals

- No autonomous refunds, cancellations, discounts, or order edits, at any confidence level.
- No storefront actions such as adding to cart or checkout in v1.
- No voice or phone channel in v1.
- No merchant-authored prompt editing; tone is a small set of presets.
- No cross-store analytics or shared learning between tenants.
- No fine-tuning; quality comes from retrieval, tools, and prompts measured by evals.

## Success criteria per core feature

1. Grounded answers: on the eval suite, at least 90% of answerable questions are correct and
   every factual answer cites at least one source that supports it; unanswerable questions are
   declined at least 95% of the time instead of guessed.
2. Verified order lookup: zero order fields disclosed in any unverified scenario, including
   prompt-injection and social-engineering scenarios. This is a hard gate, not an average.
3. Actions behind approval: zero Shopify write calls without an approved proposal, proven by a
   test that fails if the write client is reachable from the agent's tool set.
4. Human handoff: every explicit request for a human produces a handoff within one turn.
5. Traces: every tool call in every conversation is reconstructable from stored traces, with cost
   matching the provider-reported usage.
6. Evals: the CI suite runs offline on recorded model responses in under two minutes; a live run
   against the real model is a manual job that reports cost.
7. Widget: embeds with one script tag; a token for store A cannot read store B's data.
