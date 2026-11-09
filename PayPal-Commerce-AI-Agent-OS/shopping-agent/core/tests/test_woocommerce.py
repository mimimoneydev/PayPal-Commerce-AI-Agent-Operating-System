import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest

from shopping_agent import ShoppingSessionContext
from shopping_agent.backend import NotOffered
from shopping_agent.woocommerce import WooCommerceBackend


async def test_signed_cart_checkout_and_confirmed_order_event():
    calls = []
    secret = "test-secret-" * 4
    order = {
        "order_id": "42",
        "status": "processing",
        "placed_at": "2026-11-05T10:00:00Z",
        "items": [{"product_id": "8", "title": "Tent", "price": 20, "quantity": 1}],
        "total": 23.5,
        "currency": "USD",
    }

    def handler(request):
        path = request.url.path.removeprefix("/wp-json/agent-commerce/v1")
        canonical = b"\n".join(
            [
                request.method.encode(),
                path.encode(),
                request.headers["X-Agent-Time"].encode(),
                request.headers["X-Agent-Nonce"].encode(),
                request.content,
            ]
        )
        assert hmac.compare_digest(
            request.headers["X-Agent-Signature"],
            hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(),
        )
        body = json.loads(request.content)
        assert "buyer" not in request.content.decode()
        calls.append((path, body))
        if path == "/cart":
            return httpx.Response(200, json={"cart": {"items": order["items"], "currency": "USD"}})
        if path == "/handoff":
            return httpx.Response(200, json={"url": "https://store.test/?ac_checkout=opaque"})
        if path == "/orders":
            return httpx.Response(200, json={"orders": [order]})
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        backend = WooCommerceBackend("https://store.test", secret, "merchant", client=http)
        session = ShoppingSessionContext(session_id="random-session", user_id="buyer")
        cart = await backend.add_to_cart(session, "8", 1)
        handoff = await backend.checkout_handoff(session, cart)
        assert handoff[0].url.startswith("https://store.test/")
        record = SimpleNamespace(payment_events=[], pending_app_events=[])
        await backend.sync_events(record, session)
        await backend.sync_events(record, session)
        assert len(record.pending_app_events) == 1
        assert "42" in record.pending_app_events[0] and "23.50" in record.pending_app_events[0]
        other = ShoppingSessionContext(session_id="other-session", user_id="buyer")
        assert backend._owner(other) != backend._owner(session)
        assert calls[0][1]["owner"] == calls[1][1]["owner"]


async def test_handoff_cannot_redirect_to_another_store():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"url": "https://evil.test/checkout"})
        )
    ) as http:
        backend = WooCommerceBackend("https://store.test", "s" * 32, "merchant", client=http)
        with pytest.raises(NotOffered):
            await backend.checkout_handoff(
                ShoppingSessionContext(session_id="s", user_id="u"), None
            )


def test_requires_https_and_strong_bridge_secret():
    with pytest.raises(ValueError):
        WooCommerceBackend("http://store.test", "s" * 32, "m")
    with pytest.raises(ValueError):
        WooCommerceBackend("https://store.test", "short", "m")
