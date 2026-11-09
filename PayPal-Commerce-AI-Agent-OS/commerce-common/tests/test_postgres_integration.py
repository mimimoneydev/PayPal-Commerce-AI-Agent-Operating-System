"""Opt-in real PostgreSQL protocol tests in an isolated disposable schema.

COMMERCE_TEST_POSTGRES_DSN must point to a TEST database with schema-create rights.
Never use the production DSN here. Only the uniquely generated test schema is dropped.
"""

import os
import uuid

import pytest
from cryptography.fernet import Fernet

from commerce_common.control_store import Conflict, ControlStore
from commerce_common.payment_store import PostgresPaymentStore
from commerce_common.payments import CheckoutDraft, CheckoutStatus, PaymentConflict, PaymentItem


@pytest.fixture
def postgres_schema():
    dsn = os.environ.get("COMMERCE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set COMMERCE_TEST_POSTGRES_DSN for infrastructure validation")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "commerce_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield make_conninfo(dsn, options=f"-c search_path={schema}")
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def test_postgres_capture_outbox_cas_and_webhook_atomicity(postgres_schema):
    store = PostgresPaymentStore(postgres_schema)
    await store.initialize()
    draft = CheckoutDraft(
        checkout_id="checkout",
        token_hash="token",
        session_id="session",
        user_id="buyer",
        merchant_id="merchant",
        cart_hash="hash",
        items=(PaymentItem(product_id="1", name="Item", unit_amount=10, quantity=1),),
        currency="USD",
        amount=10,
        paypal_order_id="order",
    )
    await store.create(draft)
    assert await store.get_by_order_id("order") == draft
    updated = await store.update(draft.model_copy(update={"status": CheckoutStatus.COMPLETED}), 0)
    with pytest.raises(PaymentConflict):
        await store.update(draft, 0)
    # Failed CAS must roll back the webhook dedupe insert, permitting redelivery.
    with pytest.raises(PaymentConflict):
        await store.commit_webhook("event", "capture", draft)
    assert await store.commit_webhook("event", "capture", updated)
    assert not await store.commit_webhook("event", "capture", updated)
    assert len(await store.completed("merchant", "buyer")) == 1
    assert not await store.completed("another-merchant")
    assert not await store.completed("merchant", "another-buyer")


def test_postgres_control_encryption_and_cas(postgres_schema):
    from psycopg.conninfo import conninfo_to_dict
    from sqlalchemy.engine import URL

    info = conninfo_to_dict(postgres_schema)
    url = URL.create(
        "postgresql+psycopg",
        username=info.get("user"),
        password=info.get("password"),
        host=info.get("host"),
        port=int(info.get("port", 5432)),
        database=info.get("dbname"),
        query={
            k: v for k, v in info.items() if k not in {"user", "password", "host", "port", "dbname"}
        },
    )
    store = ControlStore(url.render_as_string(hide_password=False), Fernet.generate_key().decode())
    try:
        store.save_secret("merchant", "connection", {"token": "private"})
        assert store.secret("merchant", "connection") == {"token": "private"}
        assert store.secret("other", "connection") is None
        row = store.put("merchant", "state", "id", {"value": 1})
        store.put("merchant", "state", "id", {"value": 2}, version=row["version"])
        with pytest.raises(Conflict):
            store.put("merchant", "state", "id", {"value": 3}, version=row["version"])
    finally:
        store.engine.dispose()
