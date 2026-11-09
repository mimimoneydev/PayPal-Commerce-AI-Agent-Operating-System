# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Host-owned payment orchestration for commerce deployments.

The agent may create a checkout handoff, but it never receives a payment credential,
creates a PayPal order, or captures money.  Those operations live here, behind an opaque
checkout token that is scoped to one immutable cart snapshot.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

MONEY_PLACES = Decimal("0.01")


def money(value: Decimal | float | int | str) -> Decimal:
    """A currency amount rounded once with ordinary half-up commerce semantics."""
    return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


class PaymentError(RuntimeError):
    """A safe payment failure. Its message contains no credentials or payer data."""


class PaymentNotFound(PaymentError):
    pass


class PaymentConflict(PaymentError):
    pass


class PaymentProviderError(PaymentError):
    def __init__(self, operation: str, status_code: int, issue: str, debug_id: str | None = None):
        self.operation = operation
        self.status_code = status_code
        self.issue = issue
        self.debug_id = debug_id
        suffix = f" (debug id {debug_id})" if debug_id else ""
        super().__init__(f"PayPal {operation} failed: {issue}{suffix}")


class SpendCapExceeded(PaymentError):
    """The quoted total is above the shopper's cap or the host's hard ceiling.

    Raised before any payment row or PayPal order exists, so an over-cap request can
    never leave a chargeable draft behind. The model's requested cap is always clamped
    to the server-side ceiling; the agent cannot raise its own limit.
    """

    def __init__(self, amount: Decimal, cap: Decimal, currency: str):
        self.amount = amount
        self.cap = cap
        self.currency = currency
        super().__init__(
            f"Cart total {amount:.2f} {currency} exceeds the authorized spend cap of "
            f"{cap:.2f} {currency}. No PayPal order was created."
        )


class CheckoutStatus(StrEnum):
    DRAFT = "draft"
    CREATED = "created"
    APPROVED = "approved"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PaymentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=127)
    name: str = Field(min_length=1, max_length=127)
    unit_amount: Decimal = Field(gt=0)
    quantity: int = Field(ge=1, le=10_000)

    @field_validator("unit_amount")
    @classmethod
    def normalize_amount(cls, value: Decimal) -> Decimal:
        return money(value)

    @property
    def total(self) -> Decimal:
        return money(self.unit_amount * self.quantity)


class CheckoutDraft(BaseModel):
    """An immutable quote plus the PayPal state attached to it.

    ``token_hash`` is stored instead of the bearer token that appears in the checkout URL.
    ``version`` provides optimistic concurrency in stores shared by several workers.
    """

    model_config = ConfigDict(extra="forbid")

    checkout_id: str
    token_hash: str
    session_id: str
    user_id: str
    merchant_id: str = "default"
    cart_hash: str
    items: tuple[PaymentItem, ...]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(gt=0)
    # Bounded auto-buy: the effective cap (shopper's cap clamped to the host ceiling)
    # recorded on the immutable quote, so every later step can be audited against it.
    spend_cap: Decimal | None = None
    status: CheckoutStatus = CheckoutStatus.DRAFT
    paypal_order_id: str | None = None
    approval_url: str | None = None
    capture_id: str | None = None
    provider_status: str | None = None
    # The completed checkout row is also the transactional order-finalization outbox.
    commerce_order_id: str | None = None
    finalization_attempts: int = 0
    retry_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30))
    version: int = Field(default=0, ge=0)

    @field_validator("amount")
    @classmethod
    def normalize_total(cls, value: Decimal) -> Decimal:
        return money(value)

    @field_validator("spend_cap")
    @classmethod
    def normalize_cap(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else money(value)


class AgentOrderReceipt(BaseModel):
    """The sanitized record of a host-created, cap-bounded PayPal order.

    The agent sees :meth:`model_view`; the two URLs are host-only. ``checkout_url``
    carries the opaque bearer token and must never enter model context, and neither
    URL may be a model-supplied value. No access token, payer identity, or funding
    source is ever stored here.
    """

    model_config = ConfigDict(extra="forbid")

    checkout_id: str
    paypal_order_id: str
    status: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal
    spend_cap: Decimal
    cart_hash: str
    items: tuple[PaymentItem, ...]
    approval_url: str | None = None
    checkout_url: str

    @field_validator("amount", "spend_cap")
    @classmethod
    def normalize_money(cls, value: Decimal) -> Decimal:
        return money(value)

    def model_view(self) -> dict[str, Any]:
        """What the model may read: identifiers and money, never a bearer URL."""
        return self.model_dump(mode="json", exclude={"approval_url", "checkout_url"})


class PayPalOrder(BaseModel):
    order_id: str
    status: str
    approval_url: str | None = None
    capture_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None


class PayPalConfig(BaseModel):
    """Server credentials and public checkout settings, normally loaded from env."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    webhook_id: str | None = None
    sandbox: bool = True
    timeout_s: float = Field(default=20.0, gt=0, le=120)
    brand_name: str = Field(default="Store checkout", min_length=1, max_length=127)
    seller_merchant_id: str | None = None
    partner_attribution_id: str | None = None

    @property
    def base_url(self) -> str:
        return "https://api-m.sandbox.paypal.com" if self.sandbox else "https://api-m.paypal.com"

    @property
    def javascript_url(self) -> str:
        host = "www.sandbox.paypal.com" if self.sandbox else "www.paypal.com"
        return f"https://{host}/sdk/js"

    @classmethod
    def from_env(cls) -> PayPalConfig | None:
        client_id = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
        secret = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
        if not client_id and not secret:
            return None
        if not client_id or not secret:
            raise ValueError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set together")
        environment = os.environ.get("PAYPAL_ENVIRONMENT", "sandbox").strip().lower()
        if environment not in {"sandbox", "live"}:
            raise ValueError("PAYPAL_ENVIRONMENT must be 'sandbox' or 'live'")
        return cls(
            client_id=client_id,
            client_secret=secret,
            webhook_id=os.environ.get("PAYPAL_WEBHOOK_ID") or None,
            sandbox=environment == "sandbox",
            brand_name=os.environ.get("PAYPAL_BRAND_NAME", "Store checkout"),
            partner_attribution_id=os.environ.get("PAYPAL_PARTNER_ATTRIBUTION_ID") or None,
        )


class PaymentStore(Protocol):
    async def create(self, draft: CheckoutDraft) -> None: ...

    async def get_by_token_hash(self, token_hash: str) -> CheckoutDraft | None: ...

    async def get_by_order_id(self, order_id: str) -> CheckoutDraft | None: ...

    async def update(self, draft: CheckoutDraft, expected_version: int) -> CheckoutDraft: ...

    async def record_webhook(self, event_id: str, event_type: str) -> bool: ...

    async def forget_webhook(self, event_id: str) -> None: ...

    async def completed(
        self, merchant_id: str, user_id: str | None = None
    ) -> list[CheckoutDraft]: ...

    async def commit_webhook(
        self, event_id: str, event_type: str, draft: CheckoutDraft | None
    ) -> bool: ...


class SQLitePaymentStore:
    """A transactional single-node store suitable for the demos and small deployments.

    Larger deployments implement :class:`PaymentStore` over their existing database.
    The schema deliberately stores no PayPal access token, funding source, or payer details.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS payment_checkouts (
                    checkout_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    paypal_order_id TEXT UNIQUE,
                    version INTEGER NOT NULL,
                    document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_webhooks (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
                """
            )
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)

    @staticmethod
    def _load(row: sqlite3.Row | tuple[Any, ...] | None) -> CheckoutDraft | None:
        return None if row is None else CheckoutDraft.model_validate_json(row[-1])

    async def create(self, draft: CheckoutDraft) -> None:
        async with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO payment_checkouts VALUES (?, ?, ?, ?, ?)",
                        (
                            draft.checkout_id,
                            draft.token_hash,
                            draft.paypal_order_id,
                            draft.version,
                            draft.model_dump_json(),
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise PaymentConflict("Checkout already exists") from error

    async def get_by_token_hash(self, token_hash: str) -> CheckoutDraft | None:
        async with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT document FROM payment_checkouts WHERE token_hash = ?", (token_hash,)
                ).fetchone()
        return self._load(row)

    async def get_by_order_id(self, order_id: str) -> CheckoutDraft | None:
        async with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT document FROM payment_checkouts WHERE paypal_order_id = ?", (order_id,)
                ).fetchone()
        return self._load(row)

    async def update(self, draft: CheckoutDraft, expected_version: int) -> CheckoutDraft:
        updated = draft.model_copy(
            update={"version": expected_version + 1, "updated_at": datetime.now(UTC)}
        )
        async with self._lock:
            with self._connect() as connection:
                try:
                    cursor = connection.execute(
                        """UPDATE payment_checkouts
                           SET paypal_order_id = ?, version = ?, document = ?
                           WHERE checkout_id = ? AND version = ?""",
                        (
                            updated.paypal_order_id,
                            updated.version,
                            updated.model_dump_json(),
                            updated.checkout_id,
                            expected_version,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise PaymentConflict("PayPal order is already attached") from error
                if cursor.rowcount != 1:
                    raise PaymentConflict("Checkout changed; retry the operation")
        return updated

    async def record_webhook(self, event_id: str, event_type: str) -> bool:
        async with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO payment_webhooks VALUES (?, ?, ?)",
                    (event_id, event_type, datetime.now(UTC).isoformat()),
                )
                return cursor.rowcount == 1

    async def forget_webhook(self, event_id: str) -> None:
        async with self._lock:
            with self._connect() as connection:
                connection.execute("DELETE FROM payment_webhooks WHERE event_id = ?", (event_id,))

    async def completed(self, merchant_id: str, user_id: str | None = None) -> list[CheckoutDraft]:
        async with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT document FROM payment_checkouts WHERE "
                    "json_extract(document, '$.status') = 'completed' AND "
                    "COALESCE(json_extract(document, '$.merchant_id'), 'default') = ?",
                    (merchant_id,),
                ).fetchall()
        drafts = [CheckoutDraft.model_validate_json(row[0]) for row in rows]
        return [d for d in drafts if user_id is None or d.user_id == user_id]

    async def commit_webhook(self, event_id, event_type, draft):
        async with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO payment_webhooks VALUES (?, ?, ?)",
                    (event_id, event_type, datetime.now(UTC).isoformat()),
                )
                if cursor.rowcount == 0:
                    return False
                if draft:
                    updated = draft.model_copy(
                        update={"version": draft.version + 1, "updated_at": datetime.now(UTC)}
                    )
                    cursor = connection.execute(
                        "UPDATE payment_checkouts SET document=?, version=? "
                        "WHERE checkout_id=? AND version=?",
                        (
                            updated.model_dump_json(),
                            updated.version,
                            draft.checkout_id,
                            draft.version,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise PaymentConflict("Checkout changed; retry the webhook")
                return True


class PayPalProvider(Protocol):
    config: PayPalConfig

    async def create_order(self, draft: CheckoutDraft, request_id: str) -> PayPalOrder: ...

    async def capture_order(self, order_id: str, request_id: str) -> PayPalOrder: ...

    async def verify_webhook(
        self, headers: Mapping[str, str], event: Mapping[str, Any]
    ) -> bool: ...


class PayPalClient:
    """Minimal async Orders v2 client with cached OAuth and idempotency headers."""

    def __init__(self, config: PayPalConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client or httpx.AsyncClient(timeout=config.timeout_s)
        self._owns_client = client is None
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token
            response = await self._client.post(
                f"{self.config.base_url}/v1/oauth2/token",
                auth=(self.config.client_id, self.config.client_secret),
                headers={"Accept": "application/json"},
                data={"grant_type": "client_credentials"},
            )
            data = self._json(response)
            if response.is_error or not data.get("access_token"):
                self._raise_provider("authentication", response, data)
            self._access_token = str(data["access_token"])
            # Refresh before expiry; short test tokens still get a small useful lifetime.
            self._token_expires_at = time.monotonic() + max(
                int(data.get("expires_in", 300)) - 60, 30
            )
            return self._access_token

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def _raise_provider(operation: str, response: httpx.Response, data: Mapping[str, Any]) -> None:
        details = data.get("details")
        issue = str(data.get("name") or data.get("message") or "provider error")
        if isinstance(details, list) and details and isinstance(details[0], dict):
            issue = str(details[0].get("issue") or details[0].get("description") or issue)
        raise PaymentProviderError(operation, response.status_code, issue, data.get("debug_id"))

    async def _post(
        self, path: str, payload: Mapping[str, Any], operation: str, request_id: str | None = None
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {await self._token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        if self.config.partner_attribution_id:
            headers["PayPal-Partner-Attribution-Id"] = self.config.partner_attribution_id
        if self.config.seller_merchant_id:

            def encode(value):
                return (
                    base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
                    .decode()
                    .rstrip("=")
                )

            headers["PayPal-Auth-Assertion"] = (
                encode({"alg": "none"})
                + "."
                + encode(
                    {
                        "iss": self.config.client_id,
                        "payer_id": self.config.seller_merchant_id,
                    }
                )
                + "."
            )
        response = await self._client.post(
            f"{self.config.base_url}{path}", headers=headers, json=dict(payload)
        )
        data = self._json(response)
        if response.is_error:
            self._raise_provider(operation, response, data)
        return data

    async def create_order(self, draft: CheckoutDraft, request_id: str) -> PayPalOrder:
        item_total = money(sum((item.total for item in draft.items), Decimal("0")))
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": draft.checkout_id,
                    "custom_id": draft.checkout_id,
                    "amount": {
                        "currency_code": draft.currency,
                        "value": f"{draft.amount:.2f}",
                        "breakdown": {
                            "item_total": {
                                "currency_code": draft.currency,
                                "value": f"{item_total:.2f}",
                            }
                        },
                    },
                    "items": [
                        {
                            "name": item.name,
                            "sku": item.product_id,
                            "unit_amount": {
                                "currency_code": draft.currency,
                                "value": f"{item.unit_amount:.2f}",
                            },
                            "quantity": str(item.quantity),
                        }
                        for item in draft.items
                    ],
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": self.config.brand_name,
                        "user_action": "PAY_NOW",
                    }
                }
            },
        }
        if self.config.seller_merchant_id:
            payload["purchase_units"][0]["payee"] = {"merchant_id": self.config.seller_merchant_id}
        data = await self._post("/v2/checkout/orders", payload, "create order", request_id)
        approval = next(
            (
                link.get("href")
                for link in data.get("links", [])
                if isinstance(link, dict) and link.get("rel") in {"approve", "payer-action"}
            ),
            None,
        )
        return PayPalOrder(
            order_id=str(data["id"]),
            status=str(data.get("status", "CREATED")),
            approval_url=approval,
        )

    async def capture_order(self, order_id: str, request_id: str) -> PayPalOrder:
        data = await self._post(
            f"/v2/checkout/orders/{order_id}/capture", {}, "capture order", request_id
        )
        units = data.get("purchase_units") or []
        captures = (
            units[0].get("payments", {}).get("captures", [])
            if units and isinstance(units[0], dict)
            else []
        )
        capture = captures[0] if captures and isinstance(captures[0], dict) else {}
        amount = capture.get("amount") or {}
        return PayPalOrder(
            order_id=str(data.get("id", order_id)),
            status=str(capture.get("status", "")),
            capture_id=str(capture.get("id")) if capture.get("id") else None,
            amount=money(amount["value"]) if amount.get("value") else None,
            currency=amount.get("currency_code"),
        )

    async def get_order(self, order_id: str) -> PayPalOrder:
        """Read an Orders v2 order. Used by the sandbox proof script to record the
        provider's own status after capture, independently of the local outbox."""
        response = await self._client.get(
            f"{self.config.base_url}/v2/checkout/orders/{order_id}",
            headers={
                "Authorization": f"Bearer {await self._token()}",
                "Accept": "application/json",
            },
        )
        data = self._json(response)
        if response.is_error:
            self._raise_provider("get order", response, data)
        approval = next(
            (
                link.get("href")
                for link in data.get("links", [])
                if isinstance(link, dict) and link.get("rel") in {"approve", "payer-action"}
            ),
            None,
        )
        units = data.get("purchase_units") or []
        captures = (
            units[0].get("payments", {}).get("captures", [])
            if units and isinstance(units[0], dict)
            else []
        )
        capture = captures[0] if captures and isinstance(captures[0], dict) else {}
        amount = (capture.get("amount") or {}).get("value")
        return PayPalOrder(
            order_id=str(data.get("id", order_id)),
            status=str(data.get("status", "")),
            approval_url=approval,
            capture_id=str(capture["id"]) if capture.get("id") else None,
            amount=money(amount) if amount else None,
            currency=(capture.get("amount") or {}).get("currency_code"),
        )

    async def verify_webhook(self, headers: Mapping[str, str], event: Mapping[str, Any]) -> bool:
        if not self.config.webhook_id:
            raise PaymentError("PAYPAL_WEBHOOK_ID is required to accept webhooks")
        lowered = {key.lower(): value for key, value in headers.items()}
        required = {
            "transmission_id": lowered.get("paypal-transmission-id"),
            "transmission_time": lowered.get("paypal-transmission-time"),
            "cert_url": lowered.get("paypal-cert-url"),
            "auth_algo": lowered.get("paypal-auth-algo"),
            "transmission_sig": lowered.get("paypal-transmission-sig"),
        }
        if not all(required.values()):
            return False
        data = await self._post(
            "/v1/notifications/verify-webhook-signature",
            {**required, "webhook_id": self.config.webhook_id, "webhook_event": dict(event)},
            "verify webhook",
        )
        return data.get("verification_status") == "SUCCESS"


def cart_fingerprint(items: Sequence[PaymentItem], currency: str) -> str:
    canonical = {
        "currency": currency,
        "items": [item.model_dump(mode="json") for item in items],
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class CheckoutService:
    """Coordinates immutable cart quotes, PayPal orders, captures, and webhooks.

    ``max_order_amount`` is the deployment's server-side hard ceiling. A shopper's cap
    (``spend_cap`` on :meth:`create_checkout`) can only tighten it, never widen it. Both
    are checked before any payment row or provider order exists, and again before an
    order is created, so a stale draft cannot outlive a tightened policy.
    """

    def __init__(
        self,
        store: PaymentStore,
        provider: PayPalProvider,
        merchant_id: str = "default",
        *,
        max_order_amount: Decimal | str | int | float | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.merchant_id = merchant_id
        ceiling = None if max_order_amount is None else money(max_order_amount)
        if ceiling is not None and ceiling <= 0:
            raise ValueError("max_order_amount must be greater than zero")
        self.max_order_amount = ceiling
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, checkout_id: str) -> asyncio.Lock:
        return self._locks.setdefault(checkout_id, asyncio.Lock())

    def effective_cap(self, spend_cap: Decimal | str | int | float | None = None) -> Decimal | None:
        """The shopper's cap clamped to the host ceiling, or the ceiling alone."""
        cap = None if spend_cap is None else money(spend_cap)
        if cap is not None and cap <= 0:
            raise PaymentError("The spend cap must be greater than zero")
        if self.max_order_amount is not None and (cap is None or cap > self.max_order_amount):
            return self.max_order_amount
        return cap

    def assert_within_cap(self, draft: CheckoutDraft) -> None:
        """Re-check the immutable quote against the policy in force right now."""
        cap = self.effective_cap(draft.spend_cap)
        if cap is not None and draft.amount > cap:
            raise SpendCapExceeded(draft.amount, cap, draft.currency)

    async def create_checkout(
        self,
        *,
        session_id: str,
        user_id: str,
        items: Sequence[PaymentItem],
        currency: str,
        spend_cap: Decimal | str | int | float | None = None,
    ) -> tuple[CheckoutDraft, str]:
        if not items:
            raise PaymentError("Cannot check out an empty cart")
        normalized_currency = currency.upper()
        quoted = tuple(items)
        amount = money(sum((item.total for item in quoted), Decimal("0")))
        cap = self.effective_cap(spend_cap)
        if cap is not None and amount > cap:
            # Deliberately before the store write: an over-cap request leaves nothing.
            raise SpendCapExceeded(amount, cap, normalized_currency)
        token = secrets.token_urlsafe(32)
        draft = CheckoutDraft(
            checkout_id=f"co_{secrets.token_urlsafe(18)}",
            token_hash=token_digest(token),
            session_id=session_id,
            user_id=user_id,
            merchant_id=self.merchant_id,
            cart_hash=cart_fingerprint(quoted, normalized_currency),
            items=quoted,
            currency=normalized_currency,
            amount=amount,
            spend_cap=cap,
        )
        await self.store.create(draft)
        return draft, token

    async def require(self, token: str) -> CheckoutDraft:
        draft = await self.store.get_by_token_hash(token_digest(token))
        if draft is None or draft.merchant_id != self.merchant_id:
            raise PaymentNotFound("Checkout not found")
        if draft.expires_at < datetime.now(UTC) and draft.status != CheckoutStatus.COMPLETED:
            raise PaymentNotFound("Checkout expired")
        return draft

    async def create_order(self, token: str) -> CheckoutDraft:
        draft = await self.require(token)
        async with self._lock(draft.checkout_id):
            draft = await self.require(token)
            if draft.paypal_order_id:
                return draft
            self.assert_within_cap(draft)
            order = await self.provider.create_order(draft, f"{draft.checkout_id}-create")
            return await self.store.update(
                draft.model_copy(
                    update={
                        "paypal_order_id": order.order_id,
                        "approval_url": order.approval_url,
                        "provider_status": order.status,
                        "status": CheckoutStatus.CREATED,
                    }
                ),
                draft.version,
            )

    async def capture(self, token: str, order_id: str) -> CheckoutDraft:
        draft = await self.require(token)
        async with self._lock(draft.checkout_id):
            draft = await self.require(token)
            if draft.paypal_order_id != order_id:
                raise PaymentConflict("PayPal order does not belong to this checkout")
            if draft.status == CheckoutStatus.COMPLETED:
                return draft
            captured = await self.provider.capture_order(order_id, f"{draft.checkout_id}-capture")
            if captured.status != "COMPLETED":
                raise PaymentConflict(f"PayPal order is {captured.status or 'not completed'}")
            if (
                captured.order_id != order_id
                or not captured.capture_id
                or captured.amount != draft.amount
                or captured.currency != draft.currency
            ):
                raise PaymentConflict("Captured amount or currency does not match the checkout")
            return await self.store.update(
                draft.model_copy(
                    update={
                        "capture_id": captured.capture_id,
                        "provider_status": captured.status,
                        "status": CheckoutStatus.COMPLETED,
                    }
                ),
                draft.version,
            )

    async def process_webhook(
        self, headers: Mapping[str, str], event: Mapping[str, Any]
    ) -> tuple[bool, CheckoutDraft | None]:
        if not await self.provider.verify_webhook(headers, event):
            raise PaymentError("Invalid PayPal webhook signature")
        event_id = str(event.get("id", ""))
        event_type = str(event.get("event_type", ""))
        if not event_id or not event_type:
            raise PaymentError("Malformed PayPal webhook")
        try:
            resource = event.get("resource")
            resource = resource if isinstance(resource, dict) else {}
            order_id = str(
                resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
                or resource.get("id", "")
            )
            draft = await self.store.get_by_order_id(order_id) if order_id else None
            if not draft and event_type == "PAYMENT.CAPTURE.COMPLETED":
                raise PaymentConflict("Capture order is not recorded yet; retry webhook")
            if draft and draft.merchant_id != self.merchant_id:
                raise PaymentConflict("Webhook belongs to another merchant")
            if draft:
                async with self._lock(draft.checkout_id):
                    draft = await self.store.get_by_order_id(order_id)
                    assert draft is not None
                    changes: dict[str, Any] = {}
                    if event_type == "PAYMENT.CAPTURE.COMPLETED":
                        amount = resource.get("amount") or {}
                        if (
                            resource.get("status") != "COMPLETED"
                            or not resource.get("id")
                            or money(amount.get("value", "0")) != draft.amount
                            or amount.get("currency_code") != draft.currency
                            or (draft.capture_id and draft.capture_id != resource["id"])
                        ):
                            raise PaymentConflict("Capture webhook does not match the checkout")
                        changes = {
                            "status": CheckoutStatus.COMPLETED,
                            "capture_id": resource["id"],
                            "provider_status": "COMPLETED",
                        }
                    elif event_type == "CHECKOUT.ORDER.APPROVED" and draft.status in {
                        CheckoutStatus.DRAFT,
                        CheckoutStatus.CREATED,
                    }:
                        changes = {"status": CheckoutStatus.APPROVED}
                    elif (
                        event_type == "PAYMENT.CAPTURE.DENIED"
                        and draft.status != CheckoutStatus.COMPLETED
                    ):
                        changes = {"status": CheckoutStatus.FAILED}
                    draft = draft.model_copy(update=changes)
                    processed = await self.store.commit_webhook(event_id, event_type, draft)
                    return processed, await self.store.get_by_order_id(
                        order_id
                    ) if processed else None
            processed = await self.store.commit_webhook(event_id, event_type, None)
            return processed, None
        except Exception:
            # Deduplication and state updates commit together; failures leave no event marker.
            raise


class OrderFinalizer(Protocol):
    async def finalize(self, draft: CheckoutDraft, idempotency_key: str) -> str:
        """Return the existing or new commerce order id. The key MUST deduplicate writes
        in the destination system, including a crash after creating the remote order."""
        ...


async def drain_finalizations(service: CheckoutService, target: OrderFinalizer) -> int:
    """Recoverable outbox consumer. Capture and pending work share one atomic row update.

    A versioned lease prevents simultaneous workers from normally issuing the same request;
    destination idempotency protects retries after lease expiry or a lost response.
    Failures remain pending with bounded exponential backoff, never trigger another charge.
    """
    finished = 0
    for draft in await service.store.completed(service.merchant_id):
        if draft.commerce_order_id or draft.retry_at > datetime.now(UTC):
            continue
        try:
            claimed = await service.store.update(
                draft.model_copy(
                    update={
                        "retry_at": datetime.now(UTC) + timedelta(minutes=5),
                        "finalization_attempts": draft.finalization_attempts + 1,
                    }
                ),
                draft.version,
            )
        except PaymentConflict:
            continue
        try:
            order_id = await target.finalize(claimed, claimed.checkout_id)
            if not order_id:
                raise PaymentError("Finalizer returned no order id")
            await service.store.update(
                claimed.model_copy(update={"commerce_order_id": order_id}), claimed.version
            )
            finished += 1
        except Exception:
            # Do not persist exception text: upstream errors can contain customer data.
            with contextlib.suppress(PaymentConflict):
                await service.store.update(
                    claimed.model_copy(
                        update={
                            "retry_at": datetime.now(UTC)
                            + timedelta(
                                seconds=min(3600, 2 ** min(claimed.finalization_attempts, 12))
                            ),
                        }
                    ),
                    claimed.version,
                )
    return finished
