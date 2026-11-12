# Devpost form answers — PayPal Commerce AI Agent OS

**How to use:** each `##` section below is paste-ready for the matching Devpost field.
The first two blocks under **What it does** give the project in brief and in detail.
A compact tools list for the Devpost *tools/technologies* field is at the end.

> Prefer a warmer, more natural voice? Use
> [`DEVPOST-SUBMISSION-HUMAN.md`](DEVPOST-SUBMISSION-HUMAN.md) instead — same facts, written
> as people rather than as a spec sheet, with a phased implementable roadmap at the bottom.
> This file is the technical reference with exact identifiers and test counts.

**Evidence discipline:** every number, id and URL here is real and verifiable in this
repository. No completed PayPal transaction is claimed — two genuine sandbox orders exist,
both still `PAYER_ACTION_REQUIRED`. `SANDBOX-PROOF.md` and `TEST-REPORT.md` are the sources.

---

## Inspiration

Almost every agentic-commerce demo we studied stopped one step short of the interesting
part: it could search, compare and fill a cart, then handed the human a checkout link. The
moment an agent is allowed to spend money, two questions arrive together — can it prove it
bought *only* what the shopper named, and can it prove it stayed inside the amount the
shopper authorized? Giving a language model a payment credential answers neither.

We started from the opposite framing: treat the payment last mile as the product, and design
the boundary first. If the model owns conversation and tool choice while the host owns
identity, prices, credentials and durable state, delegation becomes auditable instead of
merely convenient. **PayPal Sandbox became the centre of gravity of the whole project**, not
a final integration: Orders v2, the JavaScript SDK, webhook signature verification and a
real sandbox app gave us a live, testable payment rail to build every guardrail against,
rather than a mocked "purchase" that proves nothing. Every architectural decision — the
immutable cart snapshot, the provenance gate, the three cap layers, the idempotency keys,
the transactional outbox — exists because a real sandbox order will punish you for getting
it wrong.

That boundary turned out to be portable. Once the money authority lived entirely in the
host, the same governed API could serve a Next.js storefront, a Chrome extension and an
Android app without any of them ever holding a credential. The result is a question we think
the whole category needs answered: what is the smallest authority an agent actually needs
to finish a checkout — and how do you prove it stayed there?

## What it does

**In brief.** PayPal Commerce AI Agent OS is an open-source commerce operating system in
which an AI shopping agent can prepare a *real* PayPal sandbox order — but only for items a
catalog tool actually returned this session, only below a shopper-authorized cap, and never
with a payment credential in the model's context. A governed merchant agent runs beside it
on the same safety kernel. The same auditable API powers eight Next.js apps across four
verticals, a Chrome extension and a native Android app.

**In detail.** Two agents — a customer-facing **shopping agent** and a governed **merchant
agent** — are each defined once as prompt + skills + tool contracts + gates, and run on
three runtimes (Messages API, Agent SDK, Managed Agents). PayPal is a first-class tool
*inside* the loop, not a redirect. When a shopper names items and a maximum total, the
built-in `create_paypal_order` tool prepares a real, cap-bounded Orders v2 order. The model
supplies only `product_ids` and `max_amount`; the host re-reads its own catalog for prices,
quantities and currency, freezes an immutable hashed cart snapshot, and calls PayPal with
server-held credentials. Three independent limits apply: the tool clamps the model's cap to
a fixed maximum, `CheckoutService` clamps it again to the deployment ceiling
(`COMMERCE_MAX_ORDER_AMOUNT`, `250.00 USD` here), and an over-cap cart is refused *before
any payment row exists*. A provenance gate rejects any `product_id` that a catalog or order
tool did not return in that session.

The output is a visible receipt — authorized cap, snapshot hash, PayPal order id — on the
hosted checkout page and in the in-chat card. **The agent creates an order; it never
captures.** The buyer approves on PayPal's own page, and the host captures, verifies webhook
signatures, deduplicates events by id and reconciles provider status. On the merchant side,
writes are staged, guardrail-checked and previewed; a single-use, session-bound approval
capability is minted for a preview-card click, so a bare `POST .../apply` cannot move
merchant state.

**PayPal Sandbox is the project's test bench and its proof standard.** With real sandbox
credentials the host reports `"payments": "paypal"`, the checkout page renders the PayPal
JavaScript SDK with the amount, cap and snapshot hash, and `scripts/demo_paypal_order.py`
drives `create → buyer approve → capture → signed webhook → provider order status`. We have
created two genuine orders — `94818182GP238811W` (`219.00 USD`, via the hosted agent loop)
and `4PB280312R3967053` (`10.00 USD`, via the local keys) — read them back from PayPal,
verified OAuth and reached `/v1/notifications/verify-webhook-signature`, and exercised the
`--resume-order` flow twice. **Both are still `PAYER_ACTION_REQUIRED`; nothing has been
approved, captured or charged.** `SANDBOX-PROOF.md` says so explicitly.

Four verticals (retail, travel, telecom, entertainment), eight Next.js apps, a scaffolder
plugin, two installable clients and live demos at https://shop.mimi.money and
https://agentos.mimi.money make it a runnable platform, not a single script. The **Chrome
extension** is a full Manifest V3 client: click the toolbar icon and the entire shop opens
in an extension-hosted tab, with the same `X-Session-Id` contract, SSE chat stream, cart,
orders, memory, activity inspector, Web Speech voice input and cap-bounded checkout receipt.
The **Android app** (`com.acme.shop`, 65 KB debug-signed APK) serves its bundled UI under the
shop's own HTTPS origin through `WebView.shouldInterceptRequest`, so every `/api/` call is
same-origin — with native `SpeechRecognizer`, hardware Back handling, LIVE/OFFLINE status
and external handoff of the PayPal approval link to the device browser. Neither client holds
a credential or bypasses a single server-side gate. Both chat composers accept voice input
that only fills the text field — nothing is sent until the human presses Enter or Send.

Scope is honest: the catalogs are fictional ACME fixtures; no live merchants, revenue,
production transactions, completed sandbox capture or signed webhook delivery are claimed.

## How we built it

We separated a **control plane** (identity, tenant, session, policy) from a **data plane**
(agent runtimes → typed tools → provenance gates → guardrails → audit events), with commerce
backends owning catalog/pricing truth and a payment orchestration layer owning money.
`commerce-common` supplies the shared fencing, memory, presentation, execution and payment
primitives; a rule enforced inside the tool executor holds on all three runtimes.

- **Core stack:** Python 3.11+, FastAPI, Pydantic, httpx, SQLite / SQLAlchemy PostgreSQL,
  MCP (`mcp 1.29.0`), Next.js 16 / TypeScript / React / Tailwind, OpenRouter
  (`deepseek/deepseek-v4.1-flash` with per-role model overrides), pytest, Ruff.
- **PayPal (the centre):** Orders v2 create/capture/read-back, OAuth, deterministic
  `PayPal-Request-Id` idempotency, opaque hashed checkout tokens, amount/currency equality
  checks, `/v1/notifications/verify-webhook-signature`, event-id deduplication, and a
  transactional outbox with optimistic-concurrency leases so a lost capture response or a
  delayed approval never produces a second charge. A startup guard requires
  `COMMERCE_PUBLIC_API_URL` whenever PayPal is enabled, so broken checkout links fail fast.
  Partner Referrals onboarding (`PayPalPartners`) is implemented behind an authenticated
  merchant dependency and deliberately not mounted on the unauthenticated demo.
- **Sponsor and platform tools used:** **Channel3** retail discovery (now enabled with a
  server-side API key; `ch3:` namespaced results normalized into our `ProductDetails`
  contract, with automatic fallback to the local catalog on failure); **AG Studio / AG Grid**
  for the merchant analytics control centre (trial build — a licence key is the one
  outstanding config); **Bryntum Scheduler** for the travel revenue Schedule view (npm trial
  alias, read-only by design); **APIMatic** for OpenAPI contracts exported from the real
  FastAPI apps into an `src/spec` layout for SDK/validation; plus **WooCommerce / Shopify**
  adapters behind `COMMERCE_PLATFORM`. `scripts/check.py` cross-checks tool registries,
  prompts, manifests and docs so the tool surface stays config-derived and prompt-cache
  stable.
- **Safety:** fenced third-party text, forced grounding reads, memory write filters,
  per-item and loop limits, staged merchant changes with guardrails, single-use approval
  capabilities (optionally gated by an injected `COMMERCE_MERCHANT_OPERATOR_TOKEN`), and
  merchant output/iteration budgets that stop `max_tokens` truncation.
- **Clients:** Chrome Manifest V3 (service worker, `chrome.storage.local`,
  `host_permissions`, pinned extension id, Web Speech API) and Android (aapt2, javac, d8,
  zipalign, apksigner, Java, WebView + `JavascriptInterface`, native `SpeechRecognizer`).
  The extension's `host_permissions` make Chrome bypass CORS for the shop origin; the
  Android WebView serves its assets *under* that origin, so no CORS bridge is needed.
- **Deployment:** a self-contained VPS bundle with systemd, an nginx `/api/` reverse proxy
  across two origins, certbot, and build-time `NEXT_PUBLIC_API_URL` inlining.
- **Verification:** 100 Python test files (1197 passed, 3 skipped), `ruff check` and
  `ruff format --check` clean, `check.py` clean, 9/9 TypeScript configs typechecked, both
  retail production builds, 19/19 live API smoke checks, two `stop_reason=end_turn` chat
  turns, Android 18/18 emulator checks twice, and a BrowserOS/Chrome extension functional
  run with zero console/network errors in the main flow. Tests are hermetic:
  `COMMERCE_TESTING` stops a developer's real `.env` from reconfiguring the suite.
- **Open-source discipline:** built on a third-party Apache-2.0 commerce-agent blueprint
  and compliant with §4 — root `LICENSE`, `NOTICE`, `CREDITS.md`, `CHANGES.md` with a dated
  change log, and retained SPDX headers on derived files. New files carry the contributors'
  notice. Apache-2.0 obligations were preserved while user-facing vendor branding was
  removed.

## Challenges we ran into

1. **Spending without credentials.** We reduced the model's payment arguments to two fields
   and moved pricing, snapshot creation and the API call to the host. The approval URL is
   rendered as a UI card and never enters model context.
2. **Trusting model-supplied IDs.** A model can invent or stale product ids. We added
   session-scoped provenance (`seen_products`), server-side re-pricing, and three cap layers,
   with refusal before any payment row or provider call (`SpendCapExceeded`).
3. **Payment ambiguity.** Lost capture responses, delayed approvals and duplicate webhooks
   are normal. Deterministic idempotency keys, immutable snapshots, amount/currency
   equality, verified and deduplicated events, and a durable outbox make recovery paths
   first-class. We later hit a concrete version of this: re-running `--resume-order` tried
   to attach the same PayPal order to a second local row, so we made the resume path reuse
   and rotate the existing quote's bearer token instead of violating the unique constraint.
4. **One kernel, three runtimes — and three clients.** Any rule that matters had to live in
   the shared executor, not in a runtime. Keeping the extension and Android app honest meant
   refusing to add a second backend: both had to consume the *same* HTTP contract. That
   forced two non-obvious solutions — Chrome `host_permissions` for CORS-free extension
   calls, and WebView request interception to serve Android assets under the shop origin.
5. **Two origins, one API.** With no CORS middleware in the FastAPI app, we proxied `/api/`
   in both nginx server blocks and learned the hard way that `NEXT_PUBLIC_API_URL` is
   inlined at *build* time, not runtime.
6. **Real credentials change everything.** Once the sandbox keys were live, a missing
   `COMMERCE_PUBLIC_API_URL` broke every app import, and `pytest` started reading a
   developer's `.env` at collection time. We made the suite hermetic and documented the
   startup guard. Merchant turns also began hitting `stop_reason: max_tokens`; we raised the
   output budget to 4096, bounded tool/analysis iterations and added a per-role model
   override.
7. **Evidence under a deadline.** The hosted demo now has credentials, but a PayPal order
   is app-scoped: our local keys return `INVALID_RESOURCE_ID` for the hosted order, and
   buyer approval still needs a sandbox **personal** account. We chose not to invent an
   order id, capture id or webhook event. `SANDBOX-PROOF.md` records two real, uncaptured
   orders and every missing step as `NOT RECORDED`; fixture screenshots are labelled;
   `TEST-REPORT.md` states exactly what was and was not verified.

## Accomplishments that we're proud of

- **PayPal Sandbox as a governed, exercised capability** — OAuth, Orders v2 create and
  read-back, hosted checkout with the JavaScript SDK, webhook signature verification
  reaching the real endpoint, and an idempotent `--resume-order` proof harness. Registered
  in the tool registry, both runtimes and the storefront MCP server, on by default with a
  loud missing-credential warning and an explicit `--no-paypal` offline switch.
- **Bounded auto-buy with a visible receipt** — cap, immutable cart hash and order id —
  giving an auditable chain of custody without ever placing a payment credential in a
  prompt, transcript, memory, browser extension or APK.
- **An OS rather than a demo**: two agents × three runtimes × four verticals × eight web
  apps, plus a scaffolder plugin, a Chrome extension, an Android app and one shared safety
  layer, so a merchant can replace the ACME fixtures with their own catalog without
  rewriting the safety model or the client contract.
- **Sponsor tools as additive, not load-bearing**: Channel3, AG Studio/AG Grid, Bryntum and
  APIMatic each extend a working system and degrade cleanly when their key or licence is
  absent; no sponsor credential reaches the browser or the model.
- **Verification discipline**: 100 test files / 1197 passing tests, `check.py`
  cross-checking registries, prompts, manifests and docs, nine TypeScript configs, two
  production builds, 19/19 live API checks, Android 18/18 emulator checks, a BrowserOS
  extension run, and real screenshots with capture provenance and regeneration scripts.
- **A shipped public deployment** with two live origins anyone can open without installing
  anything, plus two installable clients that need no separate server.
- **Intellectual honesty**: no fabricated transaction identifiers, a deliberately
  `PENDING` proof record, a labelled component fixture instead of fake transaction evidence,
  and an explicit scope note that this is a developer platform, not a live merchant
  deployment.

## What we learned

The hard problem in agentic commerce is **authority, not intelligence** — the most valuable
design work was deciding what the model is *not* allowed to do. We also learned that
instructions are not controls: a rule written only in a system prompt fails on a different
runtime or a different model, while a rule inside the tool call holds everywhere — and, as
it turned out, holds in a browser extension and a WebView too.

Payments punish ambiguity. Idempotency keys, immutable snapshots, amount/currency equality
checks, webhook verification and a transactional outbox turned out to be the real feature;
the happy-path API call was the easy part. A real sandbox also teaches scope the hard way:
an order created by one REST app is invisible to another, so "we have a pending order" is
not the same as "we can finish that order". Prompt caching turned out to be an architectural
constraint as well — one dynamically generated tool definition can silently zero the cache
hit rate, so the tool surface has to be config-derived and measurable.

Building three clients taught us that a well-defined host boundary is the cheapest form of
portability: the extension and the Android app needed no new authorization logic, no token
handling and no second catalog, only a way to reach the same `/api/` origin. Finally, honesty
is a feature. Judges test what the video depicts, so an honest `PENDING` proof document, a
labelled fixture screenshot and a test report that lists its own gaps are worth more than a
convincing-looking fake order id.

## What's next for PayPal Commerce AI Agent Operating System

**Submission-critical, first:**
1. Complete the one genuine sandbox transaction that is still open: have a sandbox
   **personal** buyer approve `4PB280312R3967053` (or a fresh order from the same app),
   capture it, reconcile a genuinely signed webhook, read back provider status, and let
   `scripts/demo_paypal_order.py --resume-order` regenerate `SANDBOX-PROOF.md` with real
   capture ids and screenshots. The server-side credentials, OAuth, order creation and
   verification path already work — the buyer login and a registered webhook tunnel are the
   two remaining pieces.
2. Record and publish the sub-3-minute public video showing the bounded auto-buy end to
   end across the web storefront, the Chrome extension and the Android app, and put judge
   sandbox credentials only in the Devpost *Testing Instructions* field.
3. Add the outstanding sponsor licences (`NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`, a licensed
   Bryntum package), and evaluate the official `@paypal/agent-toolkit` runtime as an
   additional tool provider while preserving the host-owned money boundary.

**Product, next:** follow the build-out sequence in `docs/commerce-os.md` — authentication
and tenant authorization in front of every host and MCP route; an atomic final-pricing
service for shipping, tax, discounts, inventory reservation and expiry; durable
tenant-scoped session, memory and payment stores; a production `OrderFinalizer` on the
existing outbox; then refunds, disputes, shipment tracking, reconciliation and a
double-entry ledger, followed by rate limits, fraud and sanctions controls, observability,
key rotation and operational runbooks. Beyond that, replace the ACME fixtures with real
WooCommerce/Shopify tenants and the multi-merchant control service, publish eval scorecards
for groundedness, cap enforcement, provenance refusal and cache stability, and turn the
bounded-checkout contract into a portable open specification other merchants can
implement.

---

## "Is your project new, or did it exist before Oct 1, 2026 (9:15 am PT)?"

**Select: New — created during the submission period.**

Paste-ready:

> New — PayPal Commerce AI Agent OS did not exist before October 1, 2026. The first
> commit to our public repository is dated November 5, 2026, and `CHANGES.md` dates all
> additions between 16 October and 7 November 2026, inside the submission period. The
> entire PayPal sandbox integration — Orders v2, `create_paypal_order` with provenance and
> spend-cap gates, bounded auto-buy, webhook verification, the proof harness — plus the
> four sponsor integrations, WooCommerce/Shopify adapters, OpenRouter runtime, Chrome
> extension, Android app, hosted demo and test suites were built during the period.
>
> The project does build on a third-party Apache-2.0-licensed commerce-agent reference
> blueprint (Copyright 2026 Anthropic PBC) that predates the period. This is open-source
> reuse, permitted by the Official Rules' Intellectual Property clause, not a pre-existing
> project of ours: we comply with the licence (`LICENSE`, `NOTICE`, `CREDITS.md`, retained
> SPDX headers) and materially enhance the underlying functionality. `CHANGES.md` records
> the 64 new files and modifications; `CREDITS.md` and `NOTICE` carry the full disclosure.

If the form instead asks for a "significantly updated" explanation (or you prefer the
conservative route of declaring the derived codebase), paste this addendum:

> Relative to that blueprint, the submission-period work adds: the complete PayPal Orders
> v2 payment layer and its safety kernel (immutable cart snapshot, provenance gate, three
> cap layers, idempotency, transactional outbox), the agent's `create_paypal_order` tool,
> bounded auto-buy with a visible receipt, default-on sandbox checkout, four sponsor
> integrations (Channel3, AG Studio/AG Grid, Bryntum, APIMatic), WooCommerce and Shopify
> adapters, an OpenRouter model runtime, a Manifest V3 Chrome extension, a native Android
> app with emulator test evidence, a public two-origin deployment, and 100 Python test
> files (1197 passing tests). Both client applications and their test reports are new in
> this repository. These are recorded in `CHANGES.md`, `SANDBOX-PROOF.md` and
> `TEST-REPORT.md`.

**Do not** claim the whole codebase was written from scratch — the retained Apache-2.0
headers make that plainly false. Disclosing the blueprint is both accurate and the safest
reading of the "New & Existing" and open-source-reuse clauses.

## Tools and technologies (for the Devpost tools field)

```
PayPal sandbox (centre of the project): Orders v2 REST API, PayPal JavaScript SDK,
PayPal Webhooks with /v1/notifications/verify-webhook-signature, PayPal Partner Referrals.
Sponsor/platform tools: Channel3, AG Grid / AG Studio, Bryntum Scheduler, APIMatic OpenAPI
exports, WooCommerce and Shopify adapters.
Model + runtimes: OpenRouter / deepseek-v4.1-flash, Anthropic-compatible provider,
Messages API, Agent SDK, Managed Agents, Model Context Protocol (mcp 1.29.0).
Backend: Python 3.11+, FastAPI, Pydantic, httpx, SQLite, PostgreSQL/SQLAlchemy, pytest,
Ruff. Web: Next.js 16, TypeScript, React, Tailwind, Web Speech API.
Clients: Chrome Manifest V3 (service worker, chrome.storage.local, host_permissions),
Chrome DevTools Protocol / BrowserOS; Android SDK (aapt2, javac, d8, zipalign, apksigner),
Java, WebView + JavascriptInterface, Android SpeechRecognizer, adb + emulator.
Ops: systemd, nginx reverse proxy, certbot, GitHub Actions, Docker-free VPS bundle.
```
