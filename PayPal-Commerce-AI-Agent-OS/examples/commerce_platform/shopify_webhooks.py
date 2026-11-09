"""Verified Shopify receipts. No shopper identity is accepted from order notes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextlib import suppress
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from commerce_common.accounting import record_order
from commerce_common.control_store import Conflict
from shopping_agent.types import Order, OrderItem


def ingest_order(store, tenant, payload):
    token = payload.get("cart_token")
    if not token:
        return False
    mapping = store.get(tenant, "cart_owners", hashlib.sha256(token.encode()).hexdigest())
    if not mapping:
        return False
    financial = payload.get("financial_status")
    if financial not in {"paid", "partially_refunded", "refunded"}:
        return False
    order_id = str(payload["id"])
    old = store.get(tenant, "shopify_orders", order_id)
    updated = datetime.fromisoformat(payload["updated_at"].replace("Z", "+00:00"))
    if old and datetime.fromisoformat(old["data"]["updated_at"]) >= updated:
        return True
    currency = payload["currency"]
    refunds = []
    for refund in payload.get("refunds", []):
        for transaction in refund.get("transactions", []):
            if transaction.get("kind") == "refund" and transaction.get("status") == "success":
                if transaction.get("currency", currency) != currency:
                    raise ValueError("Refund currency mismatch")
                refunds.append({"id": transaction["id"], "amount": transaction["amount"]})
    record_order(store, tenant, "shopify", order_id, currency, payload["total_price"], refunds)
    status = "processing"
    tracking = None
    if payload.get("fulfillment_status") == "fulfilled":
        status = "shipped"  # Never infer delivered from fulfillment creation.
        fulfillments = payload.get("fulfillments") or []
        tracking = fulfillments[-1].get("tracking_url") if fulfillments else None
        if tracking and not tracking.startswith("https://"):
            tracking = None
    if payload.get("cancelled_at"):
        status = "cancelled"
    if financial == "refunded":
        status = "refunded"
    order = Order(
        order_id=order_id,
        status=status,
        placed_at=payload["created_at"],
        total=float(payload["total_price"]),
        currency=currency,
        tracking_url=tracking,
        items=[
            OrderItem(
                product_id=f"gid://shopify/ProductVariant/{line['variant_id']}",
                title=line["title"],
                quantity=line["quantity"],
                price=float(line["price"]),
            )
            for line in payload.get("line_items", [])
        ],
    )
    # Create the review before the receipt. A retry after any interruption is safe.
    if not store.get(tenant, "fraud_reviews", order_id):
        with suppress(Conflict):
            store.put(
                tenant,
                "fraud_reviews",
                order_id,
                {"decision": "hold", "reason": "Awaiting merchant review", "source": "shopify"},
            )
    store.put(
        tenant,
        "shopify_orders",
        order_id,
        {
            "owner": mapping["data"]["owner"],
            "updated_at": updated.isoformat(),
            "order": order.model_dump(mode="json"),
        },
        version=old["version"] if old else 0,
    )
    return True


def webhook_router(store, config_for_tenant):
    router = APIRouter()

    @router.post("/webhooks/shopify/{tenant}")
    async def webhook(tenant: str, request: Request):
        config = config_for_tenant(tenant)
        if not config:
            raise HTTPException(404)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2_000_000:
                raise HTTPException(413)
        expected = base64.b64encode(
            hmac.new(config["secret"].encode(), raw, hashlib.sha256).digest()
        ).decode()
        if not hmac.compare_digest(expected, request.headers.get("x-shopify-hmac-sha256", "")):
            raise HTTPException(401, "Invalid signature")
        if request.headers.get("x-shopify-shop-domain") != config["domain"]:
            raise HTTPException(403, "Store mismatch")
        if request.headers.get("x-shopify-topic") not in {
            "orders/paid",
            "orders/updated",
            "orders/cancelled",
        }:
            raise HTTPException(422, "Unsupported topic")
        try:
            matched = ingest_order(store, tenant, json.loads(raw))
        except Conflict as error:
            raise HTTPException(409, "Concurrent delivery; retry") from error
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(422, "Invalid order payload or unsupported currency") from error
        return {"received": True, "matched": matched}

    return router
