# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from commerce_common.payments import (
    CheckoutService,
    CheckoutStatus,
    PaymentConflict,
    PaymentItem,
    PayPalClient,
    PayPalConfig,
    PayPalOrder,
    SQLitePaymentStore,
)


class FakePayPal:
    config = PayPalConfig(client_id="client", client_secret="secret")

    def __init__(self) -> None:
        self.creates = 0
        self.captures = 0
        self.webhook_valid = True

    async def create_order(self, draft, request_id):
        self.creates += 1
        assert request_id == f"{draft.checkout_id}-create"
        return PayPalOrder(order_id="PAYPAL-1", status="CREATED")

    async def capture_order(self, order_id, request_id):
        self.captures += 1
        assert order_id == "PAYPAL-1"
        assert request_id.endswith("-capture")
        return PayPalOrder(
            order_id=order_id,
            status="COMPLETED",
            capture_id="CAPTURE-1",
            amount=Decimal("25.98"),
            currency="USD",
        )

    async def verify_webhook(self, headers, event):
        return self.webhook_valid


@pytest.fixture
def provider():
    return FakePayPal()


@pytest.fixture
def service(tmp_path, provider):
    return CheckoutService(SQLitePaymentStore(tmp_path / "payments.sqlite3"), provider)


async def new_checkout(service):
    return await service.create_checkout(
        session_id="session-1",
        user_id="user-1",
        currency="usd",
        items=[PaymentItem(product_id="SKU-1", name="Trail cup", unit_amount=12.99, quantity=2)],
    )


async def test_checkout_stores_only_token_digest_and_exact_cart_quote(service):
    draft, token = await new_checkout(service)
    assert token not in draft.model_dump_json()
    assert draft.amount == Decimal("25.98")
    assert draft.currency == "USD"
    assert (await service.require(token)).checkout_id == draft.checkout_id


async def test_create_and_capture_are_idempotent(service, provider):
    _, token = await new_checkout(service)
    created = await service.create_order(token)
    repeated = await service.create_order(token)
    assert created.paypal_order_id == repeated.paypal_order_id == "PAYPAL-1"
    assert provider.creates == 1

    paid = await service.capture(token, "PAYPAL-1")
    repeated_paid = await service.capture(token, "PAYPAL-1")
    assert paid.status == repeated_paid.status == CheckoutStatus.COMPLETED
    assert paid.capture_id == "CAPTURE-1"
    assert provider.captures == 1


async def test_capture_rejects_an_order_from_another_checkout(service):
    _, token = await new_checkout(service)
    await service.create_order(token)
    with pytest.raises(PaymentConflict, match="does not belong"):
        await service.capture(token, "PAYPAL-OTHER")


async def test_capture_rejects_provider_amount_mismatch(service, provider):
    _, token = await new_checkout(service)
    await service.create_order(token)

    async def wrong_amount(order_id, request_id):
        return PayPalOrder(
            order_id=order_id,
            status="COMPLETED",
            capture_id="CAPTURE-X",
            amount=Decimal("1.00"),
            currency="USD",
        )

    provider.capture_order = wrong_amount
    with pytest.raises(PaymentConflict, match="amount or currency"):
        await service.capture(token, "PAYPAL-1")


async def test_webhook_is_verified_and_deduplicated(service):
    _, token = await new_checkout(service)
    await service.create_order(token)
    event = {
        "id": "WH-1",
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {"id": "PAYPAL-1"},
    }
    processed, approved = await service.process_webhook({}, event)
    repeated, duplicate = await service.process_webhook({}, event)
    assert processed and approved and approved.status == CheckoutStatus.APPROVED
    assert not repeated and duplicate is None


async def test_paypal_client_uses_oauth_idempotency_and_orders_v2(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={"id": "ORDER-1", "status": "CREATED"})
        raise AssertionError(request.url.path)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PayPalClient(PayPalConfig(client_id="id", client_secret="secret"), http)
    store = SQLitePaymentStore(tmp_path / "client.sqlite3")
    service = CheckoutService(store, FakePayPal())
    draft, _ = await service.create_checkout(
        session_id="s",
        user_id="u",
        currency="USD",
        items=[PaymentItem(product_id="SKU", name="Item", unit_amount="3.50", quantity=2)],
    )
    order = await client.create_order(draft, "request-1")
    assert order.order_id == "ORDER-1"
    assert requests[1].headers["paypal-request-id"] == "request-1"
    assert requests[1].headers["authorization"] == "Bearer token"
    assert b'"value":"7.00"' in requests[1].content
    await http.aclose()


async def test_get_order_reads_purchase_amount_before_buyer_approval():
    """Resume mode must be able to check a PAYER_ACTION_REQUIRED order's real money."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders/ORDER-2":
            return httpx.Response(
                200,
                json={
                    "id": "ORDER-2",
                    "status": "PAYER_ACTION_REQUIRED",
                    "purchase_units": [{"amount": {"currency_code": "USD", "value": "219.00"}}],
                    "links": [
                        {
                            "rel": "approve",
                            "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-2",
                        }
                    ],
                },
            )
        raise AssertionError(request.url.path)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = PayPalClient(PayPalConfig(client_id="id", client_secret="secret"), http)
    order = await client.get_order("ORDER-2")
    assert order.status == "PAYER_ACTION_REQUIRED"
    assert order.purchase_amount == Decimal("219.00")
    assert order.purchase_currency == "USD"
    # No capture exists yet, so the capture-specific fields stay empty.
    assert order.amount is None
    assert order.capture_id is None
    assert order.approval_url and "checkoutnow" in order.approval_url
    await http.aclose()
