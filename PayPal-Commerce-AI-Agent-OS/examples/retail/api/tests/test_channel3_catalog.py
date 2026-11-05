# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

import httpx
import pytest

from retail.api.channel3_catalog import Channel3Catalog, map_product
from retail.api.mock_retail import MockRetail
from shopping_agent import SearchFilters, ShoppingSessionContext


def channel3_product(product_id: str = "running-shoe-1") -> dict:
    return {
        "id": product_id,
        "title": "Cloud Runner 4",
        "description": "A lightweight daily running shoe.",
        "brands": [{"id": "brand-1", "name": "Northstar"}],
        "images": [
            {
                "url": "https://images.example/shoe.jpg",
                "cleaned_url": "https://images.example/shoe-clean.png",
                "is_main_image": True,
            }
        ],
        "category": {"slug": "running-shoes", "title": "Running shoes"},
        "materials": ["mesh", "rubber"],
        "key_features": ["Lightweight", "Neutral support"],
        "offers": [
            {
                "url": "https://www.buy.trychannel3.com/example",
                "domain": "merchant.example",
                "price": {"price": 119.99, "currency": "USD"},
                "availability": "InStock",
                "condition": "new",
                "variants": {
                    "selected": [
                        {"name": "Color", "label": "Navy"},
                        {"name": "Size", "label": "10"},
                    ]
                },
            }
        ],
    }


def test_maps_channel3_product_without_exposing_buy_url():
    product = map_product(channel3_product())
    assert product is not None
    assert product.product_id == "ch3:running-shoe-1"
    assert product.price == 119.99
    assert product.image_url == "https://images.example/shoe-clean.png"
    assert product.option_values == {"color": "Navy", "size": "10"}
    assert product.attributes["catalog_source"] == "Channel3"
    assert "buy.trychannel3.com" not in product.model_dump_json()


@pytest.mark.asyncio
async def test_channel3_search_maps_filters_caches_details_and_hashes_user_id():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["filters"]["price"] == {"min_price": 80.0, "max_price": 150.0}
            # Channel3's wire Page uses `data` (the Python SDK exposes this as `.items`).
            return httpx.Response(200, json={"data": [channel3_product()]})
        return httpx.Response(200, json=channel3_product())

    catalog = Channel3Catalog("secret", transport=httpx.MockTransport(handler))
    session = ShoppingSessionContext(session_id="session", user_id="customer@example.com")
    products = await catalog.search(
        session,
        "running shoes",
        SearchFilters(min_price=80, max_price=150),
        4,
    )
    details = await catalog.details(session, products[0].product_id)

    assert details is not None
    assert details.review_highlights == ["Lightweight", "Neutral support"]
    assert requests[0].headers["x-api-key"] == "secret"
    assert requests[0].headers["x-user-id"].startswith("commerce-")
    assert "customer@example.com" not in requests[0].headers["x-user-id"]


@pytest.mark.asyncio
async def test_channel3_search_accepts_legacy_products_envelope():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"products": [channel3_product()]})

    catalog = Channel3Catalog("secret", transport=httpx.MockTransport(handler))
    session = ShoppingSessionContext(session_id="session", user_id="customer")
    products = await catalog.search(session, "running shoes", None, 4)
    assert [product.product_id for product in products] == ["ch3:running-shoe-1"]


def test_invalid_channel3_numeric_config_disables_integration(monkeypatch):
    monkeypatch.setenv("CHANNEL3_API_KEY", "secret")
    monkeypatch.setenv("CHANNEL3_TIMEOUT_SECONDS", "not-a-number")
    assert Channel3Catalog.from_env() is None


@pytest.mark.asyncio
async def test_retail_falls_back_to_local_catalog_when_channel3_fails():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "unavailable"})

    backend = MockRetail(channel3=Channel3Catalog("secret", transport=httpx.MockTransport(handler)))
    session = ShoppingSessionContext(session_id="session", user_id="customer")
    products = await backend.search_products(session, "tent", SearchFilters(), 4)

    assert products
    assert all(not product.product_id.startswith("ch3:") for product in products)
