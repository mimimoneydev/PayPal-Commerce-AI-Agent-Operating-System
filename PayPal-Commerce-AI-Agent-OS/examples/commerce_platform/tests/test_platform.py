import base64
import hashlib
import hmac
import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from commerce_common.control_store import Conflict, ControlStore
from commerce_common.operations import Operations
from commerce_platform.app import create_app
from commerce_platform.shopify_webhooks import ingest_order
from commerce_platform.storefronts import DurableSessions
from demo_common.sessions import SessionConflictError, UnknownSessionError


@pytest.fixture
def store(tmp_path):
    return ControlStore("sqlite:///" + str(tmp_path / "control.db"), Fernet.generate_key().decode())


def client_for(store, email):
    app = create_app(store, origin="https://admin.test", invitation="invite", secure=True)
    client = TestClient(
        app, base_url="https://admin.test", headers={"origin": "https://admin.test"}
    )
    credentials = {"email": email, "password": "test-password-long", "invitation": "invite"}
    assert client.post("/api/register", json=credentials).status_code == 201
    result = client.post("/api/login", json=credentials)
    assert "HttpOnly" in result.headers["set-cookie"] and "Secure" in result.headers["set-cookie"]
    client.headers["x-csrf-token"] = result.json()["csrf"]
    return client


def test_admin_isolation_csrf_and_encrypted_connection(store):
    alice, bob = client_for(store, "alice@test.dev"), client_for(store, "bob@test.dev")
    tenant = alice.post("/api/merchants", json={"name": "Alice"}).json()["id"]
    path = f"/api/merchants/{tenant}"
    assert bob.get("/api/merchants").json() == []
    assert bob.get(path + "/connection").status_code == 403
    assert (
        alice.post(
            "/api/merchants", json={"name": "No"}, headers={"x-csrf-token": "bad"}
        ).status_code
        == 403
    )
    assert (
        alice.post(
            "/api/merchants", json={"name": "No"}, headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )
    config = {
        "platform": "shopify",
        "url": "https://alice.myshopify.com",
        "secret": "token" * 10,
        "webhook_secret": "signing",
    }
    assert alice.put(path + "/connection", json=config).status_code == 200
    assert config["secret"] not in alice.get(path + "/connection").text
    assert config["secret"] not in json.dumps(store.get(tenant, "secrets", "connection"))
    assert (
        alice.put(path + "/connection", json=config | {"url": "https://localhost"}).status_code
        == 409
    )
    assert alice.put(path + "/publication", json={"enabled": True}).status_code == 200
    assert alice.get(f"/stores/{tenant}/api/health").status_code == 200
    assert alice.get(f"/shop/{tenant}").status_code == 200
    assert alice.get("/shopper.js").status_code == 200
    assert alice.get("/admin.js").status_code == 200
    assert bob.put(path + "/publication", json={"enabled": False}).status_code == 403
    assert alice.post("/api/logout").status_code == 200
    assert alice.get("/api/me").status_code == 401


def test_staff_cannot_change_connections_or_execute(store):
    owner, staff = client_for(store, "owner@test.dev"), client_for(store, "staff@test.dev")
    tenant = owner.post("/api/merchants", json={"name": "Team"}).json()["id"]
    path = f"/api/merchants/{tenant}"
    assert owner.post(path + "/members", json={"email": "staff@test.dev"}).status_code == 200
    assert staff.get(path + "/connection").status_code == 200
    assert staff.put(path + "/operations/credentials", json={}).status_code == 403
    assert staff.post(path + "/operations/x/execute").status_code == 403


def test_durable_sessions_atomic_restart_and_tenant_scope(store):
    sessions = DurableSessions(store, "a")
    record = sessions.start("buyer")
    other = sessions.require(record.session_id)
    record.messages.append({"role": "user", "content": "hello"})
    record.pending_app_events.append("order paid")
    sessions.save(record)
    other.messages.append({"role": "user", "content": "stale"})
    with pytest.raises(SessionConflictError):
        sessions.save(other)
    restored = DurableSessions(store, "a").require(record.session_id)
    assert restored.messages == record.messages
    assert restored.pending_app_events == ["order paid"]
    with pytest.raises(UnknownSessionError):
        DurableSessions(store, "b").require(record.session_id)


def order_payload():
    return {
        "id": 42,
        "cart_token": "cart-one",
        "financial_status": "paid",
        "currency": "USD",
        "total_price": "12.50",
        "created_at": "2026-11-06T00:00:00Z",
        "updated_at": "2026-11-06T00:00:00Z",
        "line_items": [],
    }


def test_webhook_receipt_dedup_stale_refund_ledger(store):
    store.put("a", "cart_owners", hashlib.sha256(b"cart-one").hexdigest(), {"owner": "buyer"})
    payload = order_payload()
    assert ingest_order(store, "a", payload)
    assert ingest_order(store, "a", payload)
    assert not ingest_order(store, "b", payload)
    assert len(store.list("a", "ledger")) == 1
    assert store.get("a", "fraud_reviews", "42")["data"]["decision"] == "hold"
    refunded = payload | {
        "financial_status": "refunded",
        "updated_at": "2026-11-06T01:00:00Z",
        "refunds": [
            {"transactions": [{"id": 1, "amount": "12.50", "kind": "refund", "status": "success"}]}
        ],
    }
    ingest_order(store, "a", refunded)
    ingest_order(store, "a", payload)
    assert store.get("a", "shopify_orders", "42")["data"]["order"]["status"] == "refunded"
    assert len(store.list("a", "ledger")) == 2
    assert all(
        sum(e["amount"] for e in row["data"]["entries"]) == 0 for row in store.list("a", "ledger")
    )


def test_webhook_signature_and_domain(store):
    client = client_for(store, "owner@test.dev")
    tenant = client.post("/api/merchants", json={"name": "Store"}).json()["id"]
    client.put(
        f"/api/merchants/{tenant}/connection",
        json={
            "platform": "shopify",
            "url": "https://store.myshopify.com",
            "secret": "x" * 32,
            "webhook_secret": "signing",
        },
    )
    raw = json.dumps(order_payload()).encode()
    headers = {
        "x-shopify-topic": "orders/paid",
        "x-shopify-shop-domain": "store.myshopify.com",
        "content-type": "application/json",
        "origin": "https://not-the-browser.test",
    }
    url = f"/webhooks/shopify/{tenant}"
    assert client.post(url, content=raw, headers=headers).status_code == 401
    headers["x-shopify-hmac-sha256"] = base64.b64encode(
        hmac.new(b"signing", raw, hashlib.sha256).digest()
    ).decode()
    assert client.post(url, content=raw, headers=headers).status_code == 200
    assert client.post(url, content=raw + b" ", headers=headers).status_code == 401
    assert (
        client.post(
            url, content=raw, headers=headers | {"x-shopify-shop-domain": "other.myshopify.com"}
        ).status_code
        == 403
    )


async def test_operations_approval_fraud_gate_idempotency_and_unknown(store):
    store.put("a", "members", "owner", {"role": "owner"})
    service = Operations(store)
    row = service.stage("a", "owner", "shipment", "42", {"tracking_number": "123"})
    calls = []

    async def provider(operation, key):
        calls.append(key)
        return {"status": "completed", "id": "remote"}

    with pytest.raises(Conflict):
        await service.execute("a", "owner", row["key"], provider)
    service.approve("a", "owner", row["key"], row["version"])
    with pytest.raises(Conflict):
        await service.execute("a", "owner", row["key"], provider)
    service.review("a", "owner", "42", "release", "Verified shipment")
    assert (await service.execute("a", "owner", row["key"], provider))["data"][
        "status"
    ] == "completed"
    await service.execute("a", "owner", row["key"], provider)
    assert len(calls) == 1
    row = service.stage("a", "owner", "refund", "42", {"amount": "1.00"})
    service.approve("a", "owner", row["key"], row["version"])

    async def lost_response(operation, key):
        raise TimeoutError("remote may have completed")

    assert (await service.execute("a", "owner", row["key"], lost_response))["data"][
        "status"
    ] == "unknown"
    with pytest.raises(Conflict):
        await service.execute("a", "owner", row["key"], provider)


def test_control_cas_and_immutable_balanced_journal(store):
    store.put("a", "test", "id", {"value": 1})
    with pytest.raises(Conflict):
        store.put("a", "test", "id", {"value": 2})
    with pytest.raises(ValueError):
        store.ledger("a", "event", "USD", [{"account": "cash", "amount": 3}], description="bad")
