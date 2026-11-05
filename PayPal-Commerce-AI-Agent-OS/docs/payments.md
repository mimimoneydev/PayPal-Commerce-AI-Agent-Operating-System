# PayPal payments

PayPal checkout is an optional host capability. It is disabled unless both
`PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are present. The agent's `checkout` tool still
charges nothing: it renders a host-authored link to a short-lived checkout snapshot.

## Flow

1. The shopping agent renders checkout after reading the current cart.
2. The host snapshots the cart, hashes an opaque bearer token, and persists the quote.
3. The customer opens the handoff URL. The host page loads PayPal's JavaScript SDK.
4. The page asks the host to create an Orders v2 order. The server exchanges its client
   credentials for OAuth, sends the exact snapshot, and uses `PayPal-Request-Id`.
5. PayPal collects payment details and returns buyer approval to its SDK.
6. The host captures the matching order with another deterministic idempotency key.
7. A completed response is accepted only when its amount and currency equal the snapshot.
8. Signed webhooks reconcile provider-side events and are deduplicated by event id.

The implementation is in `commerce_common/payments.py`; the reference FastAPI routes and
hosted checkout page are in `examples/demo_common/payments.py`.

## Sandbox setup

Create a PayPal REST application and put its sandbox credentials in the root `.env`:

```dotenv
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_CLIENT_SECRET=your-sandbox-secret
PAYPAL_ENVIRONMENT=sandbox
PAYPAL_BRAND_NAME=ACME
```

`scripts/run_demo.py` supplies `COMMERCE_PUBLIC_API_URL` automatically:

```bash
python scripts/run_demo.py retail
```

Ask the assistant to add an item and check out. The checkout card now links to the host's
PayPal page. Direct `uvicorn` runs must set an absolute public API URL themselves, for example
`COMMERCE_PUBLIC_API_URL=http://localhost:8000` during local sandbox development.

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
- Replace SQLite with a backed-up transactional store shared by all API workers.
- Produce the final payable quote from a server-side pricing service. Include shipping, tax,
  discounts, and reservation expiry rather than assuming the cart subtotal is final.
- Create the commerce order through an idempotent outbox after capture, and reconcile captures
  against orders continuously.
- Add refund, dispute, fraud, and fulfillment workflows with separate permissions.
- Terminate TLS at an authenticating gateway, rate-limit all payment routes, and retain audit
  records according to legal and privacy requirements.
- Use a secrets manager, rotate credentials, and never enable request-body debug logging on
  payment infrastructure.
- Complete PayPal's launch, account, and regional compliance requirements for the merchant.

The reference database stores checkout lines, totals, PayPal order/capture ids, and state. It
does not store access tokens, PayPal secrets, funding credentials, or payer identity.
