import json

import httpx
import pytest
from cryptography.fernet import Fernet

from commerce_common.accounting import minor_units, record_order
from commerce_common.control_store import Conflict, ControlStore
from commerce_platform.operations import execute_provider


async def test_woo_operation_has_stable_key_and_signed_payload(monkeypatch):
    calls = []
    real_client = httpx.AsyncClient

    def remote(request):
        calls.append(request)
        assert request.url.path.endswith("/operations")
        assert len(request.headers["x-agent-signature"]) == 64
        body = json.loads(request.content)
        assert body["operation_id"] == "a" * 32
        assert body["kind"] == "refund" and body["payload"]["amount"] == "2.00"
        return httpx.Response(200, json={"status": "completed", "refund_id": "5"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(remote), **kwargs),
    )
    result = await execute_provider(
        "tenant",
        {"platform": "woocommerce", "url": "https://store.test", "secret": "s" * 32},
        {},
        {"kind": "refund", "order_id": "42", "payload": {"amount": "2.00"}},
        "a" * 32,
    )
    assert result["refund_id"] == "5" and len(calls) == 1


async def test_shopify_fulfillment_reads_paid_order_then_creates(monkeypatch):
    calls = []
    real_client = httpx.AsyncClient

    def remote(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["x-shopify-access-token"] == "admin-token"
        if "query" in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "order": {
                            "cancelledAt": None,
                            "displayFinancialStatus": "PAID",
                            "fulfillmentOrders": {
                                "nodes": [
                                    {"id": "gid://shopify/FulfillmentOrder/7", "status": "OPEN"}
                                ],
                                "pageInfo": {"hasNextPage": False},
                            },
                        }
                    }
                },
            )
        assert body["variables"]["input"]["lineItemsByFulfillmentOrder"] == [
            {"fulfillmentOrderId": "gid://shopify/FulfillmentOrder/7"}
        ]
        return httpx.Response(
            200,
            json={
                "data": {
                    "fulfillmentCreate": {
                        "fulfillment": {"id": "shipment", "status": "SUCCESS"},
                        "userErrors": [],
                    }
                }
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(remote), **kwargs),
    )
    result = await execute_provider(
        "tenant",
        {"platform": "shopify", "url": "https://store.myshopify.com"},
        {"shopify_admin_token": "admin-token"},
        {
            "kind": "shipment",
            "order_id": "42",
            "payload": {"tracking_number": "123", "tracking_url": "https://carrier.test/123"},
        },
        "a" * 32,
    )
    assert result["fulfillment_id"] == "shipment" and len(calls) == 2


async def test_paypal_evidence_capability_checked_without_following_link(monkeypatch):
    calls = []
    real_client = httpx.AsyncClient

    def remote(request):
        calls.append(request)
        assert request.url.host == "api-m.sandbox.paypal.com"
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 300})
        if request.method == "GET":
            return httpx.Response(
                200, json={"links": [{"rel": "provide_evidence", "href": "https://evil.test/"}]}
            )
        assert request.url.path == "/v1/customer/disputes/PP-D-123/provide-evidence"
        assert json.loads(request.content)["evidences"][0]["notes"] == "Evidence"
        return httpx.Response(204)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(remote), **kwargs),
    )
    result = await execute_provider(
        "tenant",
        {},
        {"paypal_client_id": "id", "paypal_client_secret": "secret"},
        {"kind": "dispute_evidence", "order_id": "PP-D-123", "payload": {"notes": "Evidence"}},
        "a" * 32,
    )
    assert result["submitted"] and len(calls) == 3


def test_accounting_minor_units_duplicate_refunds_and_conflicting_totals(tmp_path):
    store = ControlStore("sqlite:///" + str(tmp_path / "ledger.db"), Fernet.generate_key().decode())
    assert minor_units("1.234", "KWD") == 1234
    assert minor_units("1250", "UGX") == 1250
    for value, currency in [("1.001", "USD"), ("NaN", "USD"), ("1", "XXX"), ("-1", "USD")]:
        with pytest.raises(ValueError):
            minor_units(value, currency)
    for _ in range(2):
        record_order(
            store, "a", "woocommerce", "42", "USD", "10.00", [{"id": "5", "amount": "2.00"}]
        )
    assert len(store.list("a", "ledger")) == 2
    with pytest.raises(Conflict):
        record_order(store, "a", "woocommerce", "42", "USD", "11.00", [])
