"""PayPal Partner Referrals onboarding for authenticated multi-merchant hosts.

This is seller permission onboarding, not 'Log in with PayPal'. The caller must
derive merchant_id from its authenticated operator, never from model tool arguments.
WooCommerce-native checkout uses the WooCommerce PayPal plugin's onboarding instead.
"""

import hashlib
import hmac
from urllib.parse import quote, urlsplit

from .payments import CheckoutService, PaymentError, PayPalClient, PayPalConfig


class PayPalPartners:
    def __init__(
        self,
        config: PayPalConfig,
        partner_merchant_id: str,
        tracking_secret: str,
        return_url: str,
        *,
        client=None,
    ):
        if len(tracking_secret) < 32 or urlsplit(return_url).scheme != "https":
            raise ValueError(
                "A stable 32+ character tracking secret and HTTPS return URL are required"
            )
        self.provider = PayPalClient(config, client)
        self.partner_id = partner_merchant_id
        self.tracking_secret, self.return_url = tracking_secret, return_url

    def tracking_id(self, merchant_id: str):
        return hmac.new(
            self.tracking_secret.encode(), merchant_id.encode(), hashlib.sha256
        ).hexdigest()

    async def start(self, merchant_id: str, *, data_sharing_consent: bool) -> str:
        if not data_sharing_consent:
            raise PaymentError("The merchant must consent to sharing data with PayPal")
        data = await self.provider._post(
            "/v2/customer/partner-referrals",
            {
                "tracking_id": self.tracking_id(merchant_id),
                "operations": [
                    {
                        "operation": "API_INTEGRATION",
                        "api_integration_preference": {
                            "rest_api_integration": {
                                "integration_method": "PAYPAL",
                                "integration_type": "THIRD_PARTY",
                                "third_party_details": {"features": ["PAYMENT", "REFUND"]},
                            },
                        },
                    }
                ],
                "products": ["EXPRESS_CHECKOUT"],
                "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}],
                "partner_config_override": {"return_url": self.return_url},
            },
            "seller onboarding",
        )
        link = next(
            (
                entry.get("href")
                for entry in data.get("links", [])
                if entry.get("rel") == "action_url"
            ),
            None,
        )
        parsed = urlsplit(link or "")
        if parsed.scheme != "https" or parsed.hostname not in {
            "www.paypal.com",
            "www.sandbox.paypal.com",
        }:
            raise PaymentError("PayPal returned no valid onboarding link")
        return link

    async def _get(self, suffix, params=None):
        p = self.provider
        response = await p._client.get(
            f"{p.config.base_url}/v1/customer/partners/{quote(self.partner_id, safe='')}/merchant-integrations{suffix}",
            params=params,
            headers={
                "Authorization": f"Bearer {await p._token()}",
                "PayPal-Partner-Attribution-Id": p.config.partner_attribution_id or "",
            },
        )
        data = p._json(response)
        if response.is_error:
            p._raise_provider("seller status", response, data)
        return data

    async def seller_config(self, merchant_id: str) -> PayPalConfig:
        # Do not trust merchantIdInPayPal, permissionsGranted, or consentStatus from
        # a browser redirect. Resolve the seller using our server-generated tracking id.
        tracking = self.tracking_id(merchant_id)
        found = await self._get("", {"tracking_id": tracking})
        seller = found.get("merchant_id")
        if not seller:
            raise PaymentError("Seller onboarding is not complete")
        status = await self._get("/" + quote(seller, safe=""))
        permissions = [
            permission
            for integration in status.get("oauth_integrations", [])
            for permission in integration.get("oauth_third_party", [])
            if permission.get("partner_client_id") == self.provider.config.client_id
        ]
        scopes = {scope for permission in permissions for scope in permission.get("scopes", [])}
        if (
            status.get("merchant_id") != seller
            or status.get("tracking_id") != tracking
            or status.get("payments_receivable") is not True
            or status.get("primary_email_confirmed") is not True
            or "https://uri.paypal.com/services/payments/payment/authcapture" not in scopes
        ):
            raise PaymentError("Seller is not authorized to receive payments")
        return self.provider.config.model_copy(update={"seller_merchant_id": seller})

    async def checkout_service(self, merchant_id: str, store) -> CheckoutService:
        # Resolve again when opening a merchant payment session, so revoked permission
        # cannot remain indefinitely cached. Money always names the verified payee.
        config = await self.seller_config(merchant_id)
        return CheckoutService(store, PayPalClient(config), merchant_id)
