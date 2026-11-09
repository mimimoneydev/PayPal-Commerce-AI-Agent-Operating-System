"""Shopify Storefront carts with native checkout and tenant-scoped paid receipts.

Cart IDs contain bearer secrets: persist them encrypted, never return them to the
model. Mutation leases fail closed after an ambiguous response; reads reconcile
the actual remote cart before the shopper can submit another mutation.
"""

from __future__ import annotations

import hashlib
import re
import time
from urllib.parse import urlsplit

import httpx

from .backend import NotOffered, StorefrontBackend
from .types import (
    Cart,
    CartItem,
    CheckoutHandoff,
    Order,
    Policy,
    Product,
    ProductDetails,
    UserPreferences,
)

PRODUCT = """id title vendor description productType availableForSale
featuredImage { url } options { name values }
priceRange { minVariantPrice { amount currencyCode } }
variants(first:100) { nodes { id title availableForSale price { amount currencyCode }
image { url } selectedOptions { name value } } pageInfo { hasNextPage } }"""
CART = """id checkoutUrl cost { subtotalAmount { amount currencyCode } }
lines(first:100) { nodes { id quantity merchandise { ... on ProductVariant {
id title price { amount currencyCode } image { url } selectedOptions { name value }
product { id title } } } } pageInfo { hasNextPage } }"""


class ShopifyBackend(StorefrontBackend):
    platform_checkout = True

    def __init__(self, url, token, merchant_id, store, *, client=None, api_version="2026-04"):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", parsed.netloc)
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use the store's HTTPS myshopify.com origin")
        if not re.fullmatch(r"20\d{2}-(01|04|07|10)", api_version):
            raise ValueError("Use a stable Shopify API version")
        self.url, self.token, self.merchant_id = url.rstrip("/"), token, merchant_id
        self.store, self.store_name = store, merchant_id
        self.endpoint = f"{self.url}/api/{api_version}/graphql.json"
        self.client = client or httpx.AsyncClient(timeout=25, follow_redirects=False)
        self._owns_client = client is None

    async def aclose(self):
        if self._owns_client:
            await self.client.aclose()

    async def graphql(self, query, variables):
        response = await self.client.post(
            self.endpoint,
            json={"query": query, "variables": variables},
            headers={"X-Shopify-Storefront-Access-Token": self.token},
        )
        if response.is_error:
            raise NotOffered("The store is temporarily unavailable")
        payload = response.json()
        if payload.get("errors"):
            raise NotOffered("The store could not complete the request")
        return payload["data"]

    def _owner(self, session):
        return hashlib.sha256(f"{self.merchant_id}:{session.session_id}".encode()).hexdigest()

    def _product(self, node):
        price = node["priceRange"]["minVariantPrice"]
        variants = node["variants"]["nodes"]
        options = {o["name"]: o["values"] for o in node["options"]}
        # Even a single default variant has a distinct purchasable Shopify GID.
        return ProductDetails(
            product_id=node["id"],
            title=node["title"],
            brand=node["vendor"],
            price=float(price["amount"]),
            currency=price["currencyCode"],
            image_url=(node.get("featuredImage") or {}).get("url"),
            category=node["productType"],
            short_description=node["description"][:500],
            long_description=node["description"],
            in_stock=node["availableForSale"],
            options=options,
            variants=[
                Product(
                    product_id=v["id"],
                    title=node["title"] + " — " + v["title"],
                    price=float(v["price"]["amount"]),
                    currency=v["price"]["currencyCode"],
                    in_stock=v["availableForSale"],
                    image_url=(v.get("image") or {}).get("url"),
                    variant_of=node["id"],
                    option_values={o["name"]: o["value"] for o in v["selectedOptions"]},
                )
                for v in variants
            ],
        )

    async def search_products(self, session, query, filters=None, limit=8):
        if filters and (filters.attributes or filters.min_rating or filters.sort == "rating"):
            raise NotOffered("This store does not expose rating or attribute filtering")

        # Quote input as a Shopify search literal, not executable search syntax.
        def quoted(value):
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

        terms = [quoted(query)] if query else []
        if filters:
            if filters.category:
                terms.append("product_type:" + quoted(filters.category))
            if filters.min_price is not None:
                terms.append(f"variants.price:>={float(filters.min_price)}")
            if filters.max_price is not None:
                terms.append(f"variants.price:<={float(filters.max_price)}")
        result = await self.graphql(
            "query($q:String!,$n:Int!,$sort:ProductSortKeys!,$reverse:Boolean!) { products(first:$n,query:$q,sortKey:$sort,reverse:$reverse) { nodes { "
            + PRODUCT
            + " } } }",
            {
                "q": " AND ".join(terms),
                "n": max(1, min(limit, 30)),
                "sort": "PRICE" if filters and filters.sort.startswith("price_") else "RELEVANCE",
                "reverse": bool(filters and filters.sort == "price_desc"),
            },
        )
        return [self._product(node) for node in result["products"]["nodes"]]

    async def get_product_details(self, session, product_id):
        if not re.fullmatch(r"gid://shopify/(Product|ProductVariant)/\d+", product_id):
            return None
        data = await self.graphql(
            "query($id:ID!) { node(id:$id) { ... on Product { "
            + PRODUCT
            + " } ... on ProductVariant { product { "
            + PRODUCT
            + " } } } }",
            {"id": product_id},
        )
        node = data.get("node")
        if not node:
            return None
        product = self._product(node.get("product", node))
        if "/ProductVariant/" in product_id:
            variant = next((v for v in product.variants if v.product_id == product_id), None)
            return ProductDetails(**variant.model_dump()) if variant else None
        return product

    def _cart_model(self, data):
        if not data:
            return Cart()
        if data["lines"]["pageInfo"]["hasNextPage"]:
            raise NotOffered(
                "This cart exceeds the assistant's 100-line limit; use the store checkout"
            )
        return Cart(
            currency=data["cost"]["subtotalAmount"]["currencyCode"],
            items=[
                CartItem(
                    product_id=line["merchandise"]["id"],
                    title=line["merchandise"]["product"]["title"],
                    quantity=line["quantity"],
                    price=float(line["merchandise"]["price"]["amount"]),
                    variant_of=line["merchandise"]["product"]["id"],
                    image_url=(line["merchandise"].get("image") or {}).get("url"),
                    option_values={
                        o["name"]: o["value"] for o in line["merchandise"]["selectedOptions"]
                    },
                )
                for line in data["lines"]["nodes"]
            ],
        )

    async def _read_cart(self, owner):
        ref = self.store.secret(self.merchant_id, "cart-" + owner)
        if not ref:
            return None
        result = await self.graphql(
            "query($id:ID!) { cart(id:$id) { " + CART + " } }", {"id": ref["id"]}
        )
        return result.get("cart")

    async def get_cart(self, session):
        return self._cart_model(await self._read_cart(self._owner(session)))

    async def _mutate(self, session, action, product_id, quantity):
        from commerce_common.control_store import Conflict

        if not re.fullmatch(r"gid://shopify/ProductVariant/\d+", product_id):
            raise NotOffered("Choose a specific product variant")
        if quantity is not None and (type(quantity) is not int or not 1 <= quantity <= 99):
            raise NotOffered("Quantity must be between 1 and 99")
        owner = self._owner(session)
        lock = self.store.get(self.merchant_id, "cart_leases", owner)
        if lock and lock["data"]["until"] > time.time():
            raise NotOffered("A cart update is in progress; refresh the cart before trying again")
        try:
            lease = self.store.put(
                self.merchant_id,
                "cart_leases",
                owner,
                {"until": time.time() + 90},
                version=lock["version"] if lock else 0,
            )
        except Conflict as error:
            raise NotOffered("Another cart update is in progress") from error
        try:
            cart = await self._read_cart(owner)
            if not cart:
                if action != "add":
                    return Cart()
                result = await self.graphql(
                    "mutation($input:CartInput!) { cartCreate(input:$input) { cart { "
                    + CART
                    + " } userErrors { message } } }",
                    {"input": {"lines": [{"merchandiseId": product_id, "quantity": quantity}]}},
                )
                payload = result["cartCreate"]
            else:
                self._cart_model(cart)  # Refuse partial carts before changing anything.
                line = next(
                    (
                        line
                        for line in cart["lines"]["nodes"]
                        if line["merchandise"]["id"] == product_id
                    ),
                    None,
                )
                if not line and action != "add":
                    return self._cart_model(cart)
                if action == "remove":
                    name, typ, field, lines = "cartLinesRemove", "[ID!]!", "lineIds", [line["id"]]
                elif line:
                    total = quantity + line["quantity"] if action == "add" else quantity
                    if total > 99:
                        raise NotOffered("Maximum quantity is 99")
                    name, typ, field, lines = (
                        "cartLinesUpdate",
                        "[CartLineUpdateInput!]!",
                        "lines",
                        [{"id": line["id"], "quantity": total}],
                    )
                else:
                    name, typ, field, lines = (
                        "cartLinesAdd",
                        "[CartLineInput!]!",
                        "lines",
                        [{"merchandiseId": product_id, "quantity": quantity}],
                    )
                result = await self.graphql(
                    f"mutation($id:ID!,$lines:{typ}) {{ {name}(cartId:$id,{field}:$lines) {{ cart {{ "
                    + CART
                    + " } userErrors { message } } }",
                    {"id": cart["id"], "lines": lines},
                )
                payload = result[name]
            if payload.get("userErrors") or not payload.get("cart"):
                raise NotOffered("The store rejected this cart change; refresh availability")
            cart = payload["cart"]
            self.store.save_secret(self.merchant_id, "cart-" + owner, {"id": cart["id"]})
            token = cart["id"].split("/Cart/", 1)[1].split("?", 1)[0]
            key = hashlib.sha256(token.encode()).hexdigest()
            if not self.store.get(self.merchant_id, "cart_owners", key):
                self.store.put(self.merchant_id, "cart_owners", key, {"owner": owner})
            return self._cart_model(cart)
        finally:
            # Remote mutation timeouts are not automatically retried. Every subsequent
            # action rereads the remote cart and sets an absolute quantity.
            self.store.put(
                self.merchant_id, "cart_leases", owner, {"until": 0}, version=lease["version"]
            )

    async def add_to_cart(self, session, product_id, quantity):
        return await self._mutate(session, "add", product_id, quantity)

    async def update_cart_item(self, session, product_id, quantity):
        return await self._mutate(session, "update", product_id, quantity)

    async def remove_from_cart(self, session, product_id):
        return await self._mutate(session, "remove", product_id, None)

    async def checkout_handoff(self, session, cart):
        data = await self._read_cart(self._owner(session))
        if not data or not data["lines"]["nodes"]:
            raise NotOffered("Add items before checkout")
        parsed = urlsplit(data["checkoutUrl"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != urlsplit(self.url).hostname
            or parsed.username
        ):
            raise NotOffered(
                "Unexpected checkout domain; configure the store's native checkout domain"
            )
        return [CheckoutHandoff(url=data["checkoutUrl"], label="Continue to Shopify checkout")]

    async def get_preferences(self, session):
        return UserPreferences(user_id=session.user_id)

    async def get_orders(self, session, limit=5):
        owner = self._owner(session)
        orders = [
            Order.model_validate(row["data"]["order"])
            for row in self.store.list(self.merchant_id, "shopify_orders")
            if row["data"]["owner"] == owner
        ]
        return sorted(orders, key=lambda order: order.placed_at, reverse=True)[:limit]

    async def get_order(self, session, order_id):
        row = self.store.get(self.merchant_id, "shopify_orders", order_id)
        if row and row["data"]["owner"] == self._owner(session):
            return Order.model_validate(row["data"]["order"])
        return None

    async def search_policies(self, session, query):
        result = await self.graphql(
            "{ shop { privacyPolicy { id title body } refundPolicy { id title body } shippingPolicy { id title body } termsOfService { id title body } } }",
            {},
        )
        return [
            Policy(policy_id=p["id"], title=p["title"], content=p["body"])
            for p in result["shop"].values()
            if p
        ]

    async def get_fulfillment_options(self, session, product_ids):
        raise NotOffered("Shipping, taxes and discounts are calculated at Shopify checkout")

    async def sync_events(self, record, session):
        for order in await self.get_orders(session, 20):
            key = f"shopify:{self.merchant_id}:{order.order_id}:{order.status}"
            if key not in record.payment_events:
                record.pending_app_events.append(
                    f"Shopify confirmed order {order.order_id}: {order.status}. Total {order.total:.2f} {order.currency}. Do not charge again."
                )
                record.payment_events.append(key)
