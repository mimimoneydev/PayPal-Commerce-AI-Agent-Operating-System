"""Tenant routing and atomic durable shopper sessions."""

from pathlib import Path

from starlette.responses import JSONResponse

from commerce_common.control_store import Conflict
from demo_common.sessions import SessionConflictError, SessionStore
from shopping_agent import ShoppingSessionState


class DurableSessions(SessionStore):
    allow_turn_overwrite = False

    def __init__(self, store, tenant):
        super().__init__(ShoppingSessionState)
        self.store, self.tenant = store, tenant

    def read_state(self, session_id):
        row = self.store.get(self.tenant, "shopper_sessions", session_id)
        return (row["version"], row["data"]["state"]) if row else None

    def read_messages(self, session_id):
        row = self.store.get(self.tenant, "shopper_sessions", session_id)
        return row["data"]["messages"] if row else []

    def require(self, session_id):
        from demo_common.sessions import SessionRecord, UnknownSessionError

        row = self.store.get(self.tenant, "shopper_sessions", session_id)
        if not row:
            raise UnknownSessionError(session_id)
        document, messages = row["data"]["state"], row["data"]["messages"]
        return SessionRecord(
            session_id=session_id,
            user_id=document["user_id"],
            state=ShoppingSessionState.model_validate(document["state"]),
            messages=messages,
            pending_app_events=document["pending_app_events"],
            payment_events=document.get("payment_events", []),
            version=row["version"],
            stored_state=document,
            stored_messages=len(messages),
        )

    def save(self, record):
        if record.ended:
            return
        document = record.state_document()
        if (
            record.version
            and document == record.stored_state
            and len(record.messages) == record.stored_messages
        ):
            return
        try:
            row = self.store.put(
                self.tenant,
                "shopper_sessions",
                record.session_id,
                {"state": document, "messages": record.messages},
                version=record.version,
            )
        except Conflict as error:
            raise SessionConflictError(record.session_id) from error
        record.version, record.stored_state = row["version"], document
        record.stored_messages = len(record.messages)

    def delete(self, session_id):
        self.store.delete(self.tenant, "shopper_sessions", session_id)

    def session_ids_for_user(self, user_id):
        return [
            row["key"]
            for row in self.store.list(self.tenant, "shopper_sessions")
            if row["data"]["state"]["user_id"] == user_id
        ]


class TenantStorefronts:
    def __init__(self, store):
        self.store = store

    async def __call__(self, scope, receive, send):
        tenant = scope["path_params"]["tenant"]
        publication = self.store.get(tenant, "settings", "published")
        config = self.store.secret(tenant, "connection")
        if not publication or not publication["data"]["enabled"] or not config:
            await JSONResponse({"detail": "Storefront not published"}, status_code=404)(
                scope, receive, send
            )
            return
        from commerce_common.memory import InMemoryMemoryStore
        from commerce_common.model_provider import model_config_overrides
        from demo_common import REPO_ROOT, MemorySeeder, build_storefront_host
        from shopping_agent import ShoppingAgentConfig
        from shopping_agent.shopify import ShopifyBackend
        from shopping_agent.woocommerce import WooCommerceBackend
        from shopping_agent_runtime import ShoppingAgent

        backend = (
            ShopifyBackend(config["url"], config["secret"], tenant, self.store)
            if config["platform"] == "shopify"
            else WooCommerceBackend(config["url"], config["secret"], tenant)
        )
        merchant = self.store.get("_directory", "merchants", tenant)["data"]["name"]
        backend.store_name = merchant

        class RequestAgent(ShoppingAgent):
            async def update_memory(self, messages, session):
                # This host persists conversation state, not extracted long-term
                # memory. Do not launch a paid extraction whose results are discarded.
                return []

        agent = RequestAgent(
            backend=backend,
            skills_dir=REPO_ROOT / "shopping-agent" / "skills",
            config=ShoppingAgentConfig(
                brand_name=merchant,
                assistant_name=f"{merchant} Assistant",
                **model_config_overrides(),
            ),
            memory_store=InMemoryMemoryStore(),
        )
        host = build_storefront_host(
            title=merchant,
            example_root=Path(__file__).parent,
            backend=backend,
            agent=agent,
            memory_seeder=MemorySeeder(Path("/nonexistent"), enabled=False),
            sessions=DurableSessions(self.store, tenant),
        )
        # The parent enforces its configured public hostname and same-origin policy;
        # remove the demo-only localhost middleware from this nested application.
        from starlette.middleware.cors import CORSMiddleware
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        host.app.user_middleware = [
            middleware
            for middleware in host.app.user_middleware
            if middleware.cls not in {TrustedHostMiddleware, CORSMiddleware}
        ]
        # Instances live for one request; credentials rotate on the next request and
        # no cache can accidentally reuse one merchant's backend for another.
        try:
            await host.app(scope, receive, send)
        finally:
            await backend.aclose()
            await agent.client.close()
