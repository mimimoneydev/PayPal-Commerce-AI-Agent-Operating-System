from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from commerce_common.payments import (
    CheckoutService,
    CheckoutStatus,
    PaymentConflict,
    PaymentItem,
    PaymentNotFound,
    PayPalConfig,
    PayPalOrder,
    SQLitePaymentStore,
    drain_finalizations,
)


class Provider:
    config = PayPalConfig(client_id="client", client_secret="secret")

    async def create_order(self, draft, request_id):
        return PayPalOrder(order_id="PP-1", status="CREATED")

    async def capture_order(self, order_id, request_id):
        return PayPalOrder(
            order_id=order_id,
            status="COMPLETED",
            capture_id="CAP-1",
            amount=Decimal("10.00"),
            currency="USD",
        )

    async def verify_webhook(self, headers, event):
        return True


async def setup_checkout(tmp_path):
    store = SQLitePaymentStore(tmp_path / "state.db")
    service = CheckoutService(store, Provider(), "merchant-1")
    _, token = await service.create_checkout(
        session_id="session",
        user_id="buyer",
        currency="USD",
        items=[PaymentItem(product_id="1", name="Test", unit_amount=10, quantity=1)],
    )
    await service.create_order(token)
    return service, token


def capture_event(value="10.00"):
    return {
        "id": "EV-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-1",
            "status": "COMPLETED",
            "amount": {"value": value, "currency_code": "USD"},
            "supplementary_data": {"related_ids": {"order_id": "PP-1"}},
        },
    }


async def test_lost_capture_response_recovers_and_approval_cannot_regress(tmp_path):
    service, token = await setup_checkout(tmp_path)
    processed, draft = await service.process_webhook({}, capture_event())
    assert processed and draft.status == CheckoutStatus.COMPLETED
    assert await service.process_webhook({}, capture_event()) == (False, None)
    await service.process_webhook(
        {}, {"id": "EV-2", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "PP-1"}}
    )
    assert (await service.require(token)).status == CheckoutStatus.COMPLETED


async def test_invalid_capture_does_not_poison_deduplication(tmp_path):
    service, _ = await setup_checkout(tmp_path)
    with pytest.raises(PaymentConflict):
        await service.process_webhook({}, capture_event("9.00"))
    assert (await service.process_webhook({}, capture_event()))[0]


async def test_store_commits_webhook_and_state_atomically(tmp_path):
    service, token = await setup_checkout(tmp_path)
    draft = await service.require(token)
    await service.store.update(draft, draft.version)
    with pytest.raises(PaymentConflict):
        await service.store.commit_webhook("atomic", "capture", draft)
    fresh = await service.require(token)
    assert await service.store.commit_webhook("atomic", "capture", fresh)


async def test_outbox_recovers_restart_and_remote_success_before_local_failure(tmp_path):
    service, token = await setup_checkout(tmp_path)
    await service.capture(token, "PP-1")
    remote = {}

    class Target:
        fail = True

        async def finalize(self, draft, key):
            remote.setdefault(key, "WC-42")
            if self.fail:
                self.fail = False
                raise TimeoutError("Remote committed but response lost")
            return remote[key]

    target = Target()
    assert await drain_finalizations(service, target) == 0
    draft = await service.require(token)
    await service.store.update(
        draft.model_copy(update={"retry_at": datetime.now(UTC) - timedelta(seconds=1)}),
        draft.version,
    )
    restarted = CheckoutService(SQLitePaymentStore(tmp_path / "state.db"), Provider(), "merchant-1")
    assert await drain_finalizations(restarted, target) == 1
    assert await drain_finalizations(service, target) == 0
    assert len(remote) == 1
    assert (await service.require(token)).commerce_order_id == "WC-42"


async def test_tenant_cannot_read_checkout_or_drain_other_orders(tmp_path):
    service, token = await setup_checkout(tmp_path)
    await service.capture(token, "PP-1")
    other = CheckoutService(service.store, Provider(), "other")
    with pytest.raises(PaymentNotFound):
        await other.require(token)
    assert await other.store.completed("other") == []
    assert await service.store.completed("merchant-1", "other-user") == []
