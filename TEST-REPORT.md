# Full verification report — PayPal Commerce AI Agent OS

**Date:** 12 November 2026
**Scope:** the whole repository, using the real keys in
`PayPal-Commerce-AI-Agent-OS/.env` (values never printed or committed).
**Verdict:** the application, API, PayPal sandbox path, web UIs and both client
apps pass. Four real defects were found and fixed. One item remains blocked on
a sandbox **buyer** account (not a code defect).

---

## 1. Credentials used (names only)

`.env` is gitignored and was verified absent from the commit. Populated keys:

`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_MEMORY_MODEL`,
`CHANNEL3_API_KEY` + `CHANNEL3_BASE_URL`/limits,
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`,
`PAYPAL_ENVIRONMENT=sandbox`, `COMMERCE_MAX_ORDER_AMOUNT=250.00`,
`COMMERCE_PLATFORM=demo`, `COMMERCE_MERCHANT_ID=retail`,
`MERCHANT_MAX_TOKENS=4096` and the merchant iteration/time budgets,
`COMMERCE_CONTROL_DATABASE_URL`.

Empty (intentionally): `COMMERCE_MERCHANT_OPERATOR_TOKEN`,
`OPENROUTER_MERCHANT_MODEL`, AG Studio / Bryntum licences, WooCommerce / Shopify,
Partner Referrals.

## 2. Test matrix

| # | Check | Result |
|---|---|---|
| 1 | Full Python suite (`pytest -q`, workspace-local basetemp) | **1197 passed, 3 skipped, 0 failed** |
| 2 | `ruff check .` / `ruff format --check .` | clean, 252 files formatted |
| 3 | `scripts/check.py` | clean — README/agent tool/registry counts match |
| 4 | TypeScript `--noEmit` on `web-shared` + 8 Next.js apps | 9/9 OK |
| 5 | Production builds: retail storefront + retail merchant portal | both pass, `/icon.svg` + favicon generated |
| 6 | Local FastAPI host with real `.env` keys | `health` → `payments: "paypal"`, model `deepseek/deepseek-v4.1-flash`, Channel3 enabled |
| 7 | End-to-end API smoke (19 checks) | **19/19 passed** |
| 8 | Real PayPal sandbox OAuth / create / read-back / webhook verification | pass |
| 9 | `demo_paypal_order.py --resume-order` against a real order, twice | pass, honest partial proof both times |
| 10 | Chrome extension JS syntax + manifest + API contract | pass |
| 11 | Android app JS syntax + assets + APK present (65 KB) | pass |

### End-to-end API smoke (local server, real keys)

`GET /api/health`, `POST /api/session`, `POST /api/merchant/session`,
`GET /api/products`, `/api/cart`, `/api/orders`, `/api/memory`,
`/api/merchant/overview`, `/api/merchant/listings`, `/api/merchant/health`
— all HTTP 200 with real data (87 products, 5 orders, memory facts).

Merchant approval surface: bare `POST .../apply` → **403**; minted capability →
accepted; replay of the same capability → **403**. Unsigned webhook →
`400 Invalid PayPal webhook signature`.

Streaming chat through OpenRouter: shopping turn **11.5 s**, merchant turn
**28.9 s**, both `stop_reason=end_turn` — **no `max_tokens` truncation**.

## 3. Defects found and fixed

| # | Defect | Fix |
|---|---|---|
| 1 | A real `.env` broke `pytest` collection: demo modules load it at import time; PayPal credentials then required `COMMERCE_PUBLIC_API_URL` and crashed with `ValueError`. | Added a documented `COMMERCE_TESTING` switch to `load_demo_env()` and set it in the root `conftest.py`, so tests never read local credentials. Added `COMMERCE_PUBLIC_API_URL` to `.env.example` and the local `.env`, plus a regression test. |
| 2 | Under AI auto-approval a duplicate `apply_change` returned a soft note with no events; `change_action()` still reported `ok: true` and appended a **second** audit line. | `change_action()` now requires a `change_update` event before recording success; a no-op returns HTTP 400 with the real reason and no duplicate audit event. |
| 3 | Seven tests asserted the old pre-auto-approval behaviour (duplicate apply = error; capacity checked before staging). | Updated `contract.py` expectations indirectly via the route fix, and refreshed the travel / telecom / entertainment vertical tests to assert the intentional no-op and the stage-time apply. |
| 4 | `scripts/demo_paypal_order.py` crashed on its **first real run**: six `step(..., status=...)` calls shadowed `step()`'s own `status` parameter → `TypeError`. Also `--resume-order` failed on a second run with `PayPal order is already attached`. | Renamed the evidence field to `provider_status`; added an AST regression test that forbids `status=` in any `step()` call; made resume reuse/rotate the existing local quote instead of violating the unique `paypal_order_id` constraint. |

Also corrected: four new files carried a copied Anthropic copyright header; they now
carry the contributors header. Retained notices on genuinely derived files were left
intact for Apache-2.0 compliance. Two stale documents were rewritten to match reality
(`SANDBOX-PROOF.md`, Devpost/README statements about hosted credentials).

## 4. PayPal sandbox verification (real, nothing charged)

With the local `.env` app:

- OAuth token obtained from `https://api-m.sandbox.paypal.com`.
- Orders v2 create → **`4PB280312R3967053`**, `PAYER_ACTION_REQUIRED`, `10.00 USD`,
  immutable snapshot `co_n0KDXFq_fFMR-zPI2v4eJC7E`, cap `25.00`, ceiling `250.00`.
- `get_order` read-back confirmed status, amount and currency.
- `/v1/notifications/verify-webhook-signature` reached PayPal with a complete-but-fake
  signature and was correctly rejected — the verification path is live.
- `--resume-order 4PB280312R3967053 --amount 10.00 --currency USD --cap 25.00` was
  run twice; both wrote an honest partial proof with `buyer approval = NOT RECORDED`.

The earlier hosted order **`94818182GP238811W`** returns `INVALID_RESOURCE_ID` for
these credentials: PayPal scopes orders to the REST app that created it, so the hosted
demo uses a different client id/secret. It cannot be resumed with the local `.env`.

**Still blocked:** buyer approval in a sandbox **personal** account, capture, capture
id, a genuinely signed webhook delivery and screenshots. These require a buyer login
and a registered public tunnel — not something a script can invent.
`SANDBOX-PROOF.md` therefore remains `PENDING` and says so explicitly.

## 5. Chrome extension and Android app

Both clients were checked against the current API contract. Every endpoint they call
(`/api/health`, `/api/session`, `/api/chat`, `/api/products[/{id}]`, `/api/cart`,
`/api/cart/add`, `/api/orders`, `/api/memory` GET/PATCH/DELETE, `/api/reset`, and the
`/api/payments/paypal/checkout/<token>` handoff) exists in the live OpenAPI document.
All 8 client JS files pass `node --check`. The MV3 manifest is valid, with a pinned
extension id and `host_permissions` for `shop.mimi.money` plus local ports.

The new merchant approval capability only affects `/api/merchant/*`; neither client
calls those routes, so both remain compatible.

Existing evidence in `Chrome extension/TEST-REPORT.md` (BrowserOS, 14 flows + 10
verification checks, zero console/network errors) and
`Android App/TEST-REPORT.md` (emulator, 18/18 checks twice) was produced against the
live host on 11 November. A repeat real-browser run against the local API was started
but was interrupted before completion; it is listed as remaining work below.

## 6. Remaining work / limitations

- **Sandbox proof**: buyer approval + capture + signed webhook + screenshots.
- **Real-browser regression** for the Chrome extension and an emulator run for the
  Android app against this exact build (static + contract checks passed).
- **Fresh `deployment/` bundle**: not yet rebuilt. `deployment/` and
  `deployment.zip` are gitignored generated artifacts and are **not** in this commit.
- **Merchant latency** is functional (28.9 s, no truncation) but not fast. Setting
  `OPENROUTER_MERCHANT_MODEL` to a faster model is the remaining knob.
- Optional integrations without keys: AG Studio licence (trial warnings), Bryntum
  (retail vertical only), WooCommerce/Shopify adapters, Partner Referrals.
- No VPS deployment or service restart was performed.

## 7. Reproduce

```bash
cd PayPal-Commerce-AI-Agent-OS
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python scripts/check.py
COMMERCE_PUBLIC_API_URL=http://127.0.0.1:8000 \
  .venv/bin/python -m uvicorn retail.api.main:app --app-dir examples --port 8000
```

PayPal proof, once a sandbox buyer account is available:

```bash
python scripts/demo_paypal_order.py --check
python scripts/demo_paypal_order.py \
  --resume-order <REAL-ORDER-ID> --amount <amount> --currency USD --cap <cap>
```
