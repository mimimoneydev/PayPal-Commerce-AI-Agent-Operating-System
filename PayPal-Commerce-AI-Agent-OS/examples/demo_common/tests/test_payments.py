# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

from decimal import Decimal
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from commerce_common.payments import (
    CheckoutService,
    PaymentItem,
    PayPalConfig,
    PayPalOrder,
    SQLitePaymentStore,
)
from demo_common.payments import build_payment_router


class FakeProvider:
    config = PayPalConfig(client_id="public-client-id", client_secret="server-secret")

    async def create_order(self, draft, request_id):
        return PayPalOrder(order_id="ORDER-1", status="CREATED")

    async def capture_order(self, order_id, request_id):
        return PayPalOrder(
            order_id=order_id,
            status="COMPLETED",
            capture_id="CAPTURE-1",
            amount=Decimal("19.50"),
            currency="USD",
        )

    async def verify_webhook(self, headers, event):
        return True


async def test_hosted_checkout_hides_identity_and_completes_server_capture(tmp_path):
    provider = FakeProvider()
    service = CheckoutService(SQLitePaymentStore(tmp_path / "payments.sqlite3"), provider)
    _, token = await service.create_checkout(
        session_id="secret-session-id",
        user_id="private-user-id",
        currency="USD",
        items=[PaymentItem(product_id="SKU-1", name="Camp light", unit_amount="19.50", quantity=1)],
    )
    runtime = SimpleNamespace(config=provider.config, service=service)
    app = FastAPI()
    app.include_router(build_payment_router(runtime))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        page = await client.get(f"/api/payments/paypal/checkout/{token}")
        assert page.status_code == 200
        assert "public-client-id" in page.text
        assert "server-secret" not in page.text
        assert "secret-session-id" not in page.text
        assert "private-user-id" not in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["cache-control"] == "no-store"

        created = await client.post(f"/api/payments/paypal/checkout/{token}/order")
        assert created.status_code == 200 and created.json()["order_id"] == "ORDER-1"
        captured = await client.post(
            f"/api/payments/paypal/checkout/{token}/capture", json={"order_id": "ORDER-1"}
        )
        assert captured.status_code == 200
        assert captured.json()["status"] == "completed"


async def test_paid_receipt_reaches_order_reads_and_next_conversation(tmp_path, backend):
    from commerce_common.payments import drain_finalizations
    from demo_common.payments import PaymentRuntime
    from demo_common.sessions import SessionStore
    from shopping_agent import ShoppingSessionContext, ShoppingSessionState

    runtime = PaymentRuntime(
        config=FakeProvider.config,
        database=tmp_path / "receipts.db",
        public_api_url="https://checkout.test",
    )
    runtime.service.provider = FakeProvider()
    sessions = SessionStore(ShoppingSessionState)
    record = sessions.start("buyer")
    session = ShoppingSessionContext(session_id=record.session_id, user_id="buyer")
    _, token = await runtime.service.create_checkout(
        session_id=record.session_id,
        user_id="buyer",
        currency="USD",
        items=[PaymentItem(product_id="sku", name="Camp light", unit_amount="19.50", quantity=1)],
    )
    await runtime.service.create_order(token)
    await runtime.service.capture(token, "ORDER-1")
    await runtime.sync_events(record)
    assert "Do not ask the customer to pay again" in record.pending_app_events[-1]
    assert await drain_finalizations(runtime.service, runtime.finalizer) == 1
    runtime.install_order_reads(backend)
    orders = await backend.get_orders(session)
    receipt = next(o for o in orders if o.order_id.startswith("ORDER-co_"))
    assert receipt.total == 19.5
    await runtime.sync_events(record)
    sessions.save(record)
    restored = sessions.require(record.session_id)
    await runtime.sync_events(restored)
    assert len(restored.pending_app_events) == 2
    assert receipt.order_id in restored.pending_app_events[-1]
    outsider = ShoppingSessionContext(session_id="other", user_id="another-buyer")
    assert await backend.get_order(outsider, receipt.order_id) is None
    await runtime.close()
