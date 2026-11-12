# PayPal Commerce AI Agent OS — Devpost submission

Paste each `##` section into its matching Devpost field. The tools block is for the
tools/technologies field; the roadmap at the bottom is our own appendix, not a form field.
Everything here is true and checkable in the repository. `DEVPOST-FORM-ANSWERS.md` is the
longer technical version if a judge wants the exact identifiers and test counts.

---

## Inspiration

We kept watching agentic-commerce demos end at the wrong moment. Search, compare, a nicely
formatted cart, and then — a checkout link. The human still had to finish the job. It's a
reasonable place to stop, but it's also exactly where the interesting question starts.

The moment an agent is allowed to spend money, two things have to be true at once: it bought
only what the shopper actually named, and it stayed under the amount the shopper authorized.
Handing a language model a payment credential answers neither. It just makes the mistake
faster.

So we flipped the framing. Instead of building a shopping assistant and bolting a payment
on at the end, we designed the boundary first and let the rest of the system grow around it.
The model gets conversation and tool choice. The host gets identity, prices, credentials and
durable state. Once you draw that line clearly, delegation stops being a leap of faith and
starts being something you can audit.

PayPal Sandbox ended up at the centre of everything. Orders v2, the JavaScript SDK, webhook
signature verification and a real sandbox app gave us a live rail to build against — one that
genuinely fails when you get it wrong. That changed the work. The immutable cart snapshot,
the provenance gate, the three separate cap layers, the idempotency keys, the transactional
outbox: none of those came from a whitepaper. Each one exists because a real sandbox order
will punish you for hand-waving it.

There was a nice surprise waiting at the end. Once all the money authority lived in the host,
the same governed API could serve a web storefront, a Chrome extension and an Android app —
and none of them ever needed to hold a credential. Which leaves us with the question we'd
most like the category to answer: what is the smallest amount of authority an agent actually
needs to finish a checkout, and how do you prove it stayed inside it?

## What it does

PayPal Commerce AI Agent OS is an open-source commerce operating system where a shopping
agent can prepare a real PayPal sandbox order — but only for products a catalog tool actually
returned in that session, only below a cap the shopper set, and never with a payment
credential anywhere near the model. A governed merchant agent runs alongside it on the same
safety kernel. One auditable API powers eight Next.js apps across four verticals, a Chrome
extension and a native Android app.

We built two agents, not one. There's a customer-facing shopping agent that searches,
compares, plans and fills a cart, and a merchant agent that handles pricing, inventory,
campaigns and analytics. Both are defined once — prompt, skills, tool contracts, gates — and
run on three runtimes: the Messages API, the Agent SDK and Managed Agents. A rule enforced
inside the shared tool executor holds on all three. That mattered more than it sounds: a rule
that only lives in a system prompt quietly disappears the moment you change runtime.

PayPal sits inside the loop rather than behind a redirect. When a shopper names items and a
maximum total, the built-in `create_paypal_order` tool prepares a real Orders v2 order. The
model supplies only `product_ids` and `max_amount`. Everything else is the host's job: it
re-reads its own catalog for prices, quantities and currency, freezes a hashed immutable cart
snapshot, and calls PayPal with credentials the model never sees. Three limits stack. The
tool clamps the model's cap to a fixed maximum, `CheckoutService` clamps it again to the
deployment ceiling (`COMMERCE_MAX_ORDER_AMOUNT`, 250.00 USD in our demo), and an over-cap
cart is refused before a single payment row exists. A provenance gate rejects any product id
that a catalog or order tool didn't return in that session, so a confident model can't
invent a SKU into a purchase.

What the shopper sees is a receipt: the authorized cap, the snapshot hash and the PayPal
order id, both on the hosted checkout page and as a card in the chat. The agent creates the
order and stops there. It never captures. The buyer approves on PayPal's own page, and the
host captures, verifies webhook signatures, deduplicates events by id and reconciles the
provider's status. On the merchant side, writes are staged, guardrail-checked and previewed;
clicking Apply mints a short-lived, single-use capability bound to that session, change and
action, so a bare POST to the approval route can't quietly move merchant state.

We should be straightforward about where the sandbox proof stands, because this is the part
people most often fudge. PayPal Sandbox isn't a slide in our deck — it's the test bench and
the standard we hold the evidence to. With real credentials the host reports
`"payments": "paypal"`, the checkout page renders the PayPal SDK with the amount, cap and
snapshot hash, and `scripts/demo_paypal_order.py` drives the full
create → buyer approve → capture → signed webhook → provider status path. We created two
genuine orders, `94818182GP238811W` (219.00 USD, through the hosted agent loop) and
`4PB280312R3967053` (10.00 USD, using local keys), read both back from PayPal, verified
OAuth and reached the real webhook-verification endpoint. Both are still
`PAYER_ACTION_REQUIRED`. Nothing has been approved, captured or charged. We could have typed
a plausible capture id into a markdown file and nobody would have checked until judging day.
We didn't. `SANDBOX-PROOF.md` says PENDING and lists every missing step.

The platform around that is bigger than a single script: retail, travel, telecom and
entertainment verticals, eight Next.js apps, a plugin that scaffolds a new commerce agent,
and live demos at https://shop.mimi.money and https://agentos.mimi.money. Two installable
clients use exactly the same API. The Chrome extension is a full Manifest V3 app — click the
toolbar icon and the whole shop opens in an extension-hosted tab, with the same session
contract, the same streamed chat, cart, orders, memory, activity inspector and the same
cap-bounded checkout receipt. The Android app (com.acme.shop, a 65 KB debug-signed APK)
serves its bundled UI under the shop's own HTTPS origin through WebView request
interception, so every `/api/` call is same-origin; it adds a native speech recognizer,
hardware Back handling, a LIVE/OFFLINE indicator, and hands the PayPal approval link to the
device browser. Neither client holds a credential or skips a single server-side gate. Both
composers take voice dictation that only fills the text field — nothing is sent until a
person presses Enter or Send, which felt like the right amount of humility for a microphone
button next to a payment feature.

A few things we want to be upfront about. The catalogs are fictional ACME fixtures. There
are no live merchants, no revenue, no production transactions, and — as above — no completed
sandbox capture or signed webhook delivery. This is a developer platform and a demo, and
we've tried to write the docs the way we'd want to read them if we were judging.

## How we built it

The shape of the system is a control plane — identity, tenant, session, policy — sitting
above a data plane: agent runtimes, typed tools, provenance gates, guardrails, audit events.
Commerce backends own catalog and pricing truth. A payment orchestration layer owns money.
`commerce-common` holds the shared fencing, memory, presentation, execution and payment
primitives, so the two agents and all three runtimes inherit the same behaviour rather than
reimplementing it.

Under the hood: Python 3.11+, FastAPI, Pydantic, httpx, SQLite with a PostgreSQL/SQLAlchemy
option, MCP, Next.js 16 with TypeScript, React and Tailwind, OpenRouter running
`deepseek/deepseek-v4.1-flash`, pytest and Ruff. We added per-role model overrides because
the merchant portal carries a much larger prompt than the storefront, and a 4096-token
output budget plus bounded tool and analysis loops after we watched a merchant answer get cut
off mid-sentence. Both chat surfaces now finish cleanly.

The PayPal slice is where most of the care went. OAuth, Orders v2 create, capture and
read-back, deterministic `PayPal-Request-Id` idempotency, opaque hashed checkout tokens,
amount and currency equality checks, signature verification through
`/v1/notifications/verify-webhook-signature`, event-id deduplication, and a transactional
outbox with optimistic-concurrency leases. The point of all that plumbing is boring and
important: a lost capture response, a delayed approval or a duplicate webhook should never
produce a second charge. There's also a startup guard that refuses to boot without
`COMMERCE_PUBLIC_API_URL` when PayPal is enabled — we'd rather fail loudly than hand a
shopper a broken checkout link. Partner Referrals onboarding is implemented behind an
authenticated merchant dependency and deliberately left off the unauthenticated demo.

We used the sponsor tools where they genuinely helped, and kept them additive so the demo
still works when a key is missing. Channel3 extends retail discovery (server-side key,
`ch3:` namespaced results normalized into our own product contract, automatic fallback to
the local catalog if it fails). AG Studio and AG Grid back the merchant analytics control
centre — we're on the trial build, so a licence key is the one config still outstanding.
Bryntum Scheduler powers the travel revenue Schedule view, read-only on purpose: pricing
changes still go through staging, preview and approval. APIMatic consumes OpenAPI contracts
exported from the actual FastAPI apps into an `src/spec` layout for validation and SDK work.
WooCommerce and Shopify adapters sit behind `COMMERCE_PLATFORM`. And `scripts/check.py`
cross-checks tool registries, prompts, manifests and docs, because we learned that one
dynamically generated tool definition can quietly wreck the prompt-cache hit rate.

The two clients were an exercise in not taking shortcuts. It would have been easy to give the
extension its own mock API, or bundle a fake catalog into the APK. We didn't want a demo that
only looked like the real thing. Chrome's `host_permissions` let the extension call the shop
origin without a CORS fight; on Android, serving the bundled assets *under* the shop's HTTPS
origin means every API call is same-origin too. No CORS bridge, no token handling in native
code, no second backend.

Deployment is a self-contained VPS bundle: systemd units, an nginx `/api/` reverse proxy
across the two origins, certbot for TLS, and `NEXT_PUBLIC_API_URL` inlined at build time.
That last detail is easy to miss, so it's called out in the deployment guide.

We tested it the way we'd want someone else to. There are 100 Python test files; the full
suite is 1197 passed, 3 skipped. Ruff and `check.py` are clean, all nine TypeScript configs
typecheck, both retail production builds succeed, and a live API smoke run against real
credentials passes 19 of 19 checks — including a merchant apply route that refuses a bare
POST, accepts a minted capability and refuses a replay. Both chat turns ended with
`stop_reason=end_turn`, not a truncation. The Android app passed 18/18 emulator checks
twice; the extension had a clean BrowserOS/Chrome functional run with no console or network
errors in the main flow. We also made the test suite hermetic (`COMMERCE_TESTING`), because
once real keys were on the machine, pytest started reading a developer's `.env` during
collection and that's no way to run a test suite. `TEST-REPORT.md` has the details and the
gaps.

One last piece of housekeeping that we care about: we started from a third-party Apache-2.0
commerce-agent blueprint, so compliance was part of the deliverable, not paperwork. The root
`LICENSE`, `NOTICE`, `CREDITS.md` and `CHANGES.md`, the dated change log, and the retained
SPDX headers on derived files all travel with the code. New files carry our contributors'
notice instead. We removed user-facing vendor branding carefully, and only where the license
allowed it.

## Tools and technologies

```
PayPal sandbox (the centre of the project): Orders v2 REST API, PayPal JavaScript SDK,
PayPal Webhooks with /v1/notifications/verify-webhook-signature, PayPal Partner Referrals.
Sponsor / platform tools: Channel3, AG Grid / AG Studio, Bryntum Scheduler, APIMatic
OpenAPI exports, WooCommerce and Shopify adapters.
Model and runtimes: OpenRouter / deepseek-v4.1-flash, Anthropic-compatible provider,
Messages API, Agent SDK, Managed Agents, Model Context Protocol (mcp 1.29.0).
Backend: Python 3.11+, FastAPI, Pydantic, httpx, SQLite, PostgreSQL / SQLAlchemy,
pytest, Ruff. Web: Next.js 16, TypeScript, React, Tailwind, Web Speech API.
Clients: Chrome Manifest V3 (service worker, chrome.storage.local, host_permissions),
Chrome DevTools Protocol / BrowserOS; Android SDK (aapt2, javac, d8, zipalign,
apksigner), Java, WebView + JavascriptInterface, Android SpeechRecognizer, adb + emulator.
Ops: systemd, nginx, certbot, GitHub Actions, Docker-free VPS bundle.
```

## Challenges we ran into

The first hard problem was spending money without giving the model anything to spend. We
reduced its payment arguments to two fields and moved pricing, snapshot creation and the API
call into the host. Even the approval URL only ever appears as a UI card — it never enters
model context.

Then we had to stop trusting the model's product ids. A language model will happily produce a
plausible SKU that isn't in your catalog, or one it saw three turns ago. Session-scoped
provenance, server-side re-pricing and three cap layers fixed that, with refusal happening
before any payment row or provider call exists.

Payments punish ambiguity more than any other API we've worked with. Lost capture responses,
delayed approvals, duplicate webhooks — all normal. Idempotency keys, immutable snapshots,
amount and currency equality, verified and deduplicated events, and a durable outbox became
the real feature; the happy-path call was the easy part. We even met a smaller version of
this while building the proof harness: re-running `--resume-order` tried to attach the same
PayPal order to a second local row. Now the resume path reuses the existing quote and rotates
its bearer token instead.

Keeping one kernel across three runtimes — and then three clients — was its own discipline.
Anything that mattered had to live in the shared executor. The extension and the Android app
had to consume the same HTTP contract rather than get a convenient second backend, and that
forced the two non-obvious solutions we're happiest with: Chrome host permissions for
CORS-free extension calls, and WebView request interception to serve Android assets under
the shop origin.

Two origins sharing one API taught us that `NEXT_PUBLIC_API_URL` is inlined at build time,
not runtime. We found out the annoying way. And once the real sandbox keys were live, a
missing `COMMERCE_PUBLIC_API_URL` broke every app import, pytest began reading a local `.env`
at collection time, and merchant turns started ending at `max_tokens`. Fixing those three
things — hermetic tests, a documented startup guard, and merchant output/iteration budgets —
was less glamorous than the agent work but made the whole thing actually runnable.

The last challenge is the one we can't code our way out of. The hosted demo has credentials
now, but a PayPal order belongs to the REST app that created it: our local keys get
`INVALID_RESOURCE_ID` for the hosted order. And buyer approval still needs a sandbox
personal account and a registered webhook tunnel. It would be easy to write a convincing
order id, capture id and webhook event into a proof file. We don't think a submission is
worth that. So `SANDBOX-PROOF.md` records two real, uncaptured orders and marks every
missing step `NOT RECORDED`; fixture screenshots are labelled; `TEST-REPORT.md` says exactly
what was and wasn't verified.

## Accomplishments that we're proud of

Most of all, PayPal Sandbox as a governed capability we actually exercised rather than
described. OAuth, a real Orders v2 create and read-back, a hosted checkout page with the
JavaScript SDK, webhook signature verification reaching the real endpoint, and an idempotent
`--resume-order` harness. It's registered in the tool registry, both runtimes and the
storefront MCP server, on by default with a loud warning when credentials are missing and an
explicit `--no-paypal` switch when you want it off.

Then there's the receipt. A bounded auto-buy that shows the cap, the immutable cart hash and
the order id gives you a chain of custody you can actually follow — without a payment
credential ever appearing in a prompt, transcript, memory, browser extension or APK.

We're also proud that it's an OS rather than a demo: two agents, three runtimes, four
verticals, eight web apps, a scaffolder plugin, a Chrome extension, an Android app and one
shared safety layer. Swap the ACME fixtures for a real catalog and you don't rewrite the
safety model or the client contract. The sponsor tools are additive in the same spirit —
each extends a working system and degrades cleanly when its key is absent, and none of their
credentials reach the browser or the model.

The verification discipline matters to us too. 100 test files and 1197 passing tests,
`check.py` keeping registries, prompts, manifests and docs in sync, nine TypeScript configs,
two production builds, 19/19 live API checks, Android 18/18 emulator checks, a BrowserOS
extension run, and screenshots with capture provenance and regeneration scripts. Plus a
public deployment with two live origins anyone can open without installing anything, and two
installable clients that need no separate server.

And, quietly, the intellectual honesty: no fabricated transaction identifiers, a
deliberately PENDING proof record, a labelled component fixture instead of fake transaction
evidence, and a scope note that says plainly this is a developer platform. It's not the
flashiest line in the submission. It's the one we'd want a judge to trust.

## What we learned

The hard problem in agentic commerce is authority, not intelligence. Almost all the valuable
design work was deciding what the model is *not* allowed to do. We also learned that
instructions aren't controls. A rule written only in a system prompt fails on a different
runtime or a different model; a rule inside the tool call holds everywhere — and, as it
turned out, holds in a browser extension and a WebView as well.

Payments punish ambiguity, and a real sandbox teaches scope the hard way: an order created
by one REST app is invisible to another, so "we have a pending order" isn't the same thing
as "we can finish that order". Prompt caching turned out to be an architectural constraint
too — one dynamically generated tool definition can silently zero your cache hit rate, so the
tool surface has to be config-derived and measurable.

Building three clients taught us that a well-defined host boundary is the cheapest form of
portability there is. The extension and the Android app needed no new authorization logic, no
token handling and no second catalog — just a way to reach the same `/api/` origin. And
honesty turned out to be a feature, not a compromise. Judges test what the video depicts. An
honest PENDING proof document, a labelled fixture screenshot and a test report that lists its
own gaps are worth more than a convincing-looking fake order id.

## What's next for PayPal Commerce AI Agent Operating System

The immediate thing is to finish what we started: get a sandbox personal buyer to approve
`4PB280312R3967053` (or a fresh order from the same app), capture it, reconcile a genuinely
signed webhook, and let the proof script regenerate `SANDBOX-PROOF.md` with real capture ids
and screenshots. Then record the short public video across the web storefront, the extension
and the Android app, and put judge credentials only in the testing-instructions field. The
server-side credentials, OAuth, order creation and verification path already work; the buyer
login and a webhook tunnel are the two pieces left.

After that, we've written down a roadmap we could actually start on tomorrow. It's at the
bottom of this document, sequenced so each phase depends only on the ones before it, with
the existing modules named so nobody has to guess where to begin.

---

## Roadmap — what we'd actually build, in order

We deliberately kept this as work items, not aspirations. Each phase names the code that
exists today and the code we'd add, and the ordering follows `docs/commerce-os.md`: you can't
do refunds before final pricing, and you can't do multi-merchant before authentication.
One thing never changes at any phase: the host owns the money, and the model never gets a
credential.

**Phase 0 — Close the evidence gap (days, not architecture).**
Approve and capture one real sandbox order end to end; reconcile a genuinely signed
`PAYMENT.CAPTURE.COMPLETED` through a registered tunnel; regenerate `SANDBOX-PROOF.md` and
`proof/sandbox-transaction.json` from live responses; capture the approval, checkout and
captured-state screenshots; publish the sub-3-minute video; put judge sandbox credentials in
the Devpost testing-instructions field only. Add the outstanding sponsor licences
(`NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`, a licensed Bryntum package) and evaluate the official
`@paypal/agent-toolkit` runtime as an additional tool provider — with the host-owned money
boundary intact. *Already in place:* `scripts/demo_paypal_order.py`, `SANDBOX-PROOF.md`,
`TEST-REPORT.md`, working OAuth and order creation.

**Phase 1 — Identity and tenancy.**
Put authentication and tenant authorization in front of every host route and every MCP
server. Derive principal and tenant from the session, never from a tool argument. Make the
optional `COMMERCE_MERCHANT_OPERATOR_TOKEN` real by having an authenticating proxy inject it,
and decide which operators may hold it. Add login/registration rate limits, CSRF and MFA for
the control service, key rotation and secret backup. *Already in place:*
`examples/demo_common/sessions.py`, `commerce-common/commerce_common/control_store.py`,
`examples/demo_common/approval.py`, `docs/merchant-platform.md`.

**Phase 2 — Final pricing and order finalization.**
Build an atomic final-pricing service for shipping, tax, discounts, inventory reservation
and quote expiry, then revalidate it immediately before any PayPal order is created. Supply a
store-specific `OrderFinalizer` to the existing outbox worker (`drain_finalizations`),
requiring the destination to deduplicate checkout ids. WooCommerce native checkout already
creates its order, so that adapter reads it back instead of creating a second one. *Already
in place:* the outbox and optimistic-concurrency leases in
`commerce-common/commerce_common/payments.py`, `docs/payments.md`,
`shopping-agent/core/shopping_agent/woocommerce.py`.

**Phase 3 — Durable state and the rest of the money lifecycle.**
Move sessions, payment records, memory and staged changes to backed-up, tenant-scoped
PostgreSQL (`PostgresPaymentStore` already exists as the seam). Replace the in-process
app-event queue with a durable event bus. Then add refunds, voids, disputes, shipment
tracking, reconciliation and a double-entry ledger as separate permissioned workflows —
never as model tools. *Already in place:* `commerce-common/commerce_common/payment_store.py`,
the WooCommerce refund bridge with its "ambiguous results are not retried" rule,
`docs/merchant-platform.md`.

**Phase 4 — Real, multi-merchant stores.**
Mount the Partner Referrals onboarding routes behind the new authenticated merchant
dependency, resolve seller identity server-side, and give each verified merchant its own
isolated `CheckoutService` over a shared payment store. Bring real WooCommerce and Shopify
tenants in through invitation-gated registration with encrypted credentials, add Shopify
clearing journals, and persist long-term agent memory per tenant. *Already in place:*
`commerce-common/commerce_common/paypal_partners.py`,
`examples/demo_common/onboarding.py`, `shopping-agent/core/shopping_agent/shopify.py`,
`integrations/woocommerce/`, the control service in `docs/merchant-platform.md`.

**Phase 5 — Clients people can actually install.**
Publish the extension to the Chrome Web Store (replacing the pinned unpacked id) and ship a
release-signed Android build instead of the debug APK. Add order-status push notifications,
a proper microphone-permission flow, a read-only offline catalog, localization and WCAG
accessibility across all three surfaces. Put extension CDP checks and Android emulator checks
into CI alongside the existing GitHub Actions workflow. *Already in place:*
`Chrome extension/`, `Android App/`, `.github/workflows/ci.yml`, both client TEST-REPORTs.

**Phase 6 — Evaluation and an open contract.**
Publish eval scorecards for groundedness, cap enforcement, provenance refusal and
prompt-cache stability, with `scripts/check.py` extended to run them. Turn the
bounded-checkout contract (immutable snapshot, provenance gate, cap clamping, host-only
capture) into a portable open specification plus a conformance suite any merchant can run,
and publish APIMatic-generated SDKs from the exported OpenAPI specs. *Already in place:*
`scripts/check.py`, `scripts/export_openapi.py`, `integrations/apimatic/`.

**Phase 7 — Operations.**
Rate limits, fraud and sanctions controls, distributed tracing over tool and payment events,
backup/restore drills, deletion workflows, SLOs and operational runbooks. Re-audit the
Apache-2.0 notices at each release so the change log stays accurate. *Already in place:*
`CHANGES.md`, `NOTICE`, `CREDITS.md`, the systemd/nginx deployment bundle.

The through-line is that none of these phases ask the model for more authority. They make
the host more trustworthy. If we do this right, an agent three years from now will still only
be allowed to say *which products* and *how much* — and anyone reading the audit trail will
be able to prove it.
