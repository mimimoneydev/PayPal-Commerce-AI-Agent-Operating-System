# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""PayPal checkout routes installed by the shared storefront host when configured."""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from commerce_common.payments import (
    AgentOrderReceipt,
    CheckoutDraft,
    CheckoutService,
    PaymentConflict,
    PaymentError,
    PaymentItem,
    PaymentNotFound,
    PayPalClient,
    PayPalConfig,
    SQLitePaymentStore,
    drain_finalizations,
    money,
)
from shopping_agent import (
    Cart,
    CheckoutHandoff,
    Order,
    OrderItem,
    OrderStatus,
    ShoppingSessionContext,
    StorefrontBackend,
)


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
        merchant_id: str = "default",
        store=None,
        finalizer=None,
        max_order_amount=None,
        backend=None,
    ) -> None:
        self.config = config
        self.provider = PayPalClient(config)
        self.service = CheckoutService(
            store or SQLitePaymentStore(database),
            self.provider,
            merchant_id,
            max_order_amount=max_order_amount,
        )
        self.finalizer = finalizer or DemoOrderFinalizer()
        self.public_api_url = public_api_url.rstrip("/")
        self.backend = backend
        self.task: asyncio.Task | None = None

    async def start(self):
        initialize = getattr(self.service.store, "initialize", None)
        if initialize:
            await initialize()
        self.task = asyncio.create_task(self.work())

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.provider.aclose()

    async def work(self):
        while True:
            try:
                await drain_finalizations(self.service, self.finalizer)
            except Exception:
                # A database outage must not kill the recovery worker.
                logging.getLogger(__name__).warning("Payment finalization worker will retry")
            await asyncio.sleep(5)

    async def orders(self, user_id: str) -> list[Order]:
        return [
            Order(
                order_id=d.commerce_order_id,
                status=OrderStatus.PROCESSING,
                placed_at=d.created_at,
                items=[
                    OrderItem(
                        product_id=i.product_id,
                        title=i.name,
                        quantity=i.quantity,
                        price=float(i.unit_amount),
                    )
                    for i in d.items
                ],
                total=float(d.amount),
                currency=d.currency,
            )
            for d in await self.service.store.completed(self.service.merchant_id, user_id)
            if d.commerce_order_id
        ]

    def install_order_reads(self, backend):
        existing_orders, existing_order = backend.get_orders, backend.get_order

        async def get_orders(session, limit=5):
            orders = await existing_orders(session, limit)
            # The platform's record wins once it has shipment/refund updates.
            by_id = {o.order_id: o for o in await self.orders(session.user_id)}
            by_id.update({o.order_id: o for o in orders})
            return sorted(by_id.values(), key=lambda o: o.placed_at.timestamp(), reverse=True)[
                :limit
            ]

        async def get_order(session, order_id):
            existing = await existing_order(session, order_id)
            return existing or next(
                (o for o in await self.orders(session.user_id) if o.order_id == order_id), None
            )

        backend.get_orders, backend.get_order = get_orders, get_order

    async def sync_events(self, record):
        # Derive notifications from durable receipts, so a lost session write is retried.
        for draft in await self.service.store.completed(self.service.merchant_id, record.user_id):
            event_key = draft.checkout_id + (":order" if draft.commerce_order_id else ":payment")
            if event_key in record.payment_events:
                continue
            if draft.commerce_order_id:
                record.pending_app_events.append(
                    f"Payment confirmed. Order {draft.commerce_order_id} is processing; "
                    f"total {draft.amount:.2f} {draft.currency}. Do not charge again."
                )
            else:
                record.pending_app_events.append(
                    f"Payment of {draft.amount:.2f} {draft.currency} was received. "
                    "Order confirmation is still pending. Do not ask the customer to pay again."
                )
            record.payment_events.append(event_key)

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

    async def prepare_agent_order(
        self,
        session: ShoppingSessionContext,
        *,
        product_ids: list[str],
        max_amount,
    ) -> AgentOrderReceipt:
        """The host-owned half of the agent's ``create_paypal_order`` tool.

        The model supplies only ids and a cap. Prices, titles, quantities, currency, and
        the immutable cart snapshot all come from the server's own cart read, never from
        model arguments. The cap is re-validated and clamped inside ``CheckoutService``
        before anything is persisted or sent to PayPal. The agent cannot capture money:
        buyer approval happens on the PayPal-hosted page and the host captures it.
        """
        if self.backend is None:
            raise PaymentError("Agent checkout is not wired to a storefront backend")
        cart = await self.backend.get_cart(session)
        if not cart.items:
            raise PaymentError("Cannot create a PayPal order for an empty cart")
        requested = list(dict.fromkeys(str(pid) for pid in product_ids))
        if not requested:
            raise PaymentError("No products were selected for the bounded order")
        by_id = {item.product_id: item for item in cart.items}
        unknown = [pid for pid in requested if pid not in by_id]
        if unknown:
            raise PaymentError("Selected products are not in the cart")
        items = [
            PaymentItem(
                product_id=by_id[pid].product_id,
                name=by_id[pid].title,
                unit_amount=by_id[pid].price,
                quantity=by_id[pid].quantity,
            )
            for pid in requested
        ]
        cap = money(max_amount)
        if cap <= 0:
            raise PaymentError("The spend cap must be greater than zero")
        draft, token = await self.service.create_checkout(
            session_id=session.session_id,
            user_id=session.user_id,
            currency=cart.currency,
            items=items,
            spend_cap=cap,
        )
        created = await self.service.create_order(token)
        if not created.paypal_order_id or draft.spend_cap is None:
            raise PaymentError("The bounded order could not be prepared")
        return AgentOrderReceipt(
            checkout_id=created.checkout_id,
            paypal_order_id=created.paypal_order_id,
            status=created.status,
            currency=created.currency,
            amount=created.amount,
            spend_cap=draft.spend_cap,
            cart_hash=created.cart_hash,
            items=created.items,
            approval_url=created.approval_url,
            checkout_url=f"{self.public_api_url}/api/payments/paypal/checkout/{token}",
        )


def payment_runtime_from_env(
    *, example_root: Path, backend: StorefrontBackend
) -> PaymentRuntime | None:
    # --no-paypal (and a direct uvicorn run that sets this) is the only opt-out.
    # With credentials present, checkout is on by default; there is no second opt-in.
    if os.environ.get("COMMERCE_PAYPAL_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return None
    config = PayPalConfig.from_env()
    if config is None:
        return None
    public_url = os.environ.get("COMMERCE_PUBLIC_API_URL", "").strip()
    if not public_url:
        raise ValueError("COMMERCE_PUBLIC_API_URL is required when PayPal checkout is enabled")
    database = Path(
        os.environ.get("COMMERCE_PAYMENT_DB") or example_root / "data" / ".payments.sqlite3"
    )
    store = None
    if dsn := os.environ.get("COMMERCE_PAYMENT_DATABASE_URL"):
        from commerce_common.payment_store import PostgresPaymentStore

        store = PostgresPaymentStore(dsn)
    if not config.sandbox:
        raise ValueError(
            "The demo host cannot accept live payments. Use an authenticated production host "
            "with final pricing and an OrderFinalizer; see docs/payments.md."
        )
    runtime = PaymentRuntime(
        config=config,
        database=database,
        public_api_url=public_url,
        merchant_id=os.environ.get("COMMERCE_MERCHANT_ID", example_root.name),
        store=store,
        max_order_amount=os.environ.get("COMMERCE_MAX_ORDER_AMOUNT") or None,
        backend=backend,
    )
    backend.set_checkout_handoff_provider(runtime.handoff)
    # The PayPal-native tool in the agent loop reaches only this host-owned callable.
    backend.set_paypal_order_provider(runtime.prepare_agent_order)
    runtime.install_order_reads(backend)
    return runtime


class DemoOrderFinalizer:
    async def finalize(self, draft, idempotency_key):
        # The paid snapshot itself is the demo's persistent order record. Its primary
        # key deduplicates retries, including restarts after payment and before this call.
        return f"ORDER-{idempotency_key}"


def public_checkout(draft: CheckoutDraft) -> dict[str, Any]:
    return {
        "checkout_id": draft.checkout_id,
        "status": draft.status,
        "currency": draft.currency,
        "amount": f"{draft.amount:.2f}",
        "spend_cap": f"{draft.spend_cap:.2f}" if draft.spend_cap is not None else None,
        "cart_hash": draft.cart_hash,
        "paypal_order_id": draft.paypal_order_id,
        "order_id": draft.commerce_order_id,
        "order_status": "processing" if draft.commerce_order_id else "pending",
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
            **(
                {"merchant-id": runtime.config.seller_merchant_id}
                if runtime.config.seller_merchant_id
                else {}
            ),
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
    # The bounded auto-buy receipt is visible on the page a judge can screenshot: the
    # cap, the immutable snapshot hash, and PayPal's own order id. Nothing here is
    # model-authored; every figure comes from the persisted CheckoutDraft.
    receipt = ""
    if draft.spend_cap is not None:
        cap = html.escape(f"{draft.spend_cap:.2f} {draft.currency}")
        receipt += (
            f'<p class="safe">Authorized spend cap: <strong>{cap}</strong>. '
            f"Snapshot {html.escape(draft.checkout_id)} "
            f"· sha256 {html.escape(draft.cart_hash[:16])}…</p>"
        )
    if draft.paypal_order_id:
        receipt += (
            '<p class="safe">PayPal order '
            f"<strong>{html.escape(draft.paypal_order_id)}</strong> "
            f"· status {html.escape(str(draft.provider_status or draft.status))}</p>"
        )
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Secure PayPal checkout</title>
<style nonce="{nonce}">
body{{margin:0;background:#f5f7fa;color:#172c48;font:16px system-ui,sans-serif}}main{{max-width:620px;margin:5vh auto;padding:28px;background:white;border-radius:20px;box-shadow:0 12px 40px #172c4820}}h1{{margin-top:0}}ul{{list-style:none;padding:0;border-block:1px solid #dde3ea}}li,.total{{display:flex;justify-content:space-between;gap:20px;padding:14px 0}}.total{{font-size:1.2rem}}#message{{min-height:24px}}.safe{{font-size:.85rem;color:#52677e}}button{{font:inherit}}
</style></head><body><main>
<h1>Review and pay</h1><ul>{lines}</ul><div class="total"><span>Total</span><strong>{amount}</strong></div>
{receipt}
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
    message.textContent='Payment received. Your order is being confirmed. Please do not pay again.';
    document.getElementById('paypal-button-container').replaceChildren();
    await watchOrder();
  }},
  onCancel(){{message.textContent='Payment cancelled. Nothing was charged.';}},
  onError(error){{message.textContent=error.message||'PayPal checkout could not complete.';}}
}}).render('#paypal-button-container');
async function watchOrder(){{
  for(let attempt=0;attempt<30;attempt++){{
    try {{
      const response=await fetch(`/api/payments/paypal/checkout/${{encodeURIComponent(token)}}/status`);
      const result=await response.json();
      if(response.ok && result.order_id){{
        message.textContent=`Order ${{result.order_id}} confirmed. Return to the store to view it or ask the assistant about your purchase.`;
        document.getElementById('paypal-button-container').replaceChildren();
        return;
      }}
      if(result.status==='completed'){{
        message.textContent='Payment received. Your order is being confirmed. Please do not pay again.';
        document.getElementById('paypal-button-container').replaceChildren();
      }}
    }} catch(error) {{ /* Payment remains durable; a reload resumes this status check. */ }}
    await new Promise(resolve=>setTimeout(resolve,2000));
  }}
}}
if({json.dumps(draft.status == "completed")}) watchOrder();
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
        return {**public_checkout(draft), "order_id": draft.paypal_order_id}

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
