import base64
import json

import httpx
import pytest

from commerce_common.payments import (
    CheckoutService,
    PaymentError,
    PaymentItem,
    PayPalClient,
    PayPalConfig,
    SQLitePaymentStore,
)
from commerce_common.paypal_partners import PayPalPartners


async def test_seller_verified_server_side_and_payment_names_verified_payee(tmp_path):
    seen = []
    consent = {"active": True}

    def handler(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        if path.endswith("/partner-referrals"):
            body = json.loads(request.content)
            assert body["tracking_id"] == partners.tracking_id("tenant")
            return httpx.Response(
                201,
                json={
                    "links": [
                        {"rel": "action_url", "href": "https://www.sandbox.paypal.com/connect"}
                    ]
                },
            )
        if path.endswith("/merchant-integrations"):
            assert request.url.params["tracking_id"] == partners.tracking_id("tenant")
            return httpx.Response(200, json={"merchant_id": "SELLER"})
        if path.endswith("/SELLER"):
            return httpx.Response(
                200,
                json={
                    "merchant_id": "SELLER",
                    "tracking_id": partners.tracking_id("tenant"),
                    "payments_receivable": consent["active"],
                    "primary_email_confirmed": True,
                    "oauth_integrations": [
                        {
                            "oauth_third_party": [
                                {
                                    "partner_client_id": "client",
                                    "scopes": [
                                        "https://uri.paypal.com/services/payments/payment/authcapture"
                                    ],
                                }
                            ]
                        }
                    ],
                },
            )
        if path.endswith("/orders"):
            body = json.loads(request.content)
            assert body["purchase_units"][0]["payee"] == {"merchant_id": "SELLER"}
            assertion = request.headers["PayPal-Auth-Assertion"].split(".")[1]
            assert json.loads(
                base64.urlsafe_b64decode(assertion + "=" * (-len(assertion) % 4))
            ) == {"iss": "client", "payer_id": "SELLER"}
            return httpx.Response(201, json={"id": "ORDER", "status": "CREATED"})
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        config = PayPalConfig(
            client_id="client", client_secret="secret", partner_attribution_id="BN"
        )
        partners = PayPalPartners(
            config, "PARTNER", "tracking-secret" * 4, "https://app.test/return", client=http
        )
        with pytest.raises(PaymentError):
            await partners.start("tenant", data_sharing_consent=False)
        assert not seen
        await partners.start("tenant", data_sharing_consent=True)
        seller_config = await partners.seller_config("tenant")
        service = CheckoutService(
            SQLitePaymentStore(tmp_path / "payments.db"),
            PayPalClient(seller_config, http),
            "tenant",
        )
        _, token = await service.create_checkout(
            session_id="s",
            user_id="u",
            currency="USD",
            items=[PaymentItem(product_id="sku", name="Item", quantity=1, unit_amount=10)],
        )
        await service.create_order(token)
        consent["active"] = False
        with pytest.raises(PaymentError):
            await partners.seller_config("tenant")
