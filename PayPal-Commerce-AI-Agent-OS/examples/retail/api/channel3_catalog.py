# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Optional Channel3 catalog augmentation for the retail storefront.

The API key remains server-side. Channel3 records are mapped onto the repository's
``ProductDetails`` contract and cached so the normal provenance, presentation, cart, and
PayPal checkout paths can handle them without adding a second set of agent tools.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import httpx

from shopping_agent import Product, ProductDetails, SearchFilters, ShoppingSessionContext

logger = logging.getLogger(__name__)

CHANNEL3_PREFIX = "ch3:"
DEFAULT_BASE_URL = "https://api.trychannel3.com"


class Channel3Error(RuntimeError):
    """A provider failure that is safe to log without response bodies or credentials."""


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _price(offer: dict[str, Any]) -> tuple[float, str] | None:
    price = offer.get("price")
    if not isinstance(price, dict):
        return None
    amount = _number(price.get("price", price.get("amount")))
    currency = _text(price.get("currency"))
    if amount is None or amount <= 0 or currency is None:
        return None
    return amount, currency.upper()


def _best_offer(raw: dict[str, Any]) -> dict[str, Any] | None:
    offers = [offer for offer in raw.get("offers", []) if isinstance(offer, dict)]
    candidates = [
        offer
        for offer in offers
        if _price(offer) is not None
        and str(offer.get("availability", "")).lower() == "instock"
        and str(offer.get("condition") or "new").lower() == "new"
    ]
    if not candidates:
        candidates = [offer for offer in offers if _price(offer) is not None]
    return min(candidates, key=lambda offer: _price(offer)[0]) if candidates else None


def _image_url(raw: dict[str, Any]) -> str | None:
    images = [image for image in raw.get("images", []) if isinstance(image, dict)]
    images.sort(key=lambda image: not bool(image.get("is_main_image")))
    for image in images:
        if url := _text(image.get("cleaned_url")) or _text(image.get("url")):
            return url
    return None


def _brand(raw: dict[str, Any]) -> str | None:
    brand = raw.get("brand")
    if isinstance(brand, dict):
        if name := _text(brand.get("name")):
            return name
    elif name := _text(brand):
        return name
    for entry in raw.get("brands", []):
        if isinstance(entry, dict) and (name := _text(entry.get("name"))):
            return name
    return None


def _category(raw: dict[str, Any]) -> str | None:
    category = raw.get("category")
    if isinstance(category, dict):
        return _text(category.get("slug")) or _text(category.get("title"))
    return _text(category)


def _features(raw: dict[str, Any]) -> list[str]:
    values = raw.get("key_features")
    if not isinstance(values, list):
        return []
    return [text for value in values if (text := _text(value))][:8]


def _page_items(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Read Channel3's wire ``Page.data`` while tolerating older fixture envelopes.

    The official TypeScript SDK exposes the field as ``data`` and the Python SDK exposes
    it as ``items``. Accepting the legacy ``products`` envelope keeps this adapter
    backward-compatible with early API previews and makes a provider migration harmless.
    """
    for key in ("data", "items", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return (item for item in value if isinstance(item, dict))
    return ()


def _selected_options(offer: dict[str, Any]) -> dict[str, str]:
    variants = offer.get("variants")
    if not isinstance(variants, dict):
        return {}
    selected: dict[str, str] = {}
    for entry in variants.get("selected", []):
        if not isinstance(entry, dict):
            continue
        name, label = _text(entry.get("name")), _text(entry.get("label"))
        if name and label:
            selected[name.lower()] = label
    return selected


def map_product(raw: dict[str, Any]) -> ProductDetails | None:
    """Map one canonical Channel3 product to its best currently priced offer."""
    raw_id = _text(raw.get("id"))
    title = _text(raw.get("title"))
    offer = _best_offer(raw)
    if raw_id is None or title is None or offer is None:
        return None
    priced = _price(offer)
    if priced is None:
        return None
    amount, currency = priced
    availability = str(offer.get("availability", "")).lower() == "instock"
    retailer = _text(offer.get("domain"))
    attributes: dict[str, str] = {"catalog_source": "Channel3"}
    if retailer:
        attributes["retailer"] = retailer
    if condition := _text(offer.get("condition")):
        attributes["condition"] = condition
    if gender := _text(raw.get("gender")):
        attributes["gender"] = gender
    if age := _text(raw.get("age")):
        attributes["age_group"] = age
    materials = raw.get("materials")
    if isinstance(materials, list):
        joined = ", ".join(text for value in materials if (text := _text(value)))
        if joined:
            attributes["materials"] = joined[:300]
    structured = offer.get("structured_attributes")
    if isinstance(structured, dict):
        for key, value in list(structured.items())[:12]:
            if isinstance(value, (str, int, float, bool)):
                attributes[str(key)[:60]] = str(value)[:200]
    features = _features(raw)
    return ProductDetails(
        product_id=f"{CHANNEL3_PREFIX}{raw_id}",
        title=title,
        brand=_brand(raw),
        price=amount,
        currency=currency,
        image_url=_image_url(raw),
        category=_category(raw),
        labels=["Channel3"],
        attributes=attributes,
        in_stock=availability,
        short_description=_text(raw.get("description")),
        option_values=_selected_options(offer),
        long_description=_text(raw.get("description")),
        specs={"Retailer": retailer} if retailer else {},
        review_highlights=features,
    )


class Channel3Catalog:
    """Small async API adapter with no effect when ``CHANNEL3_API_KEY`` is unset."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 8.0,
        max_results: int = 6,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_results = max(1, min(max_results, 20))
        self.transport = transport
        self.products: dict[str, ProductDetails] = {}

    @classmethod
    def from_env(cls) -> Channel3Catalog | None:
        api_key = os.environ.get("CHANNEL3_API_KEY", "").strip()
        if not api_key:
            return None
        try:
            timeout = float(os.environ.get("CHANNEL3_TIMEOUT_SECONDS", "8"))
            limit = int(os.environ.get("CHANNEL3_MAX_RESULTS", "6"))
        except ValueError:
            logger.warning(
                "Channel3 disabled: CHANNEL3_TIMEOUT_SECONDS and CHANNEL3_MAX_RESULTS "
                "must be numeric"
            )
            return None
        return cls(
            api_key,
            base_url=os.environ.get("CHANNEL3_BASE_URL", DEFAULT_BASE_URL),
            timeout_s=max(1.0, min(timeout, 30.0)),
            max_results=limit,
        )

    @staticmethod
    def _partner_user(session: ShoppingSessionContext) -> str:
        digest = hashlib.sha256(session.user_id.encode("utf-8")).hexdigest()[:24]
        return f"commerce-{digest}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        session: ShoppingSessionContext,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "x-user-id": self._partner_user(session),
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            try:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=headers, json=json
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                suffix = f" ({status})" if status else ""
                raise Channel3Error(f"Channel3 request failed{suffix}") from error
        if not isinstance(payload, dict):
            raise Channel3Error("Channel3 returned an invalid response")
        return payload

    async def search(
        self,
        session: ShoppingSessionContext,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[Product]:
        requested = max(1, min(limit, self.max_results))
        attributes = filters.attributes if filters else {}
        context = [query]
        if filters and filters.category:
            # Store categories are deployment-owned labels, not guaranteed Channel3
            # taxonomy slugs. Keeping the label in the semantic query avoids silently
            # dropping results through a guessed category_ids filter.
            context.append(filters.category)
        context.extend(f"{key} {value}" for key, value in attributes.items())
        body: dict[str, Any] = {
            "query": " ".join(context)[:500],
            "limit": requested,
            "filters": {"conditions": ["new"], "availability": ["InStock"]},
        }
        price_filter: dict[str, float] = {}
        if filters and filters.min_price is not None:
            price_filter["min_price"] = filters.min_price
        if filters and filters.max_price is not None:
            price_filter["max_price"] = filters.max_price
        if price_filter:
            body["filters"]["price"] = price_filter
        payload = await self._request("POST", "/v1/search", session=session, json=body)
        mapped = [
            product for raw in _page_items(payload) if (product := map_product(raw)) is not None
        ]
        if filters and filters.sort != "relevance" and filters.sort.startswith("price_"):
            mapped.sort(
                key=lambda product: product.price,
                reverse=filters.sort == "price_desc",
            )
        for product in mapped:
            self.products[product.product_id] = product
        return [
            Product.model_validate(
                product.model_dump(
                    exclude={"long_description", "specs", "review_highlights", "variants"}
                )
            )
            for product in mapped[:requested]
        ]

    async def details(
        self, session: ShoppingSessionContext, product_id: str
    ) -> ProductDetails | None:
        if not product_id.startswith(CHANNEL3_PREFIX):
            return None
        raw_id = product_id.removeprefix(CHANNEL3_PREFIX)
        try:
            payload = await self._request(
                "GET", f"/v1/products/{quote(raw_id, safe='')}", session=session
            )
        except Channel3Error:
            return self.products.get(product_id)
        product = map_product(payload)
        if product is None:
            return self.products.get(product_id)
        self.products[product.product_id] = product
        return product

    def cached(self, product_id: str) -> ProductDetails | None:
        return self.products.get(product_id)

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "cached_products": len(self.products)}


def log_channel3_fallback(error: Exception) -> None:
    logger.warning("Channel3 catalog unavailable; using the built-in catalog: %s", error)
