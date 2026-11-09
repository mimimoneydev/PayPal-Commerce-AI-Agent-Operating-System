"""Human-approved operational changes with durable, fail-closed execution.

Never retry an ambiguous non-idempotent provider operation automatically. A process
crash leaves 'running', which is an explicit reconciliation case, not success.
"""

from __future__ import annotations

import secrets
import time

from .control_store import Conflict


class Operations:
    def __init__(self, store):
        self.store = store

    def review(self, tenant, actor, order_id, decision, reason):
        self.store.require_member(tenant, actor, owner=True)
        if decision not in {"hold", "release", "reject"} or not reason.strip():
            raise ValueError("A review decision and reason are required")
        old = self.store.get(tenant, "fraud_reviews", order_id)
        data = {"decision": decision, "reason": reason, "actor": actor, "at": time.time()}
        row = self.store.put(
            tenant, "fraud_reviews", order_id, data, version=old["version"] if old else 0
        )
        self.store.audit(tenant, actor, "fraud.reviewed", order_id)
        return row

    def stage(
        self,
        tenant,
        actor,
        kind,
        order_id,
        payload,
        *,
        connection_version=None,
        credentials_version=None,
    ):
        self.store.require_member(tenant, actor)
        if kind not in {"shipment", "refund", "dispute_evidence"}:
            raise ValueError("Unsupported operation")
        operation_id = secrets.token_hex(16)
        row = self.store.put(
            tenant,
            "operations",
            operation_id,
            {
                "kind": kind,
                "order_id": order_id,
                "payload": payload,
                "status": "staged",
                "created_by": actor,
                "created_at": time.time(),
                "connection_version": connection_version,
                "credentials_version": credentials_version,
            },
        )
        self.store.audit(tenant, actor, "operation.staged", operation_id)
        return row

    def approve(self, tenant, actor, operation_id, version):
        self.store.require_member(tenant, actor, owner=True)
        row = self.store.get(tenant, "operations", operation_id)
        if not row or row["version"] != version or row["data"]["status"] != "staged":
            raise Conflict("Only the displayed staged operation can be approved")
        data = row["data"] | {"status": "approved", "approved_by": actor}
        result = self.store.put(tenant, "operations", operation_id, data, version=version)
        self.store.audit(tenant, actor, "operation.approved", operation_id)
        return result

    async def execute(self, tenant, actor, operation_id, provider):
        self.store.require_member(tenant, actor, owner=True)
        row = self.store.get(tenant, "operations", operation_id)
        if not row:
            raise ValueError("Unknown operation")
        if row["data"]["status"] == "completed":
            return row
        if row["data"]["status"] != "approved":
            raise Conflict("Operation needs approval or provider reconciliation")
        if row["data"]["kind"] == "shipment":
            review = self.store.get(tenant, "fraud_reviews", row["data"]["order_id"])
            if not review or review["data"]["decision"] != "release":
                raise Conflict("Fraud review must release this order before shipping")
        running = self.store.put(
            tenant,
            "operations",
            operation_id,
            row["data"] | {"status": "running", "started_at": time.time()},
            version=row["version"],
        )
        self.store.audit(tenant, actor, "operation.started", operation_id)
        try:
            result = await provider(running["data"], operation_id)
            if result.get("status") != "completed":
                raise RuntimeError("Provider has not confirmed completion")
        except Exception:
            # Deliberately omit upstream exception/body: it can contain tokens or PII.
            result = {
                "status": "unknown",
                "message": "Inspect the provider before taking another action",
            }
        final = self.store.put(
            tenant,
            "operations",
            operation_id,
            running["data"] | {"status": result["status"], "result": result},
            version=running["version"],
        )
        self.store.audit(tenant, actor, "operation." + result["status"], operation_id)
        return final
