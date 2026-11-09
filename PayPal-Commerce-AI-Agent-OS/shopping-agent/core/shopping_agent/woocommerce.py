"""WooCommerce storefront adapter for the bundled Agent Commerce Bridge plugin.

WooCommerce owns the cart, checkout, final quote, inventory and order lifecycle.
No PayPal credentials are required here: the store's payment gateway handles payment.
Each backend instance is bound to one merchant by the authenticated host.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlsplit

import httpx

from .backend import NotOffered, StorefrontBackend
from .types import (
    Cart,
    CheckoutHandoff,
    Order,
    Product,
    ProductDetails,
    UserPreferences,
)


class WooCommerceBackend(StorefrontBackend):
    platform_checkout = True

    def __init__(
        self,
        url: str,
        secret: str,
        merchant_id: str,
        *,
        client=None,
        authenticated_customers: bool = False,
    ):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("WooCommerce URL must be an HTTPS store origin/path")
        if len(secret) < 32:
            raise ValueError("WooCommerce bridge secret must contain at least 32 characters")
        self.url, self.secret, self.merchant_id = url.rstrip("/"), secret, merchant_id
        self.store_name = merchant_id
        self.authenticated_customers = authenticated_customers
        self.client = client or httpx.AsyncClient(timeout=25, follow_redirects=False)
        self._owns_client = client is None

    async def aclose(self):
        if self._owns_client:
            await self.client.aclose()

    def _owner(self, session):
        # Demo profile ids are not authentication. Default to an unguessable session;
        # production hosts may use their verified stable principal explicitly.
        principal = session.user_id if self.authenticated_customers else session.session_id
        return hmac.new(
            self.secret.encode(), f"{self.merchant_id}:{principal}".encode(), hashlib.sha256
        ).hexdigest()

    async def _call(self, method, path, body=None):
        raw = json.dumps(body or {}, separators=(",", ":")).encode()
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        signed = b"\n".join(
            [method.encode(), path.encode(), timestamp.encode(), nonce.encode(), raw]
        )
        signature = hmac.new(self.secret.encode(), signed, hashlib.sha256).hexdigest()
        response = await self.client.request(
            method,
            f"{self.url}/wp-json/agent-commerce/v1{path}",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Agent-Time": timestamp,
                "X-Agent-Nonce": nonce,
                "X-Agent-Signature": signature,
            },
        )
        if response.is_error:
            # Never relay upstream HTML, request data, or tokens to the model.
            raise NotOffered("The store could not complete this request. Please try again.")
        return response.json()

    async def search_products(self, session, query, filters=None, limit=8):
        data = await self._call(
            "POST",
            "/catalog",
            {
                "query": query,
                "limit": min(limit, 30),
                "filters": filters.model_dump(exclude_none=True) if filters else {},
            },
        )
        return [Product.model_validate(p) for p in data["products"]]

    async def get_product_details(self, session, product_id):
        if not product_id.isdigit():
            return None
        data = await self._call("POST", "/product", {"id": int(product_id)})
        return ProductDetails.model_validate(data["product"]) if data.get("product") else None

    async def _cart(self, session, action="read", product_id=None, quantity=None):
        data = await self._call(
            "POST",
            "/cart",
            {
                "owner": self._owner(session),
                "action": action,
                "product_id": product_id,
                "quantity": quantity,
            },
        )
        return Cart.model_validate(data["cart"])

    async def get_cart(self, session):
        return await self._cart(session)

    async def add_to_cart(self, session, product_id, quantity):
        return await self._cart(session, "add", product_id, quantity)

    async def update_cart_item(self, session, product_id, quantity):
        return await self._cart(session, "update", product_id, quantity)

    async def remove_from_cart(self, session, product_id):
        return await self._cart(session, "remove", product_id)

    async def checkout_handoff(self, session, cart):
        result = await self._call("POST", "/handoff", {"owner": self._owner(session)})
        url = result["url"]
        if urlsplit(url).scheme != "https" or urlsplit(url).netloc != urlsplit(self.url).netloc:
            raise NotOffered("The store returned an invalid checkout address")
        return [CheckoutHandoff(url=url, label="Continue to secure checkout")]

    async def get_preferences(self, session):
        return UserPreferences(user_id=session.user_id)

    async def get_orders(self, session, limit=5):
        result = await self._call(
            "POST", "/orders", {"owner": self._owner(session), "limit": limit}
        )
        return [Order.model_validate(o) for o in result["orders"]]

    async def get_order(self, session, order_id):
        result = await self._call(
            "POST", "/orders", {"owner": self._owner(session), "order_id": order_id}
        )
        return next(
            (Order.model_validate(o) for o in result["orders"] if o["order_id"] == order_id), None
        )

    async def search_policies(self, session, query):
        from .types import Policy

        result = await self._call("POST", "/policies", {"query": query})
        return [Policy.model_validate(p) for p in result["policies"]]

    async def get_fulfillment_options(self, session, product_ids):
        raise NotOffered(
            "Delivery choices and their final cost are calculated by the store at checkout"
        )

    async def sync_events(self, record, session):
        # Polling authoritative order state also recovers missed webhooks or restarts.
        for order in await self.get_orders(session, 20):
            key = f"woocommerce:{self.merchant_id}:{order.order_id}:{order.status}"
            if key not in record.payment_events:
                record.pending_app_events.append(
                    f"WooCommerce confirmed order {order.order_id}: {order.status}. "
                    f"Total {order.total:.2f} {order.currency}. Do not charge again."
                )
                record.payment_events.append(key)
