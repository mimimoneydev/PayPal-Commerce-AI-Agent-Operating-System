# PayPal AI Hackathon — submission copy

> **Draft for the submitter. Do not paste until the checklist at the bottom is complete.**
>
> The demo URLs and public repository URL below are real and were verified live. Every
> remaining `{{PLACEHOLDER}}` must be replaced with a real value before pasting. Nothing in
> this file invents an order id, a capture id, a sandbox credential, a video URL, or a usage
> metric. Where evidence does not exist yet, the text says so or omits the claim.
>
> **For the seven Devpost form questions** (Inspiration, What it does, How we built it,
> Challenges, Accomplishments, What we learned, What's next), paste from
> [`DEVPOST-SUBMISSION-HUMAN.md`](DEVPOST-SUBMISSION-HUMAN.md) — the human-voice version,
> with a phased, implementable roadmap at the bottom.
> [`DEVPOST-FORM-ANSWERS.md`](DEVPOST-FORM-ANSWERS.md) is the longer technical version with
> exact identifiers and test counts. Both cover PayPal Sandbox as the project's centre, the
> sponsored tools (Channel3, AG Studio/AG Grid, Bryntum, APIMatic), the Chrome extension and
> Android app, and the verified 1197-test evidence. This file remains the title, description,
> tools, testing-instructions and checklist reference.

---

## 1. Title

```
PayPal Commerce AI Agent OS — bounded, provable agentic checkout
```

## 2. One-line summary

```
An AI shopping agent that can actually complete a PayPal sandbox purchase — but never above
the cap the shopper set, and never with a payment credential in the model's context.
```

## 3. Text description (paste into the Devpost description field)

AI shopping assistants are good at recommending products and bad at finishing the job. The
moment an agent is allowed to spend money, two questions appear at once: can it prove it only
bought what the customer asked for, and can it prove it stayed inside the amount the customer
authorized? Handing a language model a payment credential answers neither.

**PayPal Commerce AI Agent OS** is an open-source commerce operating system that puts PayPal
*inside* the agent loop rather than behind a checkout link. Its shopping agent searches,
compares, plans, fills a cart and — when a customer names both the items and a maximum total —
calls a built-in `create_paypal_order` tool that prepares a real PayPal Orders v2 order. That
tool is registered in the tool registry, both agent runtimes, and the storefront MCP server,
so PayPal is a first-class agent capability, not an optional bolt-on.

The design deliberately keeps the model away from money. The model supplies **only**
`product_ids` and `max_amount`. The host re-reads its own catalog for prices, quantities and
currency; freezes an immutable, hashed cart snapshot; and calls PayPal with credentials that
never enter model context. Three independent limits apply: the tool clamps the model-supplied
cap to a fixed maximum, the checkout service clamps it again to a deployment ceiling set by
`COMMERCE_MAX_ORDER_AMOUNT`, and an over-cap cart is refused *before any payment row is
written*. Every `product_id` must also have come from a catalog or order tool in that same
session — a provenance gate that stops the model from inventing products.

The result is a visible receipt: the authorized cap, the cart snapshot hash, and the PayPal
order id appear on both the hosted checkout page and the in-chat checkout card. The agent
**creates** an order; it never captures one. The customer approves on PayPal's page and the
host captures, verifies webhook signatures, deduplicates events, and reconciles status. The
hosted checkout page uses PayPal's JavaScript SDK; the server uses Orders v2 with OAuth,
`PayPal-Request-Id` idempotency, amount/currency equality checks, and a durable SQLite or
PostgreSQL payment store with a transactional order-finalization outbox. Lost capture
responses and delayed approval events are handled without issuing a second charge.

PayPal is on by default: `scripts/run_demo.py` enables sandbox checkout whenever credentials
are present, prints a loud warning when they are missing, and offers `--no-paypal` as the
explicit offline mode. `scripts/demo_paypal_order.py` executes the full
`create → buyer approve → capture → signed webhook → provider order status` path against
`api-m.sandbox.paypal.com`; it refuses live mode and writes proof only from real responses.
Its checked-in report is `SANDBOX-PROOF.md`.

The rest of the OS is a coherent, runnable product rather than a single script: a shopping
agent and a governed merchant agent, each defined once as prompt + skills + tool contracts +
gates and run through three compatible runtimes (Messages API, Agent SDK, Managed Agents);
four vertical demo applications (retail, travel, telecom, entertainment) across eight Next.js
apps; a plugin that scaffolds a new commerce agent; and a safety layer covering fencing,
provenance, memory validation, and AI auto-approval of every compliant merchant write. The LLM
runs through OpenRouter (`deepseek/deepseek-v4.1-flash` by default). Sponsor integrations
include Channel3 retail discovery, AG Grid analytics in the merchant control center, a Bryntum
travel occupancy scheduler, and APIMatic-ready OpenAPI exports. The suite has 98 test files;
`pytest` and `python scripts/check.py` validate the tool registries, prompts, manifests and
documentation together.

The same governed backend powers **three clients**. Alongside the hosted web storefront and
merchant portal, the repository ships a native **Android app** (`com.acme.shop`, installable
APK, `Android App/`) and a **Manifest V3 Chrome extension** (toolbar-launched shop tab,
`Chrome extension/`). Neither bundles a catalog, a fake payment or a second backend: both call
the identical live `/api/` contract with the same `X-Session-Id` session, SSE chat stream,
cart, orders, memory and PayPal safety gates. On Android a `WebView` serves the bundled client
under the shop's own HTTPS origin so all API calls are same-origin; the extension uses
`host_permissions` and `chrome.storage.local`. The Android app passed **18/18** automated
checks on an Android 17 emulator, and the extension passed a BrowserOS / Chrome for Testing
functional run — both test reports and screenshots are checked in, and both clients have
their own README with build, install and test commands.

**What is genuinely new in this submission period (1 Oct – 12 Nov 2026):** the PayPal Orders
v2 payment layer, the `create_paypal_order` agent tool and its provenance/cap gates, bounded
auto-buy with a visible receipt, default-on sandbox checkout, the sandbox proof harness,
commerce-platform adapters (WooCommerce, Shopify), the OpenRouter model runtime, the sponsor
integrations, the native Android app and Manifest V3 Chrome extension clients with their
automated test reports and screenshots, and the architecture diagram. The core OS changes are
recorded in `CHANGES.md`; both client applications and their test evidence are new in this
repository. The project builds on a third-party Apache-2.0-licensed
commerce-agent blueprint; it complies with that license (root `LICENSE`, `NOTICE`,
`CREDITS.md`, retained source notices) and materially enhances the underlying functionality
as the hackathon's open-source reuse rule requires.

The repository README includes eight real screenshots of the running retail demo — storefront,
fenced product cards, grounded comparison, the cap receipt card, cart, merchant workspace,
catalog and staged-change approval — plus screenshots of the Android app and Chrome extension,
with capture provenance and a script to regenerate the retail set.
The receipt frame is explicitly labelled a component fixture; it is not presented as a
transaction.

**Try it now (no install needed):** the storefront is live at
**https://shop.mimi.money** (search, compare, add to cart) and the merchant portal at
**https://agentos.mimi.money** (the AI auto-applies compliant changes). Both hosts were
verified responding, and the storefront now runs with PayPal sandbox credentials enabled:
`GET /api/health` reports `"payments": "paypal"`. The agent loop has created one real
sandbox order (`94818182GP238811W`, `PAYER_ACTION_REQUIRED`, `219.00 USD`) behind the
provenance gate and spend cap. **No buyer approval, capture, or completed transaction is
claimed** — see `SANDBOX-PROOF.md` for the honest partial state and section 6.4 for the
exact hosted-demo status. The same governed API also powers two installable clients: a
Manifest V3 **Chrome extension** and a native **Android app** (65 KB APK), both with voice
input and the cap-bounded checkout receipt, neither holding a credential — see section 6.4.

**Scope honesty:** the verticals use fictional ACME catalogs and fixture data. This is a
developer platform and demo, not a live merchant deployment. No real customer, real revenue,
or production transaction is claimed.

## 4. Optional insert — add after a real sandbox run

> Only paste this paragraph after `scripts/demo_paypal_order.py` has completed against a real
> sandbox app and `SANDBOX-PROOF.md` has been regenerated with genuine values.

```
A complete sandbox transaction is recorded in SANDBOX-PROOF.md: PayPal order {{ORDER_ID}},
capture {{CAPTURE_ID}}, provider status COMPLETED, and the signed webhook event {{EVENT_ID}},
with screenshots of the approval page, the cap receipt, and the captured state in
proof/screenshots/.
```

## 5. Tools and technologies (paste into the tools/technologies field)

```
PayPal sandbox (centre of the project): Orders v2 REST API, PayPal JavaScript SDK,
PayPal Webhooks (signature verification), PayPal Partner Referrals;
OpenRouter / deepseek-v4.1-flash; Python 3.11+,
FastAPI, Pydantic, SQLite, PostgreSQL/SQLAlchemy, httpx; Model Context Protocol (mcp 1.29.0);
Next.js / TypeScript / React / Tailwind; Android SDK (aapt2, javac, d8, zipalign, apksigner),
Java, WebView + JavascriptInterface, Android SpeechRecognizer, Gradle / Android Studio,
adb + Android emulator; Chrome Manifest V3 (service worker, chrome.storage.local,
host_permissions), Web Speech API; Chrome DevTools Protocol, pytest, Ruff;
Channel3, AG Grid / AG Studio, Bryntum, APIMatic.
```

## 6. Testing instructions (paste into the Devpost testing instructions field)

### 6.1 Judge credentials — provide these in this field, never in the repository

| Item | Value |
|---|---|
| Sandbox REST app client id | `{{PAYPAL_SANDBOX_CLIENT_ID}}` |
| Sandbox REST app secret | `{{PAYPAL_SANDBOX_CLIENT_SECRET}}` |
| Sandbox **personal / buyer** account email | `{{BUYER_EMAIL}}` |
| Sandbox **personal / buyer** account password | `{{BUYER_PASSWORD}}` |
| OpenRouter API key (for chat turns) | `{{OPENROUTER_API_KEY}}` |
| Webhook id, if a signed-event demo is provided | `{{PAYPAL_WEBHOOK_ID}}` |
| Storefront demo URL (public, no credentials) | `https://shop.mimi.money` |
| Merchant portal demo URL (public, no credentials) | `https://agentos.mimi.money` |

Create these in the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/):
one sandbox **business** app for the server credentials, one sandbox **personal** account for
buyer approval, and a balance on the buyer account. All values must be sandbox-only. The
repository contains no credentials.

### 6.2 Prerequisites

Python 3.11+, Node 22, npm, git. A PayPal developer account and an OpenRouter key.

### 6.3 Install and run

```bash
git clone https://github.com/mimimoneydev/PayPal-Commerce-AI-Agent-Operating-System.git
cd PayPal-Commerce-AI-Agent-Operating-System
cd PayPal-Commerce-AI-Agent-OS
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
(cd examples && npm ci)
cp .env.example .env
```

Fill `.env` with the values from section 6.1:

```text
OPENROUTER_API_KEY=...
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_ENVIRONMENT=sandbox
PAYPAL_WEBHOOK_ID=...
COMMERCE_MAX_ORDER_AMOUNT=250.00
```

Then start the retail demo (API on :8000, storefront on :3000):

```bash
python scripts/run_demo.py retail
```

`--all` also starts the merchant portal on :3100; `--merchant` starts only the portal;
`--no-paypal` runs the same UI in explicit offline mode with no PayPal routes. Browsing the
catalog, the product pages, and the portal widgets needs no credentials at all.

### 6.4 Hosted demo (fastest path, no install)

| Surface | URL | What to do |
|---|---|---|
| Storefront | **https://shop.mimi.money** | Search, compare, add to cart. |
| Merchant portal | **https://agentos.mimi.money** | Ask for a price, inventory or campaign change; the AI stages, guardrail-checks and auto-applies it, with an audit line. |

Both hosts need no credentials to browse. With sandbox credentials enabled, ask the shopping
agent to buy items *"up to $X"* — the bounded auto-buy tool returns a visible receipt with
the cap, the immutable cart hash and the PayPal order id, and nothing is charged until the
buyer approves on PayPal's page.

**Two installable clients hit the same live API** (no install needed for the hosted URLs above):

| Client | Steps | Evidence |
|---|---|---|
| Android app | `cd "Android App" && ANDROID_HOME="$HOME/Library/Android/sdk" ./build.sh`, then `adb install -r apk/ACME-Shop.apk && adb shell am start -n com.acme.shop/.MainActivity`; or sideload the prebuilt `apk/ACME-Shop.apk` | `Android App/TEST-REPORT.md` — 18/18 CDP checks on an Android 17 emulator, results.json + 10 screenshots |
| Chrome extension | `chrome://extensions` → Developer mode → **Load unpacked** → `Chrome extension/`; then the **A** toolbar icon or `Alt+Shift+A` | `Chrome extension/TEST-REPORT.md` — BrowserOS / Chrome for Testing functional run, screenshots |

> **Current hosted-demo state (re-verified after credentials were added).** Both hosts
> return HTTP 200. `GET https://shop.mimi.money/api/health` now reports
> `"model": "deepseek/deepseek-v4.1-flash"` and `"payments": "paypal"`; the
> `/api/payments/paypal/...` routes are registered and the hosted checkout page renders
> the PayPal sandbox SDK, the amount, the cap and the immutable cart snapshot hash. The
> merchant portal chat and its change preview cards also respond; the AI auto-applies
> compliant changes (a human gate is opt-in with `MERCHANT_REQUIRE_HOST_APPROVAL=1`). Optional
> integrations still needing a key: Channel3 search (`CHANNEL3_API_KEY`) and an AG Studio
> licence (`NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`, currently the trial build).
>
> A real bounded auto-buy order was created through the agent loop on the storefront:
> `94818182GP238811W`, `219.00 USD`, cap `250.00 USD`, status `PAYER_ACTION_REQUIRED`.
> Its hosted checkout draft has since expired. That order belongs to the hosted app's PayPal
> REST credentials; with a different local app's credentials PayPal returns
> `INVALID_RESOURCE_ID`, so it can only be resumed with the app that created it. A second
> order, `4PB280312R3967053` (`10.00 USD`, `PAYER_ACTION_REQUIRED`), was created and read
> back with the local `.env` keys, and `--resume-order` was exercised twice against it.
> **Nothing has been approved, captured, or charged, and no capture id or signed webhook is
> claimed.** Unfinished steps 5–7 below still require a sandbox buyer account and a
> registered webhook tunnel. See `SANDBOX-PROOF.md` for the exact evidence.

### 6.5 What to test, in order

1. **Ordinary agent loop.** Open `http://localhost:3000` (or https://shop.mimi.money for
   browsing) and say:
   *"I'm taking my partner and our 6-year-old camping for the first time next month. We need
   a tent — nothing too heavy to deal with, ideally under $250."*
   Then: *"Compare the top two options for me — mostly care about space and ease of setup."*
   Expect fenced product cards, a grounded comparison, and an add-to-cart action.

2. **Bounded auto-buy (the PayPal-in-the-loop feature).** In a fresh session, first let a
   catalog tool return a product, then say:
   *"Buy that tent for me, but do not spend more than $200 total."*
   Expect the agent to call `create_paypal_order` and return a checkout card showing a PayPal
   order id, the authorized cap, the immutable cart snapshot hash, and an approval link.
   Confirm the model text contains **no** bearer checkout URL and that the card says nothing
   has been charged yet.

3. **Cap enforcement.** Repeat with a cap below the server-priced cart total. Expect
   `SpendCapExceeded`: the order is refused *before* any payment row or PayPal order exists.
   Also verify the ceiling: set `COMMERCE_MAX_ORDER_AMOUNT=5.00`, restart, and confirm a
   larger cart is refused even when the shopper names a larger cap.

4. **Provenance gate.** Ask the agent to buy a made-up product id that no catalog tool
   returned this session. Expect a refusal, not an order.

5. **Buyer approval and capture.** Open the approval link, log in with the sandbox **buyer**
   account from section 6.1, approve, and return to the hosted checkout page. Expect the
   receipt to show `COMPLETED`, the capture id, and the same cart hash. The host captures;
   the agent never does.

6. **Webhook reconciliation.** With `PAYPAL_WEBHOOK_ID` set and a public tunnel registered
   for `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`,
   expect a genuinely signed event to be verified through
   `/v1/notifications/verify-webhook-signature` and deduplicated by event id.

7. **Full reproducible proof.** `python scripts/demo_paypal_order.py --check` (config only,
   no network), then `python scripts/demo_paypal_order.py` (opens the approval URL, waits for
   the buyer, captures, reads provider status, verifies the webhook, and writes
   `proof/sandbox-transaction.json` + `SANDBOX-PROOF.md`). To finish an order that already
   exists instead of making a second one, add
   `--resume-order 4PB280312R3967053 --amount 10.00 --currency USD --cap 25.00` (use the
   id belonging to whatever PayPal app your credentials belong to). It verifies the
   provider's own purchase amount before binding any local state, is safe to re-run, and
   never posts a second capture. This script refuses `PAYPAL_ENVIRONMENT=live` and never
   fabricates identifiers.

8. **Merchant agent and approval gate.** `python scripts/run_demo.py retail --all`, open
   `http://localhost:3100`, and ask *"What needs my attention this morning?"* followed by a
   restock request. Expect a staged change preview that does nothing until a person clicks
   Approve on the card.

9. **Automated checks.**

   ```bash
   pip install -r requirements-dev.txt
   ruff check . && pytest && python scripts/check.py
   python scripts/verify_all.py
   ```

### 6.6 Troubleshooting

- Missing PayPal credentials produce a loud startup warning; the UI still runs in offline
  mode. Use `python scripts/run_demo.py retail --no-paypal` to make that explicit.
- Chat needs `OPENROUTER_API_KEY`; `python3 scripts/test_openrouter.py` checks connectivity
  and tool calling without the UI.
- `--no-paypal` sets `COMMERCE_PAYPAL_DISABLED=1` and clears the credentials for the API
  process. `enable_agentic_payments=False` removes the agent's PayPal tool.
- Ports are preferences: a busy port moves the server to the next free one.

## 7. Submission URLs

| Field | Value |
|---|---|
| Public code repository | `https://github.com/mimimoneydev/PayPal-Commerce-AI-Agent-Operating-System` |
| Demo video (public YouTube, < 3 min) | `{{YOUTUBE_URL}}` |
| Hosted demo — storefront | `https://shop.mimi.money` |
| Hosted demo — merchant portal | `https://agentos.mimi.money` |
| Gallery images (upload from the repo, no upload URL needed) | `PayPal-Commerce-AI-Agent-OS/docs/screenshots/01-storefront-home.png`, `04-bounded-autobuy-receipt.png`, `06-merchant-home.png`, `08-staged-change-approval.png` |

## 8. Before you submit — checklist

- [x] Public GitHub repo is live at
      `https://github.com/mimimoneydev/PayPal-Commerce-AI-Agent-Operating-System` with the
      Apache-2.0 `LICENSE`; all local changes are committed and pushed (2 commits, clean
      working tree). The demo URLs and public repo URL in this file are real and verified.
- [ ] Replace the remaining `{{PLACEHOLDER}}` values: judge credentials in section 6.1,
      `{{YOUTUBE_URL}}` in section 7, and the real order / capture / event ids in section 4.
      Put judge credentials in the Devpost testing instructions field, never in the repo.
- [x] PayPal sandbox credentials and the OpenRouter key are enabled on the VPS;
      `GET https://shop.mimi.money/api/health` reports `"payments": "paypal"`. Optional
      keys still outstanding: `CHANNEL3_API_KEY`, `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY`.
- [ ] README screenshots are already present in `PayPal-Commerce-AI-Agent-OS/docs/screenshots/`
      and are labelled honestly. Still to do: approve a pending sandbox order
      (`4PB280312R3967053` for the local `.env` app) with the buyer account,
      complete capture + signed webhook,
      regenerate `SANDBOX-PROOF.md` (resume mode), capture approval / receipt /
      captured-state screenshots into `proof/screenshots/`, then paste the optional
      paragraph in section 4.
- [ ] Record and publish the < 3 minute YouTube video showing the bounded auto-buy end to
      end. No third-party trademarks or copyrighted music.
- [ ] Verify the project "functions as depicted in the video" — the rules require it.
- [ ] All materials in English. Add the sponsor prize categories being entered, if any.
- [ ] Note the prize cap rule: one Grand Prize + one Sponsor Prize, **or** one Honorable
      Mention + one Sponsor Prize.
