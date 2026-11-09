"""Merchant administration: uvicorn commerce_platform.app:from_env --factory --app-dir examples.

Registration is invitation-gated. TLS termination and request rate limiting belong
at the reverse proxy. Secrets are encrypted at rest and never returned to browsers.
"""

from __future__ import annotations

import csv
import hmac
import io
import os
import re
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from commerce_common.control_store import (
    Conflict,
    ControlStore,
    digest,
    password_hash,
    password_matches,
)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    invitation: str = ""


class Merchant(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Connection(BaseModel):
    platform: str
    url: str
    secret: str = Field(min_length=32, max_length=4096)
    webhook_secret: str = Field(default="", max_length=4096)


class Publication(BaseModel):
    enabled: bool


class Member(BaseModel):
    email: str
    role: str = "staff"


def create_app(store: ControlStore, *, origin: str, invitation: str, secure=True):
    from urllib.parse import urlsplit

    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI(title="Commerce merchant administration")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(origin).hostname])

    @app.exception_handler(Conflict)
    async def conflict(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.middleware("http")
    async def browser_security(request, call_next):
        is_webhook = re.fullmatch(r"/webhooks/shopify/[a-f0-9]{32}", request.url.path)
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and not is_webhook
            and request.headers.get("origin") != origin
        ):
            return Response("Origin denied", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    def principal(request: Request):
        token = request.cookies.get("merchant_session", "")
        session = store.get("_auth", "sessions", digest(token)) if token else None
        if not session or session["data"]["expires"] < time.time():
            raise HTTPException(401, "Sign in required")
        if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), session["data"]["csrf"]
        ):
            raise HTTPException(403, "CSRF token required")
        return session["data"]

    signed_in = Depends(principal)

    def member(tenant, user, *, owner=False):
        try:
            store.require_member(tenant, user["user"], owner=owner)
        except PermissionError as error:
            raise HTTPException(403, "Merchant access denied") from error

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).with_name("admin.html"))

    @app.get("/admin.js", include_in_schema=False)
    def script():
        return FileResponse(Path(__file__).with_name("admin.js"), media_type="text/javascript")

    @app.get("/shopper.js", include_in_schema=False)
    def shopper_script():
        return FileResponse(Path(__file__).with_name("shopper.js"), media_type="text/javascript")

    @app.get("/shop/{tenant}", include_in_schema=False)
    def shopper(tenant: str):
        publication = store.get(tenant, "settings", "published")
        if not publication or not publication["data"]["enabled"]:
            raise HTTPException(404, "Storefront not published")
        return FileResponse(Path(__file__).with_name("shopper.html"))

    @app.post("/api/register", status_code=201)
    def register(body: Credentials):
        if not invitation or not hmac.compare_digest(body.invitation, invitation):
            raise HTTPException(403, "Valid invitation required")
        email = body.email.strip().lower()
        if "@" not in email:
            raise HTTPException(422, "Email required")
        store.put(
            "_auth",
            "users",
            digest(email),
            {"email": email, "password": password_hash(body.password)},
        )
        return {"registered": True}

    @app.post("/api/login")
    def login(body: Credentials, response: Response):
        user_id = digest(body.email.strip().lower())
        user = store.get("_auth", "users", user_id)
        # Always perform a password derivation, including unknown accounts.
        encoded = user["data"]["password"] if user else password_hash("not-a-real-password")
        valid = password_matches(body.password, encoded)
        if not user or not valid:
            raise HTTPException(401, "Invalid credentials")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        store.put(
            "_auth",
            "sessions",
            digest(token),
            {
                "user": user_id,
                "csrf": csrf,
                "expires": time.time() + 28800,
            },
        )
        response.set_cookie(
            "merchant_session",
            token,
            secure=secure,
            httponly=True,
            samesite="strict",
            max_age=28800,
        )
        return {"csrf": csrf}

    @app.get("/api/me")
    def me(user=signed_in):
        return {"csrf": user["csrf"]}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, user=signed_in):
        store.delete("_auth", "sessions", digest(request.cookies["merchant_session"]))
        response.delete_cookie("merchant_session")
        return {"signed_out": True}

    @app.post("/api/merchants", status_code=201)
    def create_merchant(body: Merchant, user=signed_in):
        tenant = secrets.token_hex(16)
        # Membership is authoritative. An interrupted creation cannot grant another
        # principal access or publish a partially configured storefront.
        store.put(tenant, "members", user["user"], {"role": "owner"})
        store.put("_directory", "merchants", tenant, {"name": body.name})
        store.audit(tenant, user["user"], "merchant.created", tenant)
        return {"id": tenant, "name": body.name}

    @app.get("/api/merchants")
    def merchants(user=signed_in):
        return [
            {"id": row["key"], **row["data"]}
            for row in store.list("_directory", "merchants")
            if store.get(row["key"], "members", user["user"])
        ]

    @app.post("/api/merchants/{tenant}/members")
    def add_member(tenant: str, body: Member, user=signed_in):
        member(tenant, user, owner=True)
        target = digest(body.email.strip().lower())
        if body.role not in {"owner", "staff"} or not store.get("_auth", "users", target):
            raise HTTPException(422, "Choose an existing account and owner/staff role")
        # This endpoint adds members; it cannot demote/remove the last owner.
        store.put(tenant, "members", target, {"role": body.role})
        store.audit(tenant, user["user"], "member.added", target)
        return {"added": True}

    @app.put("/api/merchants/{tenant}/connection")
    def connection(tenant: str, body: Connection, user=signed_in):
        member(tenant, user, owner=True)
        existing = store.secret(tenant, "connection")
        if existing and (
            existing["platform"] != body.platform
            or existing["url"].rstrip("/") != body.url.rstrip("/")
        ):
            raise HTTPException(
                409,
                "Create a new merchant for a different store; existing carts and orders are store-bound",
            )
        # Tenant-supplied arbitrary URLs permit SSRF. Shopify has a fixed host suffix;
        # WooCommerce hosts must be operator-allowlisted before merchants connect.
        from urllib.parse import urlsplit

        parsed = urlsplit(body.url)
        allowed = set(os.environ.get("COMMERCE_ALLOWED_WOO_HOSTS", "").split(","))
        valid_shop = re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", parsed.hostname or "")
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not (
                (body.platform == "shopify" and valid_shop)
                or (body.platform == "woocommerce" and parsed.hostname in allowed)
            )
        ):
            raise HTTPException(422, "Use an approved HTTPS store origin")
        store.save_secret(tenant, "connection", body.model_dump())
        store.audit(tenant, user["user"], "connection.updated", body.platform)
        return {"platform": body.platform, "url": body.url, "configured": True}

    @app.get("/api/merchants/{tenant}/connection")
    def connection_status(tenant: str, user=signed_in):
        member(tenant, user)
        config = store.secret(tenant, "connection")
        return {
            "configured": bool(config),
            **({k: config[k] for k in ("platform", "url")} if config else {}),
        }

    @app.post("/api/merchants/{tenant}/connection/test")
    async def test_connection(tenant: str, user=signed_in):
        member(tenant, user, owner=True)
        config = store.secret(tenant, "connection")
        if not config:
            raise HTTPException(409, "Configure a store first")
        try:
            if config["platform"] == "woocommerce":
                from shopping_agent.woocommerce import WooCommerceBackend

                backend = WooCommerceBackend(config["url"], config["secret"], tenant)
                try:
                    await backend._call("POST", "/catalog", {"query": "", "limit": 1})
                finally:
                    await backend.aclose()
            else:
                from shopping_agent.shopify import ShopifyBackend

                backend = ShopifyBackend(config["url"], config["secret"], tenant, store)
                try:
                    await backend.graphql("{ shop { name } }", {})
                finally:
                    await backend.aclose()
        except Exception as error:
            raise HTTPException(
                502, "Store connection failed; inspect server configuration"
            ) from error
        store.audit(tenant, user["user"], "connection.verified", config["platform"])
        return {"connected": True}

    @app.get("/api/merchants/{tenant}/audit")
    def audit(tenant: str, user=signed_in):
        member(tenant, user)
        return store.list(tenant, "audit")

    @app.get("/api/merchants/{tenant}/ledger.csv")
    def ledger(tenant: str, user=signed_in):
        member(tenant, user, owner=True)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["event", "currency", "account", "minor_units"])

        def safe(value):
            value = str(value)
            return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value

        for row in store.list(tenant, "ledger"):
            for entry in row["data"]["entries"]:
                writer.writerow(
                    [
                        safe(row["key"]),
                        safe(row["data"]["currency"]),
                        safe(entry["account"]),
                        entry["amount"],
                    ]
                )
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="ledger.csv"'},
        )

    @app.put("/api/merchants/{tenant}/publication")
    def publish(tenant: str, body: Publication, user=signed_in):
        member(tenant, user, owner=True)
        config = store.secret(tenant, "connection")
        if body.enabled and (
            not config or (config["platform"] == "shopify" and not config.get("webhook_secret"))
        ):
            raise HTTPException(
                409, "Configure the store and Shopify webhook secret before publishing"
            )
        old = store.get(tenant, "settings", "published")
        store.put(
            tenant, "settings", "published", body.model_dump(), version=old["version"] if old else 0
        )
        store.audit(tenant, user["user"], "publication.updated", str(body.enabled))
        return {"enabled": body.enabled, "api": f"/stores/{tenant}/api"}

    from urllib.parse import urlsplit

    from .shopify_webhooks import webhook_router
    from .storefronts import TenantStorefronts

    def webhook_config(tenant):
        config = store.secret(tenant, "connection")
        if config and config["platform"] == "shopify" and config.get("webhook_secret"):
            return {"domain": urlsplit(config["url"]).hostname, "secret": config["webhook_secret"]}
        return None

    app.include_router(webhook_router(store, webhook_config))
    from .operations import operations_router

    app.include_router(operations_router(store, principal, member))
    app.mount("/stores/{tenant}", TenantStorefronts(store))
    return app


def from_env():
    return create_app(
        ControlStore(
            os.environ["COMMERCE_CONTROL_DATABASE_URL"], os.environ["COMMERCE_ENCRYPTION_KEY"]
        ),
        origin=os.environ["COMMERCE_ADMIN_ORIGIN"],
        invitation=os.environ["COMMERCE_REGISTRATION_CODE"],
    )


# Factory mode avoids connecting to infrastructure merely by importing this module.
# uvicorn commerce_platform.app:from_env --factory --app-dir examples
