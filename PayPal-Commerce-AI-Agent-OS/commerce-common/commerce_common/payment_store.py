"""PostgreSQL payment storage; install commerce-common[payments] to enable it."""

from datetime import UTC, datetime

from .payments import CheckoutDraft, PaymentConflict


class PostgresPaymentStore:
    """One shared database for API replicas and outbox workers.

    Uses psycopg asynchronous connections, transaction-scoped CAS writes, and unique
    provider order/event ids. Constructing this object does not connect or run DDL.
    Run initialize once as a deployment migration before accepting traffic.
    """

    def __init__(self, dsn: str):
        from psycopg import AsyncConnection

        self.dsn = dsn
        self.connection = AsyncConnection

    async def initialize(self):
        async with await self.connection.connect(self.dsn) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_checkouts (
                    checkout_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    paypal_order_id TEXT UNIQUE,
                    version INTEGER NOT NULL,
                    document TEXT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_webhooks (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS payment_merchant_status
                ON payment_checkouts ((document::jsonb->>'merchant_id'),
                                      (document::jsonb->>'status'))
            """)

    async def create(self, draft: CheckoutDraft):
        from psycopg.errors import UniqueViolation

        try:
            async with await self.connection.connect(self.dsn) as conn:
                await conn.execute(
                    "INSERT INTO payment_checkouts VALUES (%s,%s,%s,%s,%s)",
                    (
                        draft.checkout_id,
                        draft.token_hash,
                        draft.paypal_order_id,
                        draft.version,
                        draft.model_dump_json(),
                    ),
                )
        except UniqueViolation as error:
            raise PaymentConflict("Checkout already exists") from error

    async def _get(self, column: str, value: str):
        # Only the two constants below may select a column; never caller-supplied SQL.
        assert column in {"token_hash", "paypal_order_id"}
        async with await self.connection.connect(self.dsn) as conn:
            cursor = await conn.execute(
                f"SELECT document FROM payment_checkouts WHERE {column} = %s", (value,)
            )
            row = await cursor.fetchone()
        return CheckoutDraft.model_validate_json(row[0]) if row else None

    async def get_by_token_hash(self, token_hash: str):
        return await self._get("token_hash", token_hash)

    async def get_by_order_id(self, order_id: str):
        return await self._get("paypal_order_id", order_id)

    async def update(self, draft: CheckoutDraft, expected_version: int):
        from psycopg.errors import UniqueViolation

        updated = draft.model_copy(
            update={
                "version": expected_version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        try:
            async with await self.connection.connect(self.dsn) as conn:
                cursor = await conn.execute(
                    "UPDATE payment_checkouts SET paypal_order_id=%s, version=%s, document=%s "
                    "WHERE checkout_id=%s AND version=%s",
                    (
                        updated.paypal_order_id,
                        updated.version,
                        updated.model_dump_json(),
                        updated.checkout_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise PaymentConflict("Checkout changed; retry the operation")
        except UniqueViolation as error:
            raise PaymentConflict("PayPal order is already attached") from error
        return updated

    async def record_webhook(self, event_id: str, event_type: str):
        async with await self.connection.connect(self.dsn) as conn:
            cursor = await conn.execute(
                "INSERT INTO payment_webhooks VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (event_id, event_type, datetime.now(UTC).isoformat()),
            )
            return cursor.rowcount == 1

    async def forget_webhook(self, event_id: str):
        async with await self.connection.connect(self.dsn) as conn:
            await conn.execute("DELETE FROM payment_webhooks WHERE event_id=%s", (event_id,))

    async def completed(self, merchant_id: str, user_id: str | None = None):
        async with await self.connection.connect(self.dsn) as conn:
            cursor = await conn.execute(
                "SELECT document FROM payment_checkouts WHERE "
                "document::jsonb->>'status'='completed' AND "
                "COALESCE(document::jsonb->>'merchant_id', 'default')=%s AND "
                "(%s::text IS NULL OR document::jsonb->>'user_id'=%s)",
                (merchant_id, user_id, user_id),
            )
            rows = await cursor.fetchall()
        return [CheckoutDraft.model_validate_json(row[0]) for row in rows]

    async def commit_webhook(self, event_id, event_type, draft):
        async with await self.connection.connect(self.dsn) as conn:
            cursor = await conn.execute(
                "INSERT INTO payment_webhooks VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (event_id, event_type, datetime.now(UTC).isoformat()),
            )
            if cursor.rowcount == 0:
                return False
            if draft:
                updated = draft.model_copy(
                    update={"version": draft.version + 1, "updated_at": datetime.now(UTC)}
                )
                cursor = await conn.execute(
                    "UPDATE payment_checkouts SET document=%s, version=%s "
                    "WHERE checkout_id=%s AND version=%s",
                    (updated.model_dump_json(), updated.version, draft.checkout_id, draft.version),
                )
                if cursor.rowcount != 1:
                    raise PaymentConflict("Checkout changed; retry the webhook")
            return True
