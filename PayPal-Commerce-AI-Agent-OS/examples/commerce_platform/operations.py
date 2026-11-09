"""Merchant-only operational review and provider execution routes."""

import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from commerce_common.control_store import Conflict
from commerce_common.operations import Operations
from commerce_common.payments import PayPalClient, PayPalConfig


class Review(BaseModel):
    decision: str
    reason: str = Field(min_length=1, max_length=2000)


class Stage(BaseModel):
    kind: str
    order_id: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    payload: dict


class Approval(BaseModel):
    version: int = Field(ge=1)


class AccountingPage(BaseModel):
    page: int = Field(default=1, ge=1, le=1000000)


class ProviderCredentials(BaseModel):
    shopify_admin_token: str = Field(default="", max_length=4096)
    paypal_client_id: str = Field(default="", max_length=4096)
    paypal_client_secret: str = Field(default="", max_length=4096)
    paypal_sandbox: bool = True


def operations_router(store, principal, member):
    router = APIRouter(prefix="/api/merchants/{tenant}")
    signed_in = Depends(principal)
    service = Operations(store)

    @router.post("/accounting/sync")
    async def sync_accounting(tenant: str, body: AccountingPage, user=signed_in):
        member(tenant, user, owner=True)
        from commerce_common.accounting import record_order
        from shopping_agent.woocommerce import WooCommerceBackend

        config = store.secret(tenant, "connection")
        if not config or config["platform"] != "woocommerce":
            raise HTTPException(409, "WooCommerce polling only; Shopify uses signed webhooks")
        backend = WooCommerceBackend(config["url"], config["secret"], tenant)
        try:
            data = await backend._call("POST", "/accounting", {"page": body.page})
            for order in data["orders"]:
                record_order(
                    store,
                    tenant,
                    "woocommerce",
                    order["id"],
                    order["currency"],
                    order["total"],
                    order["refunds"],
                )
            store.audit(tenant, user["user"], "accounting.synced", str(body.page))
            return {"orders": len(data["orders"]), "next_page": data["next_page"]}
        finally:
            await backend.aclose()

    @router.put("/operations/credentials")
    def credentials(tenant: str, body: ProviderCredentials, user=signed_in):
        member(tenant, user, owner=True)
        store.save_secret(tenant, "operations", body.model_dump())
        store.audit(tenant, user["user"], "operations.credentials.updated", tenant)
        return {"saved": True}

    @router.get("/operations")
    def listing(tenant: str, user=signed_in):
        member(tenant, user)
        return {
            "operations": store.list(tenant, "operations"),
            "reviews": store.list(tenant, "fraud_reviews"),
        }

    @router.put("/reviews/{order_id}")
    def review(tenant: str, order_id: str, body: Review, user=signed_in):
        member(tenant, user, owner=True)
        try:
            return service.review(tenant, user["user"], order_id, body.decision, body.reason)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/operations")
    def stage(tenant: str, body: Stage, user=signed_in):
        member(tenant, user)
        config = store.secret(tenant, "connection")
        if not config:
            raise HTTPException(409, "Connect a store first")
        if body.kind == "shipment":
            url = urlsplit(body.payload.get("tracking_url", ""))
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or not body.payload.get("tracking_number")
            ):
                raise HTTPException(422, "An HTTPS tracking URL and tracking number are required")
        elif body.kind == "refund":
            from decimal import Decimal, InvalidOperation

            try:
                value = Decimal(str(body.payload.get("amount", "0")))
                if not value.is_finite() or value <= 0:
                    raise ValueError()
            except (ValueError, InvalidOperation) as error:
                raise HTTPException(422, "Positive refund amount required") from error
            if config["platform"] != "woocommerce":
                raise HTTPException(
                    422,
                    "This refund executor supports WooCommerce only; use Shopify Admin for Shopify refunds",
                )
        elif body.kind == "dispute_evidence":
            if not re.fullmatch(r"PP-D-[A-Za-z0-9-]+", body.order_id) or not body.payload.get(
                "notes"
            ):
                raise HTTPException(422, "PayPal dispute id and evidence notes are required")
        try:
            return service.stage(
                tenant,
                user["user"],
                body.kind,
                body.order_id,
                body.payload,
                connection_version=store.get(tenant, "secrets", "connection")["version"],
                credentials_version=(store.get(tenant, "secrets", "operations") or {}).get(
                    "version", 0
                ),
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/operations/{operation_id}/approve")
    def approve(tenant: str, operation_id: str, body: Approval, user=signed_in):
        member(tenant, user, owner=True)
        return service.approve(tenant, user["user"], operation_id, body.version)

    @router.post("/operations/{operation_id}/execute")
    async def execute(tenant: str, operation_id: str, user=signed_in):
        member(tenant, user, owner=True)
        row = store.get(tenant, "operations", operation_id)
        if (
            row
            and row["data"]["status"] != "completed"
            and (
                row["data"].get("connection_version")
                != (store.get(tenant, "secrets", "connection") or {}).get("version", 0)
                or row["data"].get("credentials_version")
                != (store.get(tenant, "secrets", "operations") or {}).get("version", 0)
            )
        ):
            raise Conflict("Provider credentials changed; stage and approve a new operation")

        async def provider(operation, key):
            config = store.secret(tenant, "connection")
            credentials = store.secret(tenant, "operations") or {}
            return await execute_provider(tenant, config, credentials, operation, key)

        try:
            return await service.execute(tenant, user["user"], operation_id, provider)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    return router


async def execute_provider(tenant, config, credentials, operation, key):
    if operation["kind"] == "dispute_evidence":
        client = PayPalClient(
            PayPalConfig(
                client_id=credentials["paypal_client_id"],
                client_secret=credentials["paypal_client_secret"],
                sandbox=credentials.get("paypal_sandbox", True),
            )
        )
        try:
            path = "/v1/customer/disputes/" + operation["order_id"]
            response = await client._client.get(
                client.config.base_url + path,
                headers={"Authorization": "Bearer " + await client._token()},
            )
            response.raise_for_status()
            detail = response.json()
            # Never follow a provider-supplied URL: validate capability, then use
            # our fixed API base/path. The direct merchant OAuth token scopes access.
            if not any(link.get("rel") == "provide_evidence" for link in detail.get("links", [])):
                raise ValueError("PayPal is not accepting evidence for this dispute")
            await client._post(
                path + "/provide-evidence",
                {
                    "evidences": [
                        {
                            "evidence_type": "OTHER",
                            "notes": operation["payload"]["notes"],
                        }
                    ]
                },
                "dispute evidence",
            )
            return {"status": "completed", "dispute_id": operation["order_id"], "submitted": True}
        finally:
            await client.aclose()
    if config["platform"] == "woocommerce":
        from shopping_agent.woocommerce import WooCommerceBackend

        backend = WooCommerceBackend(config["url"], config["secret"], tenant)
        try:
            return await backend._call(
                "POST",
                "/operations",
                {
                    "operation_id": key,
                    "kind": operation["kind"],
                    "order_id": operation["order_id"],
                    "payload": operation["payload"],
                },
            )
        finally:
            await backend.aclose()
    if operation["kind"] != "shipment" or not operation["order_id"].isdigit():
        raise ValueError("Unsupported Shopify operation")
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:

        async def graphql(query, variables):
            response = await client.post(
                config["url"].rstrip("/") + "/admin/api/2026-04/graphql.json",
                headers={"X-Shopify-Access-Token": credentials["shopify_admin_token"]},
                json={"query": query, "variables": variables},
            )
            response.raise_for_status()
            result = response.json()
            if result.get("errors"):
                raise ValueError("Shopify rejected the operation")
            return result["data"]

        data = await graphql(
            """query($id:ID!) { order(id:$id) { cancelledAt displayFinancialStatus
          fulfillmentOrders(first:100) { nodes { id status } pageInfo { hasNextPage } } } }""",
            {"id": "gid://shopify/Order/" + operation["order_id"]},
        )
        order = data["order"]
        if (
            not order
            or order["cancelledAt"]
            or order["displayFinancialStatus"] not in {"PAID", "PARTIALLY_REFUNDED"}
            or order["fulfillmentOrders"]["pageInfo"]["hasNextPage"]
        ):
            raise ValueError("Order is not eligible for shipment")
        groups = [
            {"fulfillmentOrderId": row["id"]}
            for row in order["fulfillmentOrders"]["nodes"]
            if row["status"] == "OPEN"
        ]
        if not groups:
            raise ValueError("No open fulfillment orders")
        result = await graphql(
            """mutation($input:FulfillmentInput!) { fulfillmentCreate(fulfillment:$input) {
            fulfillment { id status } userErrors { message } } }""",
            {
                "input": {
                    "lineItemsByFulfillmentOrder": groups,
                    "notifyCustomer": True,
                    "trackingInfo": {
                        "number": operation["payload"]["tracking_number"],
                        "url": operation["payload"]["tracking_url"],
                    },
                }
            },
        )
        outcome = result["fulfillmentCreate"]
        if (
            outcome["userErrors"]
            or not outcome["fulfillment"]
            or outcome["fulfillment"]["status"] != "SUCCESS"
        ):
            raise ValueError("Fulfillment was not confirmed")
        return {"status": "completed", "fulfillment_id": outcome["fulfillment"]["id"]}
