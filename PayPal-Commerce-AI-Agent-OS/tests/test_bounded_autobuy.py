# Copyright 2026 PayPal Commerce AI Agent OS contributors
# SPDX-License-Identifier: Apache-2.0

"""Bounded auto-buy: the host owns the prices, the cap, and the PayPal order.

These tests use an in-memory payment store so they exercise the real CheckoutService,
gates, and hosted checkout page without a database or a network call.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from commerce_common.payments import (
    AgentOrderReceipt,
    CheckoutDraft,
    CheckoutService,
    PaymentConflict,
    PaymentError,
    PaymentItem,
    PayPalConfig,
    PayPalOrder,
    SpendCapExceeded,
    money,
)
from demo_common.payments import PaymentRuntime, checkout_html, public_checkout
from shopping_agent import (
    Cart,
    CartItem,
    Product,
    ShoppingAgentConfig,
    ShoppingSessionContext,
    ShoppingSessionState,
)
from shopping_agent.gates import MAX_AGENT_ORDER_CAP, gated_create_paypal_order

CONFIG = PayPalConfig(client_id="public-client-id", client_secret="server-secret")
SESSION = ShoppingSessionContext(session_id="s-1", user_id="u-1")


class MemoryStore:
    """The PaymentStore protocol in memory: enough to run the real service."""

    def __init__(self) -> None:
        self.drafts: dict[str, CheckoutDraft] = {}
        self.creates = 0

    async def create(self, draft: CheckoutDraft) -> None:
        self.creates += 1
        self.drafts[draft.checkout_id] = draft

    async def get_by_token_hash(self, token_hash: str) -> CheckoutDraft | None:
        return next((d for d in self.drafts.values() if d.token_hash == token_hash), None)

    async def get_by_order_id(self, order_id: str) -> CheckoutDraft | None:
        return next((d for d in self.drafts.values() if d.paypal_order_id == order_id), None)

    async def update(self, draft: CheckoutDraft, expected_version: int) -> CheckoutDraft:
        current = self.drafts[draft.checkout_id]
        if current.version != expected_version:
            raise PaymentConflict("Checkout changed; retry the operation")
        updated = draft.model_copy(update={"version": expected_version + 1})
        self.drafts[draft.checkout_id] = updated
        return updated

    async def record_webhook(self, event_id: str, event_type: str) -> bool:
        return True

    async def forget_webhook(self, event_id: str) -> None:
        return None

    async def completed(self, merchant_id: str, user_id: str | None = None) -> list[CheckoutDraft]:
        return []

    async def commit_webhook(self, event_id, event_type, draft) -> bool:
        return True


class FakeProvider:
    config = CONFIG

    def __init__(self) -> None:
        self.creates = 0
        self.last_draft: CheckoutDraft | None = None

    async def create_order(self, draft: CheckoutDraft, request_id: str) -> PayPalOrder:
        self.creates += 1
        self.last_draft = draft
        return PayPalOrder(
            order_id="PAYPAL-ORDER-1",
            status="CREATED",
            approval_url="https://www.sandbox.paypal.com/checkoutnow?token=APPROVAL",
        )

    async def capture_order(self, order_id: str, request_id: str) -> PayPalOrder:
        raise AssertionError("the agent must never capture money")

    async def verify_webhook(self, headers, event) -> bool:
        return False


def cart(*items: CartItem, currency: str = "USD") -> Cart:
    return Cart(items=list(items), currency=currency)


def line(product_id: str, price: float, quantity: int = 1) -> CartItem:
    return CartItem(
        product_id=product_id, title=f"Item {product_id}", price=price, quantity=quantity
    )


def service(*, ceiling=None) -> tuple[CheckoutService, MemoryStore, FakeProvider]:
    store, provider = MemoryStore(), FakeProvider()
    return CheckoutService(store, provider, max_order_amount=ceiling), store, provider


def receipt(**overrides: Any) -> AgentOrderReceipt:
    values: dict[str, Any] = {
        "checkout_id": "co_test",
        "paypal_order_id": "PAYPAL-ORDER-1",
        "status": "created",
        "currency": "USD",
        "amount": money("42.00"),
        "spend_cap": money("50.00"),
        "cart_hash": "a" * 64,
        "items": (
            PaymentItem(product_id="SKU-1", name="Item SKU-1", unit_amount="42.00", quantity=1),
        ),
        "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=APPROVAL",
        "checkout_url": "https://shop.test/api/payments/paypal/checkout/BEARER-TOKEN",
    }
    values.update(overrides)
    return AgentOrderReceipt(**values)


class AgentOrderBackend:
    """Only the two methods the PayPal-native gate calls on a backend."""

    def __init__(self, current_cart: Cart, answer: AgentOrderReceipt | None = None) -> None:
        self.current_cart = current_cart
        self.answer = answer
        self.calls: list[tuple[list[str], Decimal]] = []

    async def get_cart(self, session) -> Cart:
        return self.current_cart

    async def create_paypal_order(self, session, *, product_ids, max_amount):
        self.calls.append((list(product_ids), max_amount))
        return self.answer


def state_with(*product_ids: str) -> ShoppingSessionState:
    state = ShoppingSessionState()
    state.remember_products(
        [Product(product_id=pid, title=f"Item {pid}", price=42.0) for pid in product_ids]
    )
    return state


# -- server-side cap -------------------------------------------------------------------


def test_effective_cap_clamps_to_the_host_ceiling_and_rejects_bad_caps():
    limited, _, _ = service(ceiling="250.00")
    assert limited.effective_cap("1000.00") == Decimal("250.00")
    assert limited.effective_cap("80.00") == Decimal("80.00")
    assert limited.effective_cap(None) == Decimal("250.00")
    with pytest.raises(PaymentError, match="greater than zero"):
        limited.effective_cap("0")
    with pytest.raises(ValueError, match="greater than zero"):
        service(ceiling="-1")


async def test_over_cap_cart_is_refused_before_any_payment_row_exists():
    limited, store, provider = service(ceiling="250.00")
    with pytest.raises(SpendCapExceeded, match="No PayPal order was created"):
        await limited.create_checkout(
            session_id=SESSION.session_id,
            user_id=SESSION.user_id,
            currency="USD",
            items=[PaymentItem(product_id="SKU-1", name="Tent", unit_amount="149.00", quantity=2)],
            spend_cap="200.00",
        )
    assert store.creates == 0 and provider.creates == 0


async def test_effective_cap_is_frozen_on_the_draft_and_rechecked_before_the_provider_call():
    limited, store, provider = service(ceiling="250.00")
    draft, token = await limited.create_checkout(
        session_id=SESSION.session_id,
        user_id=SESSION.user_id,
        currency="usd",
        items=[PaymentItem(product_id="SKU-1", name="Tent", unit_amount="42.00", quantity=1)],
        spend_cap="1000.00",
    )
    assert draft.spend_cap == Decimal("250.00")
    assert draft.amount == Decimal("42.00") and draft.currency == "USD"

    # A policy tightened after the quote was written still stops the provider call.
    limited.max_order_amount = Decimal("30.00")
    with pytest.raises(SpendCapExceeded):
        await limited.create_order(token)
    assert provider.creates == 0

    limited.max_order_amount = Decimal("250.00")
    created = await limited.create_order(token)
    assert created.paypal_order_id == "PAYPAL-ORDER-1"
    assert provider.creates == 1
    assert "server-secret" not in created.model_dump_json()


def test_agent_order_receipt_never_exposes_bearer_urls_to_the_model():
    view = receipt().model_view()
    assert "checkout_url" not in view and "approval_url" not in view
    assert view["paypal_order_id"] == "PAYPAL-ORDER-1"
    assert view["spend_cap"] == "50.00"


# -- host-owned order preparation ------------------------------------------------------


def runtime(*, current_cart: Cart, ceiling=None) -> PaymentRuntime:
    store, provider = MemoryStore(), FakeProvider()

    async def get_cart(session):
        del session
        return current_cart

    built = PaymentRuntime(
        config=CONFIG,
        database=Path("/unused/payments.sqlite3"),
        public_api_url="https://shop.test",
        store=store,
        max_order_amount=ceiling,
        backend=SimpleNamespace(get_cart=get_cart),
    )
    built.service.provider = provider
    return built


async def test_prepare_agent_order_prices_from_the_host_cart_and_clamps_the_cap():
    built = runtime(current_cart=cart(line("SKU-1", 42.0), line("SKU-2", 18.0)), ceiling="100.00")
    try:
        answer = await built.prepare_agent_order(
            SESSION, product_ids=["SKU-1"], max_amount=Decimal("10000.00")
        )
        assert answer.amount == Decimal("42.00")
        assert answer.spend_cap == Decimal("100.00")
        assert answer.paypal_order_id == "PAYPAL-ORDER-1"
        assert answer.items[0].unit_amount == Decimal("42.00")  # host price, not a model value
        assert answer.checkout_url.startswith("https://shop.test/api/payments/paypal/checkout/")
        assert "BEARER" not in answer.model_dump_json(exclude={"checkout_url"})
        assert built.service.provider.creates == 1
    finally:
        await built.provider.aclose()


async def test_prepare_agent_order_refuses_unknown_ids_empty_cart_and_cart_over_cap():
    built = runtime(current_cart=cart(line("SKU-1", 42.0)), ceiling="100.00")
    try:
        with pytest.raises(PaymentError, match="not in the cart"):
            await built.prepare_agent_order(SESSION, product_ids=["UNKNOWN"], max_amount="50")
        with pytest.raises(PaymentError, match="greater than zero"):
            await built.prepare_agent_order(SESSION, product_ids=["SKU-1"], max_amount="0")
        with pytest.raises(SpendCapExceeded):
            await built.prepare_agent_order(SESSION, product_ids=["SKU-1"], max_amount="10")
        assert built.service.provider.creates == 0

        empty = runtime(current_cart=cart(), ceiling="100.00")
        try:
            with pytest.raises(PaymentError, match="empty cart"):
                await empty.prepare_agent_order(SESSION, product_ids=["SKU-1"], max_amount="50")
        finally:
            await empty.provider.aclose()
    finally:
        await built.provider.aclose()


# -- the agent tool --------------------------------------------------------------------


async def test_paypal_tool_holds_unproven_ids_and_rejects_a_missing_cap():
    backend = AgentOrderBackend(cart(line("SKU-1", 42.0)), receipt())
    config = ShoppingAgentConfig(brand_name="ACME")
    held = await gated_create_paypal_order(
        backend=backend,
        config=config,
        session=SESSION,
        state=state_with(),
        product_ids=["SKU-1"],
        max_amount=50,
    )
    assert held.blocked == "provenance" and backend.calls == []

    for bad in (0, -5, None, "not-a-number", float("nan"), float("inf")):
        refused = await gated_create_paypal_order(
            backend=backend,
            config=config,
            session=SESSION,
            state=state_with("SKU-1"),
            product_ids=["SKU-1"],
            max_amount=bad,
        )
        assert refused.is_error and "spend cap" in refused.result_text.lower()
    assert backend.calls == []


async def test_paypal_tool_clamps_the_cap_and_keeps_the_bearer_url_out_of_model_text():
    backend = AgentOrderBackend(cart(line("SKU-1", 42.0)), receipt())
    outcome = await gated_create_paypal_order(
        backend=backend,
        config=ShoppingAgentConfig(brand_name="ACME"),
        session=SESSION,
        state=state_with("SKU-1"),
        product_ids=["SKU-1", "SKU-1"],  # deduplicated
        max_amount="999999999",
    )
    assert not outcome.refused
    assert backend.calls == [(["SKU-1"], MAX_AGENT_ORDER_CAP)]
    assert "BEARER-TOKEN" not in outcome.result_text
    assert "APPROVAL" not in outcome.result_text
    assert "PAYPAL-ORDER-1" in outcome.result_text
    assert "not captured or charged" in outcome.result_text

    assert len(outcome.events) == 1 and outcome.events[0].type == "ui"
    card = outcome.events[0].data["payload"]
    assert card["handoffs"][0]["url"].endswith("BEARER-TOKEN")
    assert card["receipt"]["paypal_order_id"] == "PAYPAL-ORDER-1"
    assert card["receipt"]["spend_cap"] == "50.00"
    assert "Nothing is charged" in card["note"]


async def test_paypal_tool_reports_an_unconfigured_store_without_offering_a_link():
    backend = AgentOrderBackend(cart(line("SKU-1", 42.0)), None)
    refused = await gated_create_paypal_order(
        backend=backend,
        config=ShoppingAgentConfig(brand_name="ACME"),
        session=SESSION,
        state=state_with("SKU-1"),
        product_ids=["SKU-1"],
        max_amount=50,
    )
    assert refused.is_error and "not configured" in refused.result_text
    assert refused.events == []


# -- the visible receipt ---------------------------------------------------------------


async def test_hosted_checkout_page_shows_the_cap_snapshot_and_paypal_order_id():
    limited, _, _ = service(ceiling="250.00")
    draft, token = await limited.create_checkout(
        session_id=SESSION.session_id,
        user_id=SESSION.user_id,
        currency="USD",
        items=[PaymentItem(product_id="SKU-1", name="Tent", unit_amount="42.00", quantity=1)],
        spend_cap="50.00",
    )
    draft = await limited.create_order(token)
    page = checkout_html(SimpleNamespace(config=CONFIG), draft, token)
    assert "Authorized spend cap" in page.body.decode()
    assert "50.00 USD" in page.body.decode()
    assert "PAYPAL-ORDER-1" in page.body.decode()
    assert f"sha256 {draft.cart_hash[:16]}" in page.body.decode()
    assert "server-secret" not in page.body.decode()

    public = public_checkout(draft)
    assert public["spend_cap"] == "50.00"
    assert public["paypal_order_id"] == "PAYPAL-ORDER-1"
    assert token not in str(public)
