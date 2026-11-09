# Merchant administration and Shopify

The optional control service adds invitation-gated registration, owner/staff membership,
encrypted store credentials, connection checks, storefront publication, durable shopper
sessions, audit records, and permissioned operations. It is a working implementation,
not a claim of production certification.

## Setup

Install the repository packages, then the optional dependencies, and start the service:

```sh
pip install -e './commerce-common[platform,examples]'
uvicorn commerce_platform.app:from_env --factory --app-dir examples --env-file .env --host 127.0.0.1 --port 8100
```

Configure `.env` using `.env.example`:

- `COMMERCE_CONTROL_DATABASE_URL`: `sqlite:///commerce-control.db` locally, or
  `postgresql+psycopg://…` for shared persistence.
- `COMMERCE_ENCRYPTION_KEY`: a generated Fernet key. Preserve it across replicas/restarts,
  back it up separately and never commit it. Losing it loses access to stored credentials.
- `COMMERCE_ADMIN_ORIGIN`: the exact HTTPS browser origin.
- `COMMERCE_REGISTRATION_CODE`: a private random invitation code.
- `COMMERCE_ALLOWED_WOO_HOSTS`: operator-approved WooCommerce hostnames. Approve only trusted
  stores and enforce egress restrictions against private addresses and DNS rebinding.

Put HTTPS and rate limiting in front of the loopback service. Cookies are Secure, HttpOnly
and SameSite=Strict; HTTP-only browser deployment is intentionally unsupported. Origin,
CSRF token and membership are checked on administration writes. Add rate limits for login,
registration, shopper sessions and model calls. Password reset, MFA, email verification,
SSO and retention/deletion jobs are not included.

Open the administration origin, register using the invitation, sign in, create a merchant,
save and test its connection, then publish. Different stores require different merchants;
credential rotation cannot reassign old carts/orders. Team additions require a registered
email. Staff may inspect and stage operations; owners manage credentials, approve and execute.

The shopper page is `/shop/<merchant-id>` and API is `/stores/<merchant-id>/api`. Shoppers
converse, select products, add items and ask to check out. The assistant returns the store's
native checkout link. Returning to the tab refreshes receipts; the next conversation turn
receives payment/order confirmation. Sessions and transcripts survive API restarts. Guest
tokens are tab-scoped, not cross-device authentication. Long-term extracted agent memory
is not persisted by this control-service example.

## WooCommerce

Follow [WooCommerce setup](woocommerce.md), then enter its HTTPS origin and bridge secret
in administration. For optional refund/shipment execution, the store operator must also set:

```php
define('AGENT_COMMERCE_OPERATIONS_ENABLED', true);
```

This is off by default: upgrading the plugin does not silently grant refund authority.
Only paid assistant-attributed orders qualify. Refunds use `wc_create_refund` through the
installed gateway, which must support refunds. Remote operation IDs are persisted before
gateway calls; ambiguous results are not automatically refunded again.

## Shopify

For the retail example, set `COMMERCE_PLATFORM=shopify`, `SHOPIFY_URL`,
`SHOPIFY_STOREFRONT_TOKEN`, `SHOPIFY_WEBHOOK_SECRET`, and control-store settings.
For several merchants, enter credentials separately in administration. Use a public
Storefront API token (sent server-side) and publish products to its sales channel.
This is a token-based custom integration, not Shopify App Store OAuth installation.

Subscribe `orders/paid`, `orders/updated`, and `orders/cancelled` to
`https://<api-host>/webhooks/shopify/<merchant-id>` using the matching signing secret.
The handler verifies raw-body HMAC and shop domain, then matches the order's `cart_token`
against server-created carts. Customer-editable order notes do not establish ownership.
Configure webhook retry/alerting: a missing receipt is not permission to pay again.
Missed-webhook polling and order-history backfill are not included.

The adapter uses Shopify API `2026-04`, supports up to 100 cart lines and exposes at most
100 variants per product. Checkout URLs are restricted to the configured `myshopify.com`
hostname; custom checkout domains need an explicit allowlist extension. Native checkout
owns final tax, shipping, discounts and inventory. The assistant subtotal is not a final
quote. Configure PayPal using Shopify's supported payment settings.
See [Shopify's cart guide](https://shopify.dev/docs/storefronts/headless/building-with-the-storefront-api/cart/manage).

## Operations and boundaries

Actions are staged, approved using the displayed version, then explicitly executed.
Credential changes invalidate outstanding approvals. Completed operations return their
stored result without another provider call. `running`/`unknown` requires provider-side
investigation; no automatic retry or operator reconciliation UI is included. Never stage
a replacement refund merely because a request timed out.

- **Fraud:** manual hold/release/reject review with reasons and audit records. Shopify
  receipts start on hold. Shipments through this service require release. This is not
  fraud scoring, sanctions screening, or a hold on external warehouse automation.
- **Fulfillment:** WooCommerce tracking records and completion; Shopify Admin fulfillment
  creation for open fulfillment orders. Record only real shipments. These calls do not
  buy labels, book carriers or physically dispatch parcels. They never imply delivery.
  Multi-location/partial Shopify shipments may require Shopify Admin handling.
- **Refunds:** owner-approved WooCommerce gateway refunds. Shopify refunds remain in
  Shopify Admin; order webhooks update receipts and journal entries afterward.
- **Disputes:** PayPal evidence-note submission (`OTHER` evidence), only when PayPal exposes
  `provide_evidence`. Configure merchant-specific PayPal credentials with Disputes API access.
  No automatic claim acceptance, file evidence uploads, deadlines or resolution predictions.
- **Accounting:** immutable balanced gross-payment/refund journals and CSV export. Shopify
  uses signed webhooks; WooCommerce's owner-only sync button scans assistant-attributed
  paid orders in pages, including gateway-confirmed refunds. Repeat scans to discover updates.
  Currency minor units are explicit in `commerce_common/accounting.py`; unsupported units fail closed.
  This is a clearing/liability journal, not revenue recognition, tax returns, bank settlement
  reconciliation or an external ledger connector. Edited paid totals that disagree with a
  recorded journal require reconciliation.

See [Shopify fulfillment](https://shopify.dev/docs/api/admin-graphql/2026-04/mutations/fulfillmentCreate)
and [PayPal disputes](https://developer.paypal.com/api/disputes/). Store credentials are
field-encrypted; conversations and operational records are not. Use encrypted storage,
least-privilege DB roles, backups, key rotation, observability and compliance review.

## Infrastructure verification

Read-only connection checks (no carts, orders or payments):

```sh
python scripts/check_commerce_infrastructure.py woocommerce
python scripts/check_commerce_infrastructure.py postgres
```

Run database integration tests against a dedicated **test** database:

```sh
COMMERCE_TEST_POSTGRES_DSN='postgresql://…/commerce_test' pytest commerce-common/tests/test_postgres_integration.py -q
```

Tests create uniquely named schemas and remove only those schemas. They exercise CAS
conflicts, webhook transaction rollback/deduplication, tenant-filtered completed checkouts,
and encrypted control-store persistence. They passed locally against PGlite over its
PostgreSQL wire-protocol server, not a native PostgreSQL deployment. Replication, pooling,
network policy and backup recovery still need infrastructure-specific validation.

No live store/database credentials were available during implementation. Before release,
complete sandbox purchases on each target store: variant, coupon, final tax/shipping,
decline/cancel, exactly one payment/order, next-turn confirmation, refunds and tracking.
Test webhook redelivery/reordering, server restart and lost provider responses. Verify
scopes, TLS, migrations, egress and restore procedures. Mocks and PHP syntax checks do
not certify a live checkout.
