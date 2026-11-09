from types import SimpleNamespace

import httpx

from commerce_common.memory import InMemoryMemoryStore
from commerce_common.streaming import AgentEvent
from demo_common.memory import MemorySeeder
from demo_common.storefront import build_storefront_host
from shopping_agent.woocommerce import WooCommerceBackend


async def test_native_paid_order_is_visible_and_reaches_next_chat(tmp_path, monkeypatch):
    # Native checkout must not also attach the direct PayPal payment provider.
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "must-not-be-used")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "must-not-be-used")
    captured_messages = []
    available = {"value": True}

    class Agent:
        memory = SimpleNamespace(store=InMemoryMemoryStore())
        skills = SimpleNamespace(names=[])
        config = SimpleNamespace(model="test")

        async def stream_turn(self, messages, session, state):
            captured_messages.extend(messages)
            yield AgentEvent(type="text_delta", data={"text": "Your order is confirmed."})

        async def update_memory(self, messages, session):
            pass

    def woo(request):
        if not available["value"]:
            return httpx.Response(503)
        if request.url.path.endswith("/orders"):
            return httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "order_id": "42",
                            "status": "processing",
                            "placed_at": "2026-11-05T10:00:00Z",
                            "items": [],
                            "total": 24,
                            "currency": "USD",
                        }
                    ]
                },
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(woo)) as remote:
        backend = WooCommerceBackend("https://store.test", "s" * 32, "merchant", client=remote)
        host = build_storefront_host(
            title="Store",
            example_root=tmp_path,
            backend=backend,
            agent=Agent(),
            memory_seeder=MemorySeeder(tmp_path / "unused.json", enabled=False),
        )
        assert host.payment_runtime is None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=host.app), base_url="http://localhost"
        ) as client:
            session = (await client.post("/api/session", json={"user_id": "demo-user"})).json()
            assert session["user_id"] != "demo-user"
            headers = {"X-Session-Id": session["session_id"]}
            assert (await client.get("/api/health")).json()["payments"] == "platform"
            orders = await client.get("/api/orders", headers=headers)
            assert orders.json()["orders"][0]["order_id"] == "42"
            response = await client.post(
                "/api/chat", headers=headers, json={"message": "Did it work?"}
            )
            assert response.status_code == 200
            assert "WooCommerce confirmed order 42" in str(captured_messages)
            record = host.sessions.require(session["session_id"])
            assert record.payment_events == ["woocommerce:merchant:42:processing"]
            available["value"] = False
            response = await client.post(
                "/api/chat", headers=headers, json={"message": "Any update?"}
            )
            assert response.status_code == 200
            assert "Payment status is unknown" in str(captured_messages)
