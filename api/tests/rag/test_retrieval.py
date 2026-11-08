import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine

from app.connectors.shopify.client import PolicyDoc, ProductDoc
from app.db import tenant_connection
from app.ingest.sync import upsert_policy, upsert_product
from app.rag.embedder import HashingEmbedder
from app.rag.retrieval import search

pytestmark = pytest.mark.usefixtures("clean_catalog")

CATALOG = {
    "Merino Wool Beanie": "Warm knit hat for winter, made from soft merino wool.",
    "Waterproof Rain Jacket": "Lightweight shell that keeps you dry in heavy rain.",
    "Trail Running Shoes": "Grippy outsole and cushioned midsole for rough trails.",
    "Leather Wallet": "Slim bifold wallet in full-grain leather with six card slots.",
    "Ceramic Coffee Mug": "Holds 350 ml, dishwasher and microwave safe.",
    "Yoga Mat": "Non-slip 6 mm mat for yoga and pilates.",
    "Canvas Tote Bag": "Sturdy cotton canvas tote for groceries and books.",
    "Stainless Water Bottle": "Insulated bottle keeps drinks cold for 24 hours.",
    "Linen Bed Sheets": "Breathable washed linen sheet set, queen size.",
    "Bluetooth Speaker": "Portable speaker with 12 hour battery and water resistance.",
}

QUERIES = {
    "do you have a warm hat for winter": "Merino Wool Beanie",
    "jacket that keeps me dry in the rain": "Waterproof Rain Jacket",
    "shoes for running on trails": "Trail Running Shoes",
    "slim leather wallet with card slots": "Leather Wallet",
    "is the mug microwave safe": "Ceramic Coffee Mug",
    "non-slip mat for pilates": "Yoga Mat",
    "a bag for groceries": "Canvas Tote Bag",
    "bottle that keeps drinks cold": "Stainless Water Bottle",
    "queen size linen sheets": "Linen Bed Sheets",
    "speaker battery life": "Bluetooth Speaker",
}


def seed(engine: Engine, tenant: uuid.UUID, catalog: dict[str, str]) -> None:
    embedder = HashingEmbedder()
    with tenant_connection(engine, tenant) as conn:
        for n, (title, description) in enumerate(catalog.items()):
            doc = ProductDoc(
                external_id=f"gid://shopify/Product/{n}",
                title=title,
                description_html=f"<p>{description}</p>",
                handle=title.lower().replace(" ", "-"),
                price_min=Decimal("10"),
                price_max=Decimal("10"),
                available=True,
            )
            upsert_product(conn, tenant, "demo.myshopify.com", doc, embedder)


def test_seeded_queries_find_the_right_product(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    seed(app_engine, tenants[0], CATALOG)

    with tenant_connection(app_engine, tenants[0]) as conn:
        top = {query: search(conn, query, HashingEmbedder(), limit=1) for query in QUERIES}

    assert {query: hits[0].title for query, hits in top.items()} == QUERIES


def test_retrieval_never_crosses_stores(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    store_a, store_b = tenants
    seed(app_engine, store_a, {"Merino Wool Beanie": "Warm merino wool hat."})
    seed(app_engine, store_b, {"Garden Hose": "Fifty foot expandable hose."})

    with tenant_connection(app_engine, store_b) as conn:
        hits = search(conn, "warm merino wool hat", HashingEmbedder(), limit=10)

    assert [hit.title for hit in hits] == ["Garden Hose"]


def test_source_type_filter_returns_only_policies(
    app_engine: Engine, tenants: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant = tenants[0]
    seed(app_engine, tenant, {"Return Label Printer": "Prints return labels."})
    policy = PolicyDoc(
        kind="REFUND_POLICY",
        title="Refund policy",
        body_html="<p>Return unworn items within 30 days for a full refund.</p>",
        url=None,
    )
    with tenant_connection(app_engine, tenant) as conn:
        upsert_policy(conn, tenant, policy, HashingEmbedder())
        hits = search(conn, "how do returns work", HashingEmbedder(), source_type="policy")

    assert [hit.title for hit in hits] == ["Refund policy"]
