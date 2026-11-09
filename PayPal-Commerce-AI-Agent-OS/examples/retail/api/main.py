# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""ACME retail example API: the mock retailer behind the shared storefront routes, the
merchant router under /api/merchant, and the retail-only routes below.

    uvicorn retail.api.main:app --app-dir examples --reload --port 8000

Memory here is file-backed (``data/.memory-store.json``, gitignored) and seeded once per
user, so what a shopper asks the store to remember, or to forget, survives a restart.
"""

from __future__ import annotations

import os

from fastapi.staticfiles import StaticFiles

from commerce_common.memory import InMemoryMemoryStore, JsonFileMemoryStore
from demo_common import (
    REPO_ROOT,
    CartAddRequest,
    MemorySeeder,
    build_storefront_host,
    load_demo_env,
)
from shopping_agent import ProductDetails
from shopping_agent_runtime import ShoppingAgent

from .agent_config import build_shopping_config
from .merchant import create_merchant_router
from .mock_retail import DATA_DIR, MockRetail

load_demo_env(DATA_DIR.parent)
if os.environ.get("COMMERCE_PLATFORM", "demo") not in {"demo", "woocommerce", "shopify"}:
    raise ValueError("COMMERCE_PLATFORM must be demo, woocommerce or shopify")
PRODUCT_IMAGES = DATA_DIR.parent / "storefront-web" / "public" / "products"
storefront_sessions = None

if os.environ.get("COMMERCE_PLATFORM") == "woocommerce":
    from shopping_agent.woocommerce import WooCommerceBackend

    backend = WooCommerceBackend(
        os.environ["WOOCOMMERCE_URL"],
        os.environ["WOOCOMMERCE_BRIDGE_SECRET"],
        os.environ.get("COMMERCE_MERCHANT_ID", "retail"),
    )
elif os.environ.get("COMMERCE_PLATFORM") == "shopify":
    from commerce_common.control_store import ControlStore
    from commerce_platform.storefronts import DurableSessions
    from shopping_agent.shopify import ShopifyBackend

    if not os.environ.get("SHOPIFY_WEBHOOK_SECRET"):
        raise ValueError("SHOPIFY_WEBHOOK_SECRET is required for paid-order confirmation")

    control_store = ControlStore(
        os.environ["COMMERCE_CONTROL_DATABASE_URL"], os.environ["COMMERCE_ENCRYPTION_KEY"]
    )
    storefront_sessions = DurableSessions(
        control_store, os.environ.get("COMMERCE_MERCHANT_ID", "retail")
    )
    backend = ShopifyBackend(
        os.environ["SHOPIFY_URL"],
        os.environ["SHOPIFY_STOREFRONT_TOKEN"],
        os.environ.get("COMMERCE_MERCHANT_ID", "retail"),
        control_store,
    )
else:
    backend = MockRetail()
agent = ShoppingAgent(
    backend=backend,
    skills_dir=REPO_ROOT / "shopping-agent" / "skills",
    config=build_shopping_config(),
    memory_store=JsonFileMemoryStore(DATA_DIR / ".memory-store.json"),
)


def product_detail(product: ProductDetails) -> dict:
    # Detail-panel enrichment only; the agent's tool results never carry it.
    return product.model_dump() | {
        "price_intelligence": backend.price_intelligence(product.product_id),
        "review_aspects": backend.review_aspects(product.product_id),
    }


host = build_storefront_host(
    title="PayPal Commerce AI Agent OS — ACME Retail API",
    example_root=DATA_DIR.parent,
    backend=backend,
    agent=agent,
    memory_seeder=MemorySeeder(
        DATA_DIR / "memory-seed.json",
        marker=DATA_DIR / ".memory-seeded.json",
        enabled=isinstance(backend, MockRetail),
    ),
    product_detail=product_detail,
    sessions=storefront_sessions,
)
app = host.app
if os.environ.get("COMMERCE_PLATFORM") == "shopify":
    from urllib.parse import urlsplit

    from commerce_platform.shopify_webhooks import webhook_router

    app.include_router(
        webhook_router(
            control_store,
            lambda tenant: (
                {
                    "domain": urlsplit(os.environ["SHOPIFY_URL"]).hostname,
                    "secret": os.environ["SHOPIFY_WEBHOOK_SECRET"],
                }
                if tenant == backend.merchant_id and os.environ.get("SHOPIFY_WEBHOOK_SECRET")
                else None
            ),
        )
    )
if isinstance(backend, MockRetail):
    app.include_router(
        create_merchant_router(backend, InMemoryMemoryStore()), prefix="/api/merchant"
    )
# The merchant portal shows the storefront's listing photos, so the API serves them to both apps.
app.mount("/products", StaticFiles(directory=PRODUCT_IMAGES, check_dir=False), name="products")


@app.post("/api/cart/add")
async def cart_add(request: CartAddRequest, record: host.CurrentSession) -> dict:
    return await host.direct_add(
        record,
        request,
        note="Customer tapped the add-to-cart button on {title} ({product_id}), quantity {quantity}.",
    )
