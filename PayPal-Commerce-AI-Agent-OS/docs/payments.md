# PayPal payments

PayPal checkout is **on by default**: `scripts/run_demo.py` enables it whenever
`PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are present, prints a loud warning when they
are missing, and offers `--no-paypal` as the explicit offline mode (it sets
`COMMERCE_PAYPAL_DISABLED=1` and clears the credentials for the API process). There is no
second opt-in. Only sandbox credentials are accepted by the demo host; live mode is refused.

PayPal is also inside the agent loop. The built-in `create_paypal_order` tool lets the model
prepare a real Orders v2 order behind the catalog provenance gate and a spend cap. It is
registered in the tool registry, both agent runtimes, and the storefront MCP server. The
model supplies **only** `product_ids` and `max_amount`; prices, quantities, currency, the
immutable snapshot, and the PayPal API call are all host-owned. The tool creates an order,
never captures money, and its checkout URL goes to the customer's UI card rather than into
model context. Set `enable_agentic_payments=False` (or `enable_cart=False`) to remove it.

## Bounded auto-buy

A shopper names the items and a maximum total; the agent calls `create_paypal_order` with
that cap. Three independent limits apply:

1. The tool clamps the model-supplied cap to `MAX_AGENT_ORDER_CAP` (10,000.00) and rejects
   non-positive or non-finite caps.
2. `CheckoutService.effective_cap()` clamps it again to the host ceiling from
   `COMMERCE_MAX_ORDER_AMOUNT`.
3. `SpendCapExceeded` is raised *before* any payment row is written if the server-priced
   cart total exceeds the effective cap, and `assert_within_cap()` re-checks the immutable
   draft before the provider call.

The effective cap, cart hash and PayPal order id are persisted on the `CheckoutDraft` and
rendered as a visible receipt on both the hosted checkout page and the in-chat checkout
card. The customer still approves on PayPal's page; nothing is charged by the agent.

## Flow

1. The shopping agent renders checkout after reading the current cart, or prepares a
   bounded order through `create_paypal_order`.
2. The host snapshots the cart, hashes an opaque bearer token, and persists the quote.
3. The customer opens the handoff URL. The host page loads PayPal's JavaScript SDK.
4. The page asks the host to create an Orders v2 order. The server exchanges its client
   credentials for OAuth, sends the exact snapshot, and uses `PayPal-Request-Id`.
5. PayPal collects payment details and returns buyer approval to its SDK.
6. The host captures the matching order with another deterministic idempotency key.
7. A completed response is accepted only when its amount and currency equal the snapshot.
8. Signed webhooks reconcile provider-side events and are deduplicated by event id.
9. Completed checkout rows act as a transactional outbox. A background worker finalizes
   the commerce order with the checkout id as its idempotency key. Failures retain the
   paid state and retry with backoff; they never issue another charge.
10. The checkout page distinguishes payment received from order confirmed. Persistent
    receipts populate order reads and queue an application event before the next chat turn.

The implementation is in `commerce_common/payments.py`; the example FastAPI routes and
hosted checkout page are in `examples/demo_common/payments.py`.

For the selected WooCommerce integration, use [the native checkout guide](woocommerce.md).
WooCommerce creates its own order as part of checkout; the agent host never duplicates it.
The direct PayPal flow below remains useful for custom carts and sandbox examples.

## Durable state and recovery

Set `COMMERCE_PAYMENT_DATABASE_URL` to a PostgreSQL DSN and install
`pip install -e './commerce-common[payments]'` to use `PostgresPaymentStore`. The example
host initializes its tables at startup; a production deployment should call `initialize()`
as a migration and use a runtime database role without DDL privileges. With no DSN, the
existing SQLite store remains the local default.

Both stores atomically commit webhook deduplication and checkout state. A verified
`PAYMENT.CAPTURE.COMPLETED` can recover a lost capture response, but must match the recorded
order, amount, currency and capture id. Delayed approval events cannot downgrade payment.
Finalization leases use optimistic concurrency across workers. Remote order creation must
deduplicate the supplied checkout id, including the case where the remote call succeeds
but its response is lost. The demo finalizer projects the immutable snapshot as a persistent
processing order; it does not send goods or update a real warehouse.

An authenticated custom-cart host supplies an `OrderFinalizer` and calls
`drain_finalizations(service, finalizer)` continuously. A real finalizer must return the
same commerce order id for every retry of a checkout. The example host refuses direct
live PayPal payments because its snapshot does not calculate final shipping and tax.

## Multiple sellers and onboarding

`commerce_common.paypal_partners.PayPalPartners` implements Partner Referrals onboarding.
It creates a seller signup link only after explicit data-sharing consent, resolves seller
identity server-side using a stable HMAC tracking id, and checks the account's payment
eligibility, confirmed email and granted payment permissions. Browser callback query
parameters never authorize a seller.

`examples/demo_common/onboarding.py` supplies `/api/merchant/paypal/connect` and `/status`
routes that require the host to inject its authenticated merchant dependency. They are
intentionally not mounted on the unauthenticated demo portal. Construct `PayPalPartners`
with the partner app's `PayPalConfig`, `PAYPAL_PARTNER_MERCHANT_ID`, stable
`PAYPAL_TRACKING_SECRET`, and `PAYPAL_ONBOARDING_RETURN_URL`.

For each authenticated tenant, call `checkout_service(merchant_id, store)` to resolve the
verified seller and create an isolated service over a shared payment store. Orders specify
the seller payee and PayPal auth assertion; the JavaScript SDK receives the seller merchant
id. PayPal still enforces granted permissions on payment calls. Refresh seller authorization
when opening a new merchant payment session; permission revocation must not be cached forever.
This requires PayPal partner access and is distinct from consumer “Log in with PayPal.”
See [PayPal seller onboarding](https://developer.paypal.com/platforms/seller-onboarding/before-payment).

## Sandbox setup

Create a PayPal REST application and put its sandbox credentials in the root `.env`:

```dotenv
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_CLIENT_SECRET=your-sandbox-secret
PAYPAL_ENVIRONMENT=sandbox
PAYPAL_WEBHOOK_ID=your-webhook-id
PAYPAL_BRAND_NAME=ACME
# Server-side hard ceiling for bounded auto-buy; a shopper's cap can only tighten it.
COMMERCE_MAX_ORDER_AMOUNT=250.00
```

`scripts/run_demo.py` supplies `COMMERCE_PUBLIC_API_URL` automatically:

```bash
python scripts/run_demo.py retail          # PayPal sandbox checkout enabled
python scripts/run_demo.py retail --no-paypal   # explicit offline mode, no PayPal calls
```

Ask the assistant to add an item and check out, or to buy named items within a stated cap so
it calls `create_paypal_order`. The checkout card links to the host's PayPal page and shows
the authorized cap, immutable snapshot hash, and PayPal order id. Direct `uvicorn` runs must
set an absolute public API URL themselves, for example
`COMMERCE_PUBLIC_API_URL=http://localhost:8000` during local sandbox development.

## Recorded sandbox proof

`scripts/demo_paypal_order.py` records a genuine sandbox transaction on the production
code path: `create → buyer approve → capture → webhook → order status`. It reads the
provider's own order status through `PayPalClient.get_order()` after capture, verifies a
real signed webhook with `service.process_webhook()`, and writes
`proof/sandbox-transaction.json` plus `SANDBOX-PROOF.md`.

```bash
python scripts/demo_paypal_order.py --check       # config only, no network
python scripts/demo_paypal_order.py               # real sandbox order
python scripts/demo_paypal_order.py --proof-only  # rebuild the markdown from recorded files
```

The script refuses `PAYPAL_ENVIRONMENT=live`, never invents an order id, capture id, webhook
event, screenshot or credential, and writes `NOT RECORDED` for any step that did not
actually happen. Screenshots belong in `proof/screenshots/`. The checked-in
`SANDBOX-PROOF.md` is the honest pre-run state until a run with real credentials completes;
it also carries the checklist for judge sandbox credentials, which must be supplied by the
submitter in the Devpost testing instructions, never committed to this repository.

## Webhooks

Register this HTTPS endpoint on the same PayPal REST application:

```text
https://your-api.example/api/payments/paypal/webhook
```

Set the resulting webhook id as `PAYPAL_WEBHOOK_ID`. Without it, the endpoint refuses every
event. The listener posts the PayPal transmission headers and event back to PayPal's signature
verification endpoint before it changes local state. Subscribe at least to:

- `CHECKOUT.ORDER.APPROVED`
- `PAYMENT.CAPTURE.COMPLETED`
- `PAYMENT.CAPTURE.DENIED`
- `PAYMENT.CAPTURE.REFUNDED`

PayPal retries non-2xx webhook deliveries. The handler returns an error for invalid signatures
or failed reconciliation and records an event id only while processing succeeds.

Official references: [OAuth authentication](https://developer.paypal.com/api/rest/authentication),
[Orders v2](https://developer.paypal.com/api/rest/integration/orders-api), and
[webhook verification](https://developer.paypal.com/api/rest/webhooks/rest/).

## Going live

Before `PAYPAL_ENVIRONMENT=live`:

- Replace the demo identity and public routes with real authentication and tenant authorization.
- Configure and back up the shared PostgreSQL store.
- Produce the final payable quote from a server-side pricing service. Include shipping, tax,
  discounts, and reservation expiry rather than assuming the cart subtotal is final.
- Supply the store-specific idempotent `OrderFinalizer` to the included outbox worker,
  and reconcile captures against orders continuously.
- Add refund, dispute, fraud, and fulfillment workflows with separate permissions.
- Terminate TLS at an authenticating gateway, rate-limit all payment routes, and retain audit
  records according to legal and privacy requirements.
- Use a secrets manager, rotate credentials, and never enable request-body debug logging on
  payment infrastructure.
- Complete PayPal's launch, account, and regional compliance requirements for the merchant.

The reference database stores checkout lines, totals, PayPal order/capture ids, and state. It
does not store access tokens, PayPal secrets, funding credentials, or payer identity.
