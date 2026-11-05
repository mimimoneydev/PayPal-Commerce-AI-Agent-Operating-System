# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""PayPal checkout routes installed by the shared storefront host when configured."""

from __future__ import annotations

import html
import json
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from commerce_common.payments import (
    CheckoutDraft,
    CheckoutService,
    PaymentConflict,
    PaymentError,
    PaymentItem,
    PaymentNotFound,
    PayPalClient,
    PayPalConfig,
    SQLitePaymentStore,
)
from shopping_agent import Cart, CheckoutHandoff, ShoppingSessionContext, StorefrontBackend


class CaptureRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


class PaymentRuntime:
    """One deployment's provider, store, handoff factory, and HTTP routes."""

    def __init__(
        self,
        *,
        config: PayPalConfig,
        database: Path,
        public_api_url: str,
    ) -> None:
        self.config = config
        self.provider = PayPalClient(config)
        self.service = CheckoutService(SQLitePaymentStore(database), self.provider)
        self.public_api_url = public_api_url.rstrip("/")

    async def handoff(self, session: ShoppingSessionContext, cart: Cart) -> list[CheckoutHandoff]:
        _, token = await self.service.create_checkout(
            session_id=session.session_id,
            user_id=session.user_id,
            currency=cart.currency,
            items=[
                PaymentItem(
                    product_id=item.product_id,
                    name=item.title,
                    unit_amount=item.price,
                    quantity=item.quantity,
                )
                for item in cart.items
            ],
        )
        return [
            CheckoutHandoff(
                url=f"{self.public_api_url}/api/payments/paypal/checkout/{token}",
                label="Pay securely with PayPal",
            )
        ]


def payment_runtime_from_env(
    *, example_root: Path, backend: StorefrontBackend
) -> PaymentRuntime | None:
    config = PayPalConfig.from_env()
    if config is None:
        return None
    public_url = os.environ.get("COMMERCE_PUBLIC_API_URL", "").strip()
    if not public_url:
        raise ValueError("COMMERCE_PUBLIC_API_URL is required when PayPal checkout is enabled")
    database = Path(
        os.environ.get("COMMERCE_PAYMENT_DB") or example_root / "data" / ".payments.sqlite3"
    )
    runtime = PaymentRuntime(config=config, database=database, public_api_url=public_url)
    backend.set_checkout_handoff_provider(runtime.handoff)
    return runtime


def public_checkout(draft: CheckoutDraft) -> dict[str, Any]:
    return {
        "checkout_id": draft.checkout_id,
        "status": draft.status,
        "currency": draft.currency,
        "amount": f"{draft.amount:.2f}",
        "items": [
            {
                "name": item.name,
                "quantity": item.quantity,
                "unit_amount": f"{item.unit_amount:.2f}",
            }
            for item in draft.items
        ],
    }


def checkout_html(runtime: PaymentRuntime, draft: CheckoutDraft, token: str) -> HTMLResponse:
    nonce = secrets.token_urlsafe(18)
    sdk_query = urlencode(
        {
            "client-id": runtime.config.client_id,
            "currency": draft.currency,
            "intent": "capture",
            "components": "buttons",
        }
    )
    sdk_url = f"{runtime.config.javascript_url}?{sdk_query}"
    token_json = json.dumps(token)
    amount = html.escape(f"{draft.amount:.2f} {draft.currency}")
    lines = "".join(
        f"<li><span>{html.escape(item.name)} × {item.quantity}</span>"
        f"<strong>{html.escape(f'{item.total:.2f} {draft.currency}')}</strong></li>"
        for item in draft.items
    )
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Secure PayPal checkout</title>
<style nonce="{nonce}">
body{{margin:0;background:#f5f7fa;color:#172c48;font:16px system-ui,sans-serif}}main{{max-width:620px;margin:5vh auto;padding:28px;background:white;border-radius:20px;box-shadow:0 12px 40px #172c4820}}h1{{margin-top:0}}ul{{list-style:none;padding:0;border-block:1px solid #dde3ea}}li,.total{{display:flex;justify-content:space-between;gap:20px;padding:14px 0}}.total{{font-size:1.2rem}}#message{{min-height:24px}}.safe{{font-size:.85rem;color:#52677e}}button{{font:inherit}}
</style></head><body><main>
<h1>Review and pay</h1><ul>{lines}</ul><div class="total"><span>Total</span><strong>{amount}</strong></div>
<div id="paypal-button-container"></div><p id="message" role="status"></p>
<p class="safe">Payment details are collected by PayPal and are never shared with the commerce agent.</p>
</main><script nonce="{nonce}" src="{html.escape(sdk_url, quote=True)}"></script>
<script nonce="{nonce}">
const token={token_json}; const message=document.getElementById('message');
paypal.Buttons({{
  async createOrder(){{
    message.textContent='Creating your secure order…';
    const response=await fetch(`/api/payments/paypal/checkout/${{encodeURIComponent(token)}}/order`,{{method:'POST',headers:{{'Content-Type':'application/json'}}}});
    const data=await response.json(); if(!response.ok) throw new Error(data.detail||'Could not create the order');
    message.textContent=''; return data.order_id;
  }},
  async onApprove(data){{
    message.textContent='Confirming your payment…';
    const response=await fetch(`/api/payments/paypal/checkout/${{encodeURIComponent(token)}}/capture`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{order_id:data.orderID}})}});
    const result=await response.json(); if(!response.ok) throw new Error(result.detail||'Could not capture the payment');
    message.textContent='Payment complete. You can close this page.';
    document.getElementById('paypal-button-container').replaceChildren();
  }},
  onCancel(){{message.textContent='Payment cancelled. Nothing was charged.';}},
  onError(error){{message.textContent=error.message||'PayPal checkout could not complete.';}}
}}).render('#paypal-button-container');
</script></body></html>"""
    response = HTMLResponse(body)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}' https://www.paypal.com https://www.sandbox.paypal.com; "
        f"style-src 'nonce-{nonce}'; img-src https://*.paypal.com data:; "
        "connect-src 'self' https://*.paypal.com; frame-src https://*.paypal.com; "
        "form-action https://*.paypal.com; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def build_payment_router(runtime: PaymentRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/payments/paypal", tags=["payments"])

    @router.get("/checkout/{token}", response_class=HTMLResponse)
    async def show_checkout(token: str) -> HTMLResponse:
        try:
            draft = await runtime.service.require(token)
        except PaymentNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        return checkout_html(runtime, draft, token)

    @router.get("/checkout/{token}/status")
    async def checkout_status(token: str) -> dict[str, Any]:
        try:
            return public_checkout(await runtime.service.require(token))
        except PaymentNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from None

    @router.post("/checkout/{token}/order")
    async def create_order(token: str) -> dict[str, Any]:
        try:
            draft = await runtime.service.create_order(token)
        except PaymentNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        except PaymentError as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        return {"order_id": draft.paypal_order_id, **public_checkout(draft)}

    @router.post("/checkout/{token}/capture")
    async def capture(token: str, request: CaptureRequest) -> dict[str, Any]:
        try:
            draft = await runtime.service.capture(token, request.order_id)
        except PaymentNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        except PaymentConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except PaymentError as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        return {"ok": True, **public_checkout(draft)}

    @router.post("/webhook")
    async def webhook(request: Request) -> dict[str, Any]:
        try:
            raw = await request.body()
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Malformed JSON") from None
        try:
            processed, draft = await runtime.service.process_webhook(request.headers, event)
        except PaymentError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        return {
            "ok": True,
            "processed": processed,
            "checkout_id": draft.checkout_id if draft else None,
        }

    return router
