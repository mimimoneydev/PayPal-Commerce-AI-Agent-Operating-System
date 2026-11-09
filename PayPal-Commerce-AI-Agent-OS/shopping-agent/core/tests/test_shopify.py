import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet

from commerce_common.control_store import ControlStore
from shopping_agent.backend import NotOffered
from shopping_agent.shopify import ShopifyBackend


@pytest.fixture
def store(tmp_path):
    return ControlStore("sqlite:///" + str(tmp_path / "shop.db"), Fernet.generate_key().decode())


def cart(quantity=1):
    return {
        "id": "gid://shopify/Cart/cart-token?key=secret",
        "checkoutUrl": "https://store.myshopify.com/checkouts/1",
        "cost": {"subtotalAmount": {"amount": "10", "currencyCode": "USD"}},
        "lines": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {
                    "id": "line-1",
                    "quantity": quantity,
                    "merchandise": {
                        "id": "gid://shopify/ProductVariant/1",
                        "price": {"amount": "10", "currencyCode": "USD"},
                        "product": {"id": "gid://shopify/Product/1", "title": "Item"},
                        "selectedOptions": [],
                        "image": None,
                    },
                }
            ],
        },
    }


async def test_native_cart_checkout_persistence_and_secret_isolation(store):
    calls = []
    state = cart()

    def remote(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["x-shopify-storefront-access-token"] == "token"
        query = body["query"]
        if "cartCreate" in query:
            return httpx.Response(
                200, json={"data": {"cartCreate": {"cart": state, "userErrors": []}}}
            )
        if "cartLinesUpdate" in query:
            state["lines"]["nodes"][0]["quantity"] = body["variables"]["lines"][0]["quantity"]
            return httpx.Response(
                200, json={"data": {"cartLinesUpdate": {"cart": state, "userErrors": []}}}
            )
        return httpx.Response(200, json={"data": {"cart": state}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        backend = ShopifyBackend("https://store.myshopify.com", "token", "a", store, client=client)
        session = SimpleNamespace(session_id="session", user_id="buyer")
        assert not (await backend.get_cart(session)).items
        result = await backend.add_to_cart(session, "gid://shopify/ProductVariant/1", 1)
        assert result.items[0].quantity == 1
        assert "secret" not in result.model_dump_json()
        assert (await backend.add_to_cart(session, "gid://shopify/ProductVariant/1", 2)).items[
            0
        ].quantity == 3
        assert (await backend.checkout_handoff(session, result))[0].url.endswith("/checkouts/1")
        restarted = ShopifyBackend(
            "https://store.myshopify.com", "token", "a", store, client=client
        )
        assert (await restarted.get_cart(session)).items[0].quantity == 3
        other = ShopifyBackend("https://store.myshopify.com", "token", "b", store, client=client)
        assert not (await other.get_cart(session)).items
        state["checkoutUrl"] = "https://attacker.test/checkout"
        with pytest.raises(NotOffered):
            await backend.checkout_handoff(session, result)
        with pytest.raises(NotOffered):
            await backend.add_to_cart(session, "gid://shopify/Product/1", 1)


async def test_cart_remote_errors_are_sanitized_and_mutations_not_retried(store):
    calls = []

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json={"errors": [{"message": "secret-token private details"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        backend = ShopifyBackend("https://store.myshopify.com", "token", "a", store, client=client)
        with pytest.raises(NotOffered, match="could not complete"):
            await backend.add_to_cart(
                SimpleNamespace(session_id="s"), "gid://shopify/ProductVariant/1", 1
            )
    assert len(calls) == 1


def test_reject_untrusted_shopify_hosts(store):
    for url in (
        "http://store.myshopify.com",
        "https://store.myshopify.com.attacker.test",
        "https://user:pass@store.myshopify.com",
    ):
        with pytest.raises(ValueError):
            ShopifyBackend(url, "token", "a", store)
