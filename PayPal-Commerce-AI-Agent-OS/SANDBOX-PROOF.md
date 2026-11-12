# PayPal sandbox transaction proof

> **STATUS: PENDING — a real sandbox order exists, but it has NOT been approved or captured.**
>
> Two genuine PayPal Orders v2 orders exist: one created through the hosted demo's agent
> loop and one created and verified with the credentials in this repository's local `.env`.
> **Neither has been buyer-approved, captured, or charged**, and no capture id, signed
> webhook delivery, or screenshot has been recorded. Every value below came from a live
> PayPal sandbox response or a live host response; nothing is invented. Once a sandbox
> buyer approves the local order, the resume command below makes
> `scripts/demo_paypal_order.py` overwrite this file with the complete proof.

_This checked-in copy is the honest pre-capture state. It is replaced only by
`scripts/demo_paypal_order.py`, which writes exclusively from live PayPal responses._

## Partial real evidence

### Order created by the hosted demo (different PayPal app)

These values came from the live `https://shop.mimi.money` demo through the agent loop.
They are recorded so the pending order is not lost, not as evidence of a completed payment.

- **PayPal order id:** `94818182GP238811W`
- **Provider status then:** `PAYER_ACTION_REQUIRED` (waiting for the sandbox buyer)
- **Amount:** `219.00 USD` · **Effective spend cap:** `250.00 USD`
- **Approval URL:** `https://www.sandbox.paypal.com/checkoutnow?token=94818182GP238811W`
- **Cart snapshot hash:** `054314534b3b66dbc951d072155885b8b325335db109df160c76a308f2e295e4`
- **Hosted checkout token:** `zZJc5PEaiw3JqYO3TwGbQcomfdFLKizDrN4O1nstEqU`
- **Hosted checkout draft:** expired — `GET /api/payments/paypal/checkout/<token>/status`
  returns `404 {"detail":"Checkout expired"}`.
- **Current status:** `GET /v2/checkout/orders/94818182GP238811W` with the credentials in
  this repository's local `.env` returns `INVALID_RESOURCE_ID`. PayPal scopes orders to
  the REST app that created them, so the hosted demo used a different client id/secret.
  **This order cannot be resumed with the local credentials.**

### Order created and verified with the local `.env` credentials (12 Nov 2026)

- **PayPal order id:** `4PB280312R3967053`
- **Provider status:** `PAYER_ACTION_REQUIRED` (read back from PayPal)
- **Amount / currency:** `10.00 USD` (verified against the provider's own purchase unit)
- **Immutable snapshot:** `co_n0KDXFq_fFMR-zPI2v4eJC7E`,
  `cart_hash=377fb5a1d59675d0…`, shopper cap `25.00`, host ceiling `250.00`
- **Approval URL:** `https://www.sandbox.paypal.com/checkoutnow?token=4PB280312R3967053`
- **Verified live:** OAuth token, Orders v2 create, `get_order` read-back, and
  `/v1/notifications/verify-webhook-signature` (a complete-but-fake signature reached
  PayPal and was rejected, proving the path is wired to the real endpoint).
- **`--resume-order 4PB280312R3967053` was run twice.** Both runs read the provider's
  real amount/currency, refused to create a duplicate order, and wrote an honest partial
  proof with `buyer approval = NOT RECORDED`. The second run reused the existing local
  quote instead of failing on the unique `paypal_order_id` constraint.
- **Still missing:** buyer approval in a sandbox **personal** account, capture,
  capture id, a genuinely signed webhook delivery, and screenshots.

## Environment

- **API base:** `https://api-m.sandbox.paypal.com` (sandbox credentials are configured on
  the host, not in this repository; see the credentials section below)
- **Webhook id configured:** yes on the host (`PAYPAL_WEBHOOK_ID`); unsigned test events
  were correctly rejected and complete-but-fake signatures reached PayPal's real
  verification endpoint. No genuine signed delivery has been recorded.
- **Spend cap:** `25.00 USD` (local resume run) · **Host ceiling:** `250.00 USD`
- **Model / payments (local API with `.env`):** `deepseek/deepseek-v4.1-flash`, `payments: "paypal"`, Channel3 enabled

## Recorded steps

| Step | Status | Evidence |
| --- | --- | --- |
| immutable snapshot | RECORDED (local `.env`) | `checkout_id=co_n0KDXFq_fFMR-zPI2v4eJC7E`, `amount=10.00 USD` |
| create Orders v2 order | RECORDED (local `.env`) | `paypal_order_id=4PB280312R3967053`, `provider_status=PAYER_ACTION_REQUIRED` |
| resume existing order | RECORDED (twice, idempotent) | `paypal_order_id=4PB280312R3967053`, `amount=10.00 USD` |
| buyer approval | NOT RECORDED | — |
| capture | NOT RECORDED | — |
| signed webhook | NOT RECORDED | — |
| provider order status | RECORDED (pre-capture read-back) | `paypal_order_id=4PB280312R3967053`, `provider_status=PAYER_ACTION_REQUIRED` |
| host order status | NOT RECORDED | — |

A complete proof exercises
`create → buyer approve → capture → webhook → order status`, using `PayPalClient`
(`commerce_common/payments.py`) with OAuth, `PayPal-Request-Id` idempotency, immutable cart
snapshots, amount/currency equality checks, and signature verification through
`/v1/notifications/verify-webhook-signature`.

## Screenshots

**NOT RECORDED.** No files in `proof/screenshots/`. Capture these during the run, drop them
in that directory, then re-run with `--proof-only` to refresh this file before publishing:

1. The PayPal approval page showing the sandbox buyer and the amount.
2. The hosted checkout page showing the authorized cap and PayPal order id.
3. The captured state: provider status `COMPLETED` and the capture id.
4. The chat turn where `create_paypal_order` is called behind the provenance gate.

## Judge sandbox credentials

**NOT RECORDED — this is an action for the submitter.** PayPal credentials belong to a
PayPal Developer account; a script cannot create them and guessing them would be a
fabrication. Before submitting to Devpost:

1. In the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/), create a
   dedicated sandbox **business** app for judges and a sandbox **personal** buyer account.
   Copy the app's sandbox client id and secret.
2. Put the sandbox client id / secret, `PAYPAL_ENVIRONMENT=sandbox`, `PAYPAL_WEBHOOK_ID`,
   and the buyer account's email + password in the Devpost *Testing Instructions* field
   (or a password-protected gist linked there). **Never commit them to this repository.**
3. Add the HTTPS tunnel URL for the script's webhook listener to the app's webhook
   subscriptions: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`,
   `PAYMENT.CAPTURE.DENIED`.
4. Verify the buyer account has a sandbox balance before judging day.

## Reproduce

```bash
cp .env.example .env   # fill PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET
export PAYPAL_ENVIRONMENT=sandbox
python scripts/demo_paypal_order.py --check
python scripts/demo_paypal_order.py
python scripts/run_demo.py retail   # PayPal is on by default
```

To finish the **existing** local order rather than creating a second one, approve it first
with the sandbox buyer account, then:

```bash
python scripts/demo_paypal_order.py \
  --resume-order 4PB280312R3967053 --amount 10.00 --currency USD --cap 25.00
```

`--cap` must be at least the order amount: the script refuses to bind a quote whose cap
is below the real order. Running this twice is safe — it reuses the local quote and
never creates a duplicate PayPal order or a second capture.

> The hosted demo's `94818182GP238811W` order belongs to a **different** PayPal REST app
> and returns `INVALID_RESOURCE_ID` for these credentials. Do not use
> `--resume-order 94818182GP238811W` with the local `.env`; use the app that created it.

`--resume-order` reads the provider's own purchase unit and refuses to bind a snapshot
whose amount or currency differs; it never creates a duplicate order and never POSTs
`/capture` twice. Add `--webhook-event proof/webhook-events.jsonl` to reconcile genuinely
signed events captured from a tunnel.

`--no-paypal` is the explicit offline switch. The machine-readable record is written to
`proof/sandbox-transaction.json`; the script refuses `PAYPAL_ENVIRONMENT=live` and never
writes a success for a step that did not happen.
